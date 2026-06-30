from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.modules.audit.models import AuditLog, OutboxEvent
from app.modules.file.models import FileBlob, FileVersion, Node
from app.modules.quota.models import QuotaAccount, QuotaLedger
from app.modules.upload.models import UploadPart, UploadSession
from tests.helpers import (
    client as client,
)
from tests.helpers import (
    create_folder,
    create_space,
    login,
    seed_admin,
)
from tests.helpers import (
    session_factory as session_factory,
)
from tests.helpers import (
    settings as settings,
)


@pytest.mark.asyncio
async def test_init_multipart_upload_status_and_presign(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="upload-space")

    init_response = await client.post(
        "/api/v1/uploads/init",
        headers={"Authorization": f"Bearer {token}", "X-Request-ID": "req_upload_init"},
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "file_name": "  需求说明.pdf  ",
            "size_bytes": settings.upload_part_size_bytes + 1,
            "content_hash": "a" * 64,
            "hash_algo": "sha256",
            "mime_type": "application/pdf",
        },
    )

    assert init_response.status_code == 201
    init_payload = init_response.json()
    assert init_payload["mode"] == "multipart"
    assert init_payload["part_size_bytes"] == settings.upload_part_size_bytes
    assert init_payload["total_parts"] == 2

    status_response = await client.get(
        f"/api/v1/uploads/{init_payload['session_id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    presign_response = await client.post(
        f"/api/v1/uploads/{init_payload['session_id']}/parts/1/presign",
        headers={"Authorization": f"Bearer {token}"},
    )
    status_after_presign = await client.get(
        f"/api/v1/uploads/{init_payload['session_id']}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert status_response.status_code == 200
    assert status_response.json()["status"] == "initiated"
    assert status_response.json()["uploaded_parts"] == []
    assert presign_response.status_code == 200
    assert presign_response.json()["part_no"] == 1
    assert "upload_id=" in presign_response.json()["upload_url"]
    assert status_after_presign.status_code == 200
    assert status_after_presign.json()["status"] == "uploading"

    async with session_factory() as session:
        upload_session = (await session.execute(select(UploadSession))).scalar_one()
        audit = (
            await session.execute(select(AuditLog).where(AuditLog.action == "upload.initialized"))
        ).scalar_one()
        outbox_event = (
            await session.execute(
                select(OutboxEvent).where(OutboxEvent.event_type == "audit.upload.initialized")
            )
        ).scalar_one()

    assert upload_session.file_name == "需求说明.pdf"
    assert upload_session.status == "uploading"
    assert audit.request_id == "req_upload_init"
    assert outbox_event.aggregate_type == "audit_log"


@pytest.mark.asyncio
async def test_init_upload_uses_instant_upload_when_blob_exists(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="instant-upload-space")
    tenant_id = UUID(str(space["tenant_id"]))
    blob_id: UUID

    async with session_factory() as session:
        blob = FileBlob(
            tenant_id=tenant_id,
            hash_algo="sha256",
            content_hash="b" * 64,
            size_bytes=1024,
            storage_key="objects/test/bb",
            mime_type="text/plain",
            ref_count=0,
        )
        session.add(blob)
        await session.commit()
        blob_id = blob.id

    response = await client.post(
        "/api/v1/uploads/init",
        headers={"Authorization": f"Bearer {token}", "X-Request-ID": "req_upload_instant"},
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "file_name": "秒传.txt",
            "size_bytes": 1024,
            "content_hash": "b" * 64,
            "hash_algo": "sha256",
            "mime_type": "text/plain",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["mode"] == "instant"
    assert payload["blob_id"] == str(blob_id)

    async with session_factory() as session:
        blob = (await session.execute(select(FileBlob).where(FileBlob.id == blob_id))).scalar_one()
        node = (
            await session.execute(select(Node).where(Node.id == UUID(payload["node_id"])))
        ).scalar_one()
        version = (
            await session.execute(
                select(FileVersion).where(FileVersion.id == UUID(payload["version_id"]))
            )
        ).scalar_one()
        quota_account = (await session.execute(select(QuotaAccount))).scalar_one()
        quota_ledger = (await session.execute(select(QuotaLedger))).scalar_one()
        audit = (
            await session.execute(select(AuditLog).where(AuditLog.action == "upload.instant"))
        ).scalar_one()
        outbox_event = (
            await session.execute(
                select(OutboxEvent).where(OutboxEvent.event_type == "audit.upload.instant")
            )
        ).scalar_one()

    assert blob.ref_count == 1
    assert node.name == "秒传.txt"
    assert node.current_version_id == version.id
    assert version.blob_id == blob_id
    assert quota_account.owner_type == "space"
    assert quota_account.owner_id == UUID(str(space["id"]))
    assert quota_account.used_bytes == 1024
    assert quota_ledger.account_id == quota_account.id
    assert quota_ledger.delta_bytes == 1024
    assert quota_ledger.reason == "file_version_created"
    assert quota_ledger.ref_type == "file_version"
    assert quota_ledger.ref_id == version.id
    assert audit.request_id == "req_upload_instant"
    assert outbox_event.aggregate_type == "audit_log"


@pytest.mark.asyncio
async def test_init_upload_rejects_name_conflict_and_invalid_part(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="upload-conflict-space")
    await create_folder(
        client,
        token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        name="同名",
    )

    conflict_response = await client.post(
        "/api/v1/uploads/init",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "file_name": "同名",
            "size_bytes": 1024,
            "content_hash": "c" * 64,
            "hash_algo": "sha256",
        },
    )
    init_response = await client.post(
        "/api/v1/uploads/init",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "file_name": "分片.bin",
            "size_bytes": 1024,
            "content_hash": "d" * 64,
            "hash_algo": "sha256",
        },
    )
    invalid_part_response = await client.post(
        f"/api/v1/uploads/{init_response.json()['session_id']}/parts/2/presign",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert conflict_response.status_code == 409
    assert conflict_response.json()["code"] == "NODE_NAME_EXISTS"
    assert init_response.status_code == 201
    assert invalid_part_response.status_code == 422
    assert invalid_part_response.json()["code"] == "UPLOAD_PART_INVALID"


@pytest.mark.asyncio
async def test_complete_multipart_upload_creates_file_version_and_is_idempotent(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="complete-upload-space")
    size_bytes = settings.upload_part_size_bytes + 128
    init_response = await client.post(
        "/api/v1/uploads/init",
        headers={"Authorization": f"Bearer {token}", "X-Request-ID": "req_upload_start"},
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "file_name": "完整上传.bin",
            "size_bytes": size_bytes,
            "content_hash": "e" * 64,
            "hash_algo": "sha256",
            "mime_type": "application/octet-stream",
        },
    )
    session_id = init_response.json()["session_id"]
    complete_payload = {
        "parts": [
            {
                "part_no": 1,
                "etag": "etag-1",
                "size_bytes": settings.upload_part_size_bytes,
            },
            {"part_no": 2, "etag": "etag-2", "size_bytes": 128},
        ]
    }

    complete_response = await client.post(
        f"/api/v1/uploads/{session_id}/complete",
        headers={"Authorization": f"Bearer {token}", "X-Request-ID": "req_upload_complete"},
        json=complete_payload,
    )
    duplicate_response = await client.post(
        f"/api/v1/uploads/{session_id}/complete",
        headers={"Authorization": f"Bearer {token}"},
        json=complete_payload,
    )
    status_response = await client.get(
        f"/api/v1/uploads/{session_id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert complete_response.status_code == 200
    assert duplicate_response.status_code == 200
    assert duplicate_response.json() == complete_response.json()
    assert status_response.json()["status"] == "completed"
    assert status_response.json()["uploaded_parts"] == [1, 2]

    payload = complete_response.json()
    async with session_factory() as session:
        upload_session = (
            await session.execute(select(UploadSession).where(UploadSession.id == UUID(session_id)))
        ).scalar_one()
        blob = (
            await session.execute(select(FileBlob).where(FileBlob.id == UUID(payload["blob_id"])))
        ).scalar_one()
        node = (
            await session.execute(select(Node).where(Node.id == UUID(payload["node_id"])))
        ).scalar_one()
        version = (
            await session.execute(
                select(FileVersion).where(FileVersion.id == UUID(payload["version_id"]))
            )
        ).scalar_one()
        quota_account = (await session.execute(select(QuotaAccount))).scalar_one()
        quota_ledger = (await session.execute(select(QuotaLedger))).scalar_one()
        upload_parts = (
            (await session.execute(select(UploadPart).order_by(UploadPart.part_no))).scalars().all()
        )
        audit = (
            await session.execute(select(AuditLog).where(AuditLog.action == "upload.completed"))
        ).scalar_one()
        outbox_event = (
            await session.execute(
                select(OutboxEvent).where(OutboxEvent.event_type == "audit.upload.completed")
            )
        ).scalar_one()

    assert upload_session.completed_node_id == node.id
    assert upload_session.completed_version_id == version.id
    assert upload_session.completed_blob_id == blob.id
    assert blob.ref_count == 1
    assert blob.storage_key.startswith(f"uploads/{space['tenant_id']}/")
    assert node.name == "完整上传.bin"
    assert node.current_version_id == version.id
    assert version.blob_id == blob.id
    assert quota_account.owner_type == "space"
    assert quota_account.owner_id == UUID(str(space["id"]))
    assert quota_account.used_bytes == size_bytes
    assert quota_ledger.account_id == quota_account.id
    assert quota_ledger.delta_bytes == size_bytes
    assert quota_ledger.reason == "file_version_created"
    assert quota_ledger.ref_type == "file_version"
    assert quota_ledger.ref_id == version.id
    assert [(part.part_no, part.etag) for part in upload_parts] == [(1, "etag-1"), (2, "etag-2")]
    assert audit.request_id == "req_upload_complete"
    assert outbox_event.aggregate_type == "audit_log"


@pytest.mark.asyncio
async def test_init_upload_rejects_when_space_quota_exceeded(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    settings.default_space_quota_bytes = 512
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="quota-small-space")

    response = await client.post(
        "/api/v1/uploads/init",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "file_name": "超额.bin",
            "size_bytes": 1024,
            "content_hash": "9" * 64,
            "hash_algo": "sha256",
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "QUOTA_EXCEEDED"

    async with session_factory() as session:
        quota_account = (await session.execute(select(QuotaAccount))).scalar_one()
        ledgers = (await session.execute(select(QuotaLedger))).scalars().all()
        sessions = (await session.execute(select(UploadSession))).scalars().all()

    assert quota_account.limit_bytes == 512
    assert quota_account.used_bytes == 0
    assert ledgers == []
    assert sessions == []


@pytest.mark.asyncio
async def test_complete_upload_rejects_missing_part(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="missing-part-space")
    init_response = await client.post(
        "/api/v1/uploads/init",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "file_name": "缺片.bin",
            "size_bytes": settings.upload_part_size_bytes + 1,
            "content_hash": "f" * 64,
            "hash_algo": "sha256",
        },
    )

    response = await client.post(
        f"/api/v1/uploads/{init_response.json()['session_id']}/complete",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "parts": [
                {"part_no": 1, "etag": "etag-1", "size_bytes": settings.upload_part_size_bytes}
            ]
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "UPLOAD_PART_MISSING"


@pytest.mark.asyncio
async def test_abort_upload_marks_session_terminal(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="abort-upload-space")
    init_response = await client.post(
        "/api/v1/uploads/init",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "file_name": "取消上传.bin",
            "size_bytes": 1024,
            "content_hash": "1" * 64,
            "hash_algo": "sha256",
        },
    )
    session_id = init_response.json()["session_id"]

    abort_response = await client.post(
        f"/api/v1/uploads/{session_id}/abort",
        headers={"Authorization": f"Bearer {token}", "X-Request-ID": "req_upload_abort"},
    )
    duplicate_abort_response = await client.post(
        f"/api/v1/uploads/{session_id}/abort",
        headers={"Authorization": f"Bearer {token}"},
    )
    presign_response = await client.post(
        f"/api/v1/uploads/{session_id}/parts/1/presign",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert abort_response.status_code == 200
    assert abort_response.json() == {"session_id": session_id, "status": "aborted"}
    assert duplicate_abort_response.status_code == 200
    assert presign_response.status_code == 409
    assert presign_response.json()["code"] == "UPLOAD_NOT_ACTIVE"

    async with session_factory() as session:
        upload_session = (
            await session.execute(select(UploadSession).where(UploadSession.id == UUID(session_id)))
        ).scalar_one()
        audit = (
            await session.execute(select(AuditLog).where(AuditLog.action == "upload.aborted"))
        ).scalar_one()
        outbox_event = (
            await session.execute(
                select(OutboxEvent).where(OutboxEvent.event_type == "audit.upload.aborted")
            )
        ).scalar_one()

    assert upload_session.status == "aborted"
    assert audit.request_id == "req_upload_abort"
    assert outbox_event.aggregate_type == "audit_log"
