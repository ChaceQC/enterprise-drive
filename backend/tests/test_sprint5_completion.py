from __future__ import annotations

from datetime import timedelta
from io import BytesIO
from uuid import UUID

import pytest
from httpx import AsyncClient
from PIL import Image
from pypdf import PdfWriter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.security import utc_now
from app.infrastructure.search.content_extraction import TesseractOcrEngine
from app.infrastructure.storage.testing import InMemoryStorageAdapter
from app.modules.audit.models import AuditLog, OutboxEvent
from app.modules.audit.repository import AuditRepository
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.auth.repository import AuthRepository
from app.modules.file.models import FileBlob, FileVersion, Node
from app.modules.org.repository import OrgRepository
from app.modules.org.service import OrgService
from app.modules.preview.lifecycle import PreviewArtifactLifecycleService
from app.modules.preview.models import PreviewArtifact
from app.modules.preview.repository import PreviewRepository
from app.modules.search.extractors import (
    ImageOcrTextExtractor,
    OfficeDocumentTextExtractor,
    PdfTextExtractor,
    TextExtractionContext,
    TextExtractionError,
)
from app.modules.share.lifecycle import ShareLifecycleService
from app.modules.share.models import (
    Share,
    ShareAccessLog,
    ShareNotification,
    ShareRecipientGrant,
)
from app.modules.share.recipient_grants import ShareRecipientGrantService
from app.modules.share.repository import ShareRepository
from app.modules.space.models import Space
from app.workers.share_tasks import ShareRecipientRebuildPublisher
from tests.helpers import client as client
from tests.helpers import create_second_user, create_space, login, seed_admin
from tests.helpers import session_factory as session_factory
from tests.helpers import settings as settings
from tests.helpers import storage_adapter as storage_adapter


class FakeOcrEngine:
    def __init__(self) -> None:
        self.image_calls = 0
        self.pdf_calls = 0

    def extract_image(self, content: bytes, context: TextExtractionContext) -> str:
        self.image_calls += 1
        return f"IMAGE:{context.name}:{len(content)}"

    def extract_pdf(
        self,
        content: bytes,
        context: TextExtractionContext,
        *,
        max_pages: int,
    ) -> str:
        self.pdf_calls += 1
        return f"PDF:{context.name}:{max_pages}:{len(content)}"


class FakeOfficeConverter:
    def convert_to_pdf(self, content: bytes, context: TextExtractionContext) -> bytes:
        del content, context
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        output = BytesIO()
        writer.write(output)
        return output.getvalue()


async def _create_instant_file(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    csrf_token: str,
    *,
    tenant_id: str,
    space_id: str,
    parent_id: str,
    content_hash: str,
    file_name: str = "内部分享.txt",
    size_bytes: int = 128,
) -> dict[str, object]:
    async with session_factory() as session:
        session.add(
            FileBlob(
                tenant_id=UUID(tenant_id),
                hash_algo="sha256",
                content_hash=content_hash,
                size_bytes=size_bytes,
                storage_key=f"objects/test/{content_hash}",
                mime_type="text/plain",
                ref_count=0,
            )
        )
        await session.commit()
    response = await client.post(
        "/api/v1/uploads/init",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "space_id": space_id,
            "parent_id": parent_id,
            "file_name": file_name,
            "size_bytes": size_bytes,
            "content_hash": content_hash,
            "hash_algo": "sha256",
            "mime_type": "text/plain",
        },
    )
    assert response.status_code == 201
    return dict(response.json())


@pytest.mark.asyncio
async def test_internal_share_received_items_download_notification_and_revoke(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    storage_adapter: InMemoryStorageAdapter,
) -> None:
    await seed_admin(session_factory, settings)
    member_id = await create_second_user(session_factory)
    admin_csrf = await login(client)
    space = await create_space(client, admin_csrf, slug="sprint5-internal-share")
    file_payload = await _create_instant_file(
        client,
        session_factory,
        admin_csrf,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        content_hash="4" * 64,
    )
    create_response = await client.post(
        "/api/v1/shares",
        headers={"X-CSRF-Token": admin_csrf},
        json={
            "share_type": "internal",
            "root_node_id": file_payload["node_id"],
            "permission": "download",
            "recipients": [{"subject_type": "user", "subject_id": str(member_id)}],
            "max_views": 2,
            "max_downloads": 1,
        },
    )
    assert create_response.status_code == 201
    share_id = create_response.json()["id"]

    created_response = await client.get("/api/v1/shares/created")
    assert created_response.status_code == 200
    assert [item["id"] for item in created_response.json()["items"]] == [share_id]

    member_csrf = await login(client, username="member", password="member-password")
    received_response = await client.get("/api/v1/shares/received")
    notification_response = await client.get("/api/v1/shares/notifications")
    items_response = await client.get(
        f"/api/v1/shares/{share_id}/items",
        headers={"X-Request-ID": "req_internal_view"},
    )
    download_response = await client.post(
        f"/api/v1/shares/{share_id}/download",
        headers={"X-CSRF-Token": member_csrf, "X-Request-ID": "req_internal_download"},
        json={"node_id": file_payload["node_id"]},
    )
    second_download = await client.post(
        f"/api/v1/shares/{share_id}/download",
        headers={"X-CSRF-Token": member_csrf},
        json={"node_id": file_payload["node_id"]},
    )

    assert received_response.status_code == 200
    assert received_response.json()["items"][0]["id"] == share_id
    assert notification_response.status_code == 200
    notification = notification_response.json()["items"][0]
    assert notification["share_id"] == share_id
    assert notification["is_read"] is False
    assert items_response.status_code == 200
    assert items_response.json()["access_role"] == "recipient"
    assert items_response.json()["items"][0]["node_id"] == file_payload["node_id"]
    assert download_response.status_code == 200
    assert download_response.json()["download_count"] == 1
    assert download_response.json()["protocol_version"] == "DTP/1"
    assert second_download.status_code == 410
    assert second_download.json()["code"] == "SHARE_DOWNLOAD_LIMIT_EXCEEDED"
    assert storage_adapter.presigned_downloads[-1][1].startswith("objects/test/")

    read_response = await client.post(
        f"/api/v1/shares/notifications/{notification['id']}/read",
        headers={"X-CSRF-Token": member_csrf},
    )
    assert read_response.status_code == 200
    assert read_response.json()["read"] is True

    admin_csrf = await login(client)
    revoke_response = await client.post(
        f"/api/v1/shares/{share_id}/revoke",
        headers={"X-CSRF-Token": admin_csrf},
    )
    assert revoke_response.status_code == 200
    await login(client, username="member", password="member-password")
    after_revoke = await client.get(f"/api/v1/shares/{share_id}/items")
    assert after_revoke.status_code == 410
    assert after_revoke.json()["code"] == "SHARE_REVOKED"

    async with session_factory() as session:
        grant = (
            await session.execute(
                select(ShareRecipientGrant).where(ShareRecipientGrant.share_id == UUID(share_id))
            )
        ).scalar_one()
        stored_notification = (
            await session.execute(
                select(ShareNotification).where(ShareNotification.share_id == UUID(share_id))
            )
        ).scalar_one()
        audit_actions = set(
            (
                await session.execute(
                    select(AuditLog.action).where(
                        AuditLog.action.in_(
                            [
                                "share.internal.accessed",
                                "share.internal.downloaded",
                                "share.notification.read",
                            ]
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        download_log_results = list(
            (
                await session.execute(
                    select(ShareAccessLog.result)
                    .where(ShareAccessLog.action == "download")
                    .order_by(ShareAccessLog.created_at)
                )
            )
            .scalars()
            .all()
        )
    assert grant.is_active is False
    assert stored_notification.invalidated_at is not None
    assert audit_actions == {
        "share.internal.accessed",
        "share.internal.downloaded",
        "share.notification.read",
    }
    assert download_log_results == ["allowed", "denied"]


@pytest.mark.asyncio
async def test_department_membership_rebuild_revokes_and_restores_share_grant(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    member_id = await create_second_user(session_factory)
    admin_csrf = await login(client)
    space = await create_space(client, admin_csrf, slug="sprint5-department-share")
    file_payload = await _create_instant_file(
        client,
        session_factory,
        admin_csrf,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        content_hash="5" * 64,
    )
    create_department = await client.post(
        "/api/v1/admin/departments",
        headers={"X-CSRF-Token": admin_csrf},
        json={"name": "研发部"},
    )
    assert create_department.status_code == 201
    department = create_department.json()
    add_member = await client.post(
        f"/api/v1/admin/departments/{department['id']}/members",
        headers={"X-CSRF-Token": admin_csrf},
        json={"user_id": str(member_id), "expected_version": department["version"]},
    )
    assert add_member.status_code == 201
    department_version = add_member.json()["organization_version"]
    create_share = await client.post(
        "/api/v1/shares",
        headers={"X-CSRF-Token": admin_csrf},
        json={
            "share_type": "internal",
            "root_node_id": file_payload["node_id"],
            "recipients": [{"subject_type": "department", "subject_id": department["id"]}],
        },
    )
    assert create_share.status_code == 201
    share_id = UUID(create_share.json()["id"])

    remove_member = await client.delete(
        f"/api/v1/admin/departments/{department['id']}/members/{member_id}",
        headers={"X-CSRF-Token": admin_csrf},
        params={"expected_version": department_version},
    )
    assert remove_member.status_code == 200

    async with session_factory() as session:
        repository = ShareRepository(session)
        publisher = ShareRecipientRebuildPublisher(
            recipient_grant_service=ShareRecipientGrantService(
                repository=repository,
                auth_repository=AuthRepository(session),
                org_service=OrgService(repository=OrgRepository(session)),
            )
        )
        event = (
            (
                await session.execute(
                    select(OutboxEvent).where(
                        OutboxEvent.event_type == "share.recipients_rebuild_requested"
                    )
                )
            )
            .scalars()
            .all()[-1]
        )
        await publisher.publish(event)
        await session.commit()
        grant = (
            await session.execute(
                select(ShareRecipientGrant).where(
                    ShareRecipientGrant.share_id == share_id,
                    ShareRecipientGrant.user_id == member_id,
                )
            )
        ).scalar_one()
        assert grant.is_active is False

    await login(client, username="member", password="member-password")
    denied = await client.get(f"/api/v1/shares/{share_id}/items")
    assert denied.status_code == 404

    admin_csrf = await login(client)
    department_detail = await client.get(f"/api/v1/admin/departments/{department['id']}")
    restored_member = await client.post(
        f"/api/v1/admin/departments/{department['id']}/members",
        headers={"X-CSRF-Token": admin_csrf},
        json={
            "user_id": str(member_id),
            "expected_version": department_detail.json()["version"],
        },
    )
    assert restored_member.status_code == 201

    async with session_factory() as session:
        repository = ShareRepository(session)
        await ShareRecipientGrantService(
            repository=repository,
            auth_repository=AuthRepository(session),
            org_service=OrgService(repository=OrgRepository(session)),
        ).reconcile_share(
            tenant_id=UUID(str(space["tenant_id"])),
            share_id=share_id,
        )
        await repository.commit()

    await login(client, username="member", password="member-password")
    restored = await client.get(f"/api/v1/shares/{share_id}/items")
    assert restored.status_code == 200


@pytest.mark.asyncio
async def test_share_expiry_lifecycle_invalidates_recipient_grants_and_notifications(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    member_id = await create_second_user(session_factory)
    admin_csrf = await login(client)
    space = await create_space(client, admin_csrf, slug="sprint5-share-expiry")
    file_payload = await _create_instant_file(
        client,
        session_factory,
        admin_csrf,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        content_hash="7" * 64,
    )
    create_share = await client.post(
        "/api/v1/shares",
        headers={"X-CSRF-Token": admin_csrf},
        json={
            "share_type": "internal",
            "root_node_id": file_payload["node_id"],
            "recipients": [{"subject_type": "user", "subject_id": str(member_id)}],
            "expires_at": (utc_now() + timedelta(minutes=5)).isoformat(),
        },
    )
    assert create_share.status_code == 201
    share_id = UUID(create_share.json()["id"])
    tenant_id = UUID(str(space["tenant_id"]))
    async with session_factory() as session:
        share = await session.get(Share, share_id)
        assert share is not None
        share.expires_at = utc_now() - timedelta(minutes=1)
        await session.commit()

    async with session_factory() as session:
        repository = ShareRepository(session)
        result = await ShareLifecycleService(
            repository=repository,
            recipient_grant_service=ShareRecipientGrantService(
                repository=repository,
                auth_repository=AuthRepository(session),
                org_service=OrgService(repository=OrgRepository(session)),
            ),
            audit_service=AuditService(repository=AuditRepository(session)),
        ).expire_shares(
            tenant_id=tenant_id,
            limit=10,
        )

    assert result.to_dict() == {
        "scanned": 1,
        "expired": 1,
        "grants_deactivated": 1,
    }
    async with session_factory() as session:
        share = await session.get(Share, share_id)
        grant = (
            await session.execute(
                select(ShareRecipientGrant).where(
                    ShareRecipientGrant.share_id == share_id,
                    ShareRecipientGrant.user_id == member_id,
                )
            )
        ).scalar_one()
        notification = (
            await session.execute(
                select(ShareNotification).where(
                    ShareNotification.share_id == share_id,
                    ShareNotification.user_id == member_id,
                )
            )
        ).scalar_one()
        audit = (
            await session.execute(select(AuditLog).where(AuditLog.action == "share.expired"))
        ).scalar_one()
    assert share is not None and share.status == "expired"
    assert grant.is_active is False
    assert notification.invalidated_at is not None
    assert audit.actor_type == "system"


@pytest.mark.asyncio
async def test_preview_lifecycle_removes_stale_and_orphan_artifacts(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    storage_adapter: InMemoryStorageAdapter,
) -> None:
    await seed_admin(session_factory, settings)
    async with session_factory() as session:
        user = (await session.execute(select(User))).scalar_one()
        space = Space(
            tenant_id=user.tenant_id,
            owner_id=user.id,
            slug="preview-lifecycle",
            name="预览生命周期",
        )
        session.add(space)
        await session.flush()
        node = Node(
            tenant_id=user.tenant_id,
            space_id=space.id,
            parent_id=None,
            node_type="file",
            name="旧版本.png",
            normalized_name="旧版本.png",
            owner_id=user.id,
        )
        session.add(node)
        await session.flush()
        blob = FileBlob(
            tenant_id=user.tenant_id,
            hash_algo="sha256",
            content_hash="6" * 64,
            size_bytes=10,
            storage_key="objects/test/preview-lifecycle",
            mime_type="image/png",
            ref_count=1,
        )
        session.add(blob)
        await session.flush()
        version = FileVersion(
            tenant_id=user.tenant_id,
            node_id=node.id,
            blob_id=blob.id,
            version_no=1,
            size_bytes=10,
            mime_type="image/png",
            created_by=user.id,
        )
        session.add(version)
        await session.flush()
        node.current_version_id = None
        artifact = PreviewArtifact(
            tenant_id=user.tenant_id,
            node_id=node.id,
            version_id=version.id,
            artifact_type="image",
            mime_type="image/webp",
            storage_key=f"previews/{user.tenant_id}/{node.id}/{version.id}/image.webp",
            size_bytes=7,
            created_at=utc_now() - timedelta(days=40),
            last_accessed_at=utc_now() - timedelta(days=40),
        )
        session.add(artifact)
        await session.commit()
        tenant_id = user.tenant_id
        artifact_key = artifact.storage_key

    orphan_key = f"previews/{tenant_id}/orphan/image.webp"
    recent_orphan_key = f"previews/{tenant_id}/recent/image.webp"
    storage_adapter.object_contents[(settings.s3_bucket, artifact_key)] = b"artifact"
    storage_adapter.object_contents[(settings.s3_bucket, orphan_key)] = b"orphan"
    storage_adapter.object_contents[(settings.s3_bucket, recent_orphan_key)] = b"recent"
    storage_adapter.object_last_modified[(settings.s3_bucket, artifact_key)] = (
        utc_now() - timedelta(days=40)
    )
    storage_adapter.object_last_modified[(settings.s3_bucket, orphan_key)] = utc_now() - timedelta(
        days=40
    )
    storage_adapter.object_last_modified[(settings.s3_bucket, recent_orphan_key)] = utc_now()

    async with session_factory() as session:
        result = await PreviewArtifactLifecycleService(
            repository=PreviewRepository(session),
            storage=storage_adapter,
            bucket=settings.s3_bucket,
        ).cleanup(
            tenant_id=tenant_id,
            retention_days=30,
            limit=100,
        )

    assert result.stale_cleaned == 1
    assert result.orphan_cleaned == 1
    assert (settings.s3_bucket, artifact_key) not in storage_adapter.object_contents
    assert (settings.s3_bucket, orphan_key) not in storage_adapter.object_contents
    assert (settings.s3_bucket, recent_orphan_key) in storage_adapter.object_contents
    async with session_factory() as session:
        artifacts = (await session.execute(select(PreviewArtifact))).scalars().all()
    assert artifacts == []


def test_ocr_and_complex_format_extractors_use_bounded_adapters() -> None:
    ocr = FakeOcrEngine()
    image_text = ImageOcrTextExtractor(ocr_engine=ocr).extract(
        b"image",
        TextExtractionContext(mime_type="image/png", name="scan.png"),
    )
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    output = BytesIO()
    writer.write(output)
    scanned_pdf = output.getvalue()
    scanned_pdf_text = PdfTextExtractor(max_pages=3, ocr_engine=ocr).extract(
        scanned_pdf,
        TextExtractionContext(mime_type="application/pdf", name="scan.pdf"),
    )
    legacy_text = OfficeDocumentTextExtractor(
        converter=FakeOfficeConverter(),
        pdf_extractor=PdfTextExtractor(max_pages=2, ocr_engine=ocr),
    ).extract(
        b"legacy",
        TextExtractionContext(mime_type="application/msword", name="legacy.doc"),
    )

    assert image_text == "IMAGE:scan.png:5"
    assert scanned_pdf_text == f"PDF:scan.pdf:3:{len(scanned_pdf)}"
    assert legacy_text.startswith("PDF:legacy.doc.pdf:2:")
    assert ocr.image_calls == 1
    assert ocr.pdf_calls == 2


def test_tesseract_ocr_reports_missing_tool_and_pixel_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.infrastructure.search.content_extraction.shutil.which",
        lambda _: None,
    )
    with pytest.raises(TextExtractionError) as missing_tool:
        TesseractOcrEngine().extract_image(
            b"image",
            TextExtractionContext(mime_type="image/png", name="scan.png"),
        )
    assert missing_tool.value.status == "skipped"
    assert missing_tool.value.reason == "ocr_tool_unavailable"

    monkeypatch.setattr(
        "app.infrastructure.search.content_extraction.shutil.which",
        lambda command: command,
    )
    image_output = BytesIO()
    Image.new("RGB", (20, 20), "white").save(image_output, format="PNG")
    with pytest.raises(TextExtractionError) as pixel_limit:
        TesseractOcrEngine(max_pixels=100).extract_image(
            image_output.getvalue(),
            TextExtractionContext(mime_type="image/png", name="scan.png"),
        )
    assert pixel_limit.value.status == "skipped"
    assert pixel_limit.value.reason == "ocr_pixels_exceeded"
