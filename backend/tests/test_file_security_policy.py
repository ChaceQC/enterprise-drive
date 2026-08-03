from __future__ import annotations

from io import BytesIO
from uuid import UUID

import pytest
from httpx import AsyncClient
from pypdf import PdfReader, PdfWriter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.infrastructure.storage.testing import InMemoryStorageAdapter
from app.modules.audit.models import AuditLog
from app.modules.file.models import FileBlob, FileVersion, Node
from app.modules.file_security.models import FileSecurityPolicy
from tests.helpers import (
    client as client,
)
from tests.helpers import (
    create_second_user,
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
from tests.helpers import (
    storage_adapter as storage_adapter,
)


@pytest.mark.asyncio
async def test_admin_manages_file_security_policy_and_normal_user_is_denied(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)

    create_response = await client.post(
        "/api/v1/admin/file-security/policies",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "name": "密级 PDF",
            "priority": 10,
            "classification": "confidential",
            "download_mode": "watermark",
            "extensions": ["PDF", ".pdf"],
            "dlp_keywords": ["secret", "秘密"],
            "dlp_action": "block",
            "fail_closed": True,
            "watermark_text": "CONFIDENTIAL | {user} | {timestamp}",
        },
    )
    assert create_response.status_code == 201
    policy_id = UUID(create_response.json()["id"])
    assert create_response.json()["extensions"] == [".pdf"]
    assert create_response.json()["version"] == 1

    stale_update = await client.patch(
        f"/api/v1/admin/file-security/policies/{policy_id}",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "expected_version": 9,
            "priority": 20,
        },
    )
    assert stale_update.status_code == 409
    assert stale_update.json()["code"] == "FILE_SECURITY_POLICY_CHANGED"

    update_response = await client.patch(
        f"/api/v1/admin/file-security/policies/{policy_id}",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "expected_version": 1,
            "priority": 20,
            "mime_prefixes": ["application/pdf"],
        },
    )
    assert update_response.status_code == 200
    assert update_response.json()["version"] == 2

    list_response = await client.get(
        "/api/v1/admin/file-security/policies",
        params={"classification": "confidential", "is_active": True},
    )
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()["items"]] == [str(policy_id)]

    await create_second_user(session_factory)
    await login(client, username="member", password="member-password")
    denied_response = await client.get("/api/v1/admin/file-security/policies")
    assert denied_response.status_code == 403
    assert denied_response.json()["code"] == "ADMIN_REQUIRED"


@pytest.mark.asyncio
async def test_download_policy_forces_proxy_and_blocks_dlp_keyword(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    storage_adapter: InMemoryStorageAdapter,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space = await create_space(client, csrf_token, slug="security-proxy")
    fixture = await _seed_file(
        session_factory,
        storage_adapter,
        tenant_id=UUID(str(space["tenant_id"])),
        space_id=UUID(str(space["id"])),
        parent_id=UUID(str(space["root_node_id"])),
        file_name="policy.secret",
        mime_type="text/plain",
        content=b"safe content",
        search_text="safe content",
    )
    await _seed_policy(
        session_factory,
        tenant_id=fixture["tenant_id"],
        name="代理文件",
        extension=".secret",
        download_mode="proxy",
        dlp_keywords=[],
    )

    presigned = await client.get(f"/api/v1/files/{fixture['node_id']}/download")
    assert presigned.status_code == 409
    assert presigned.json()["code"] == "DOWNLOAD_PROXY_REQUIRED"

    proxy = await client.get(
        f"/api/v1/files/{fixture['node_id']}/content",
        headers={"Range": "bytes=0-3"},
    )
    assert proxy.status_code == 206
    assert proxy.content == b"safe"

    async with session_factory() as session:
        policy = (
            await session.execute(
                select(FileSecurityPolicy).where(
                    FileSecurityPolicy.tenant_id == fixture["tenant_id"]
                )
            )
        ).scalar_one()
        policy.download_mode = "proxy"
        policy.dlp_keywords = ["secret"]
        policy.dlp_action = "block"
        version = (
            await session.execute(
                select(FileVersion).where(FileVersion.id == fixture["version_id"])
            )
        ).scalar_one()
        version.search_text = "contains secret content"
        await session.commit()

    blocked = await client.get(f"/api/v1/files/{fixture['node_id']}/content")
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "DLP_DOWNLOAD_BLOCKED"

    async with session_factory() as session:
        denied_audits = (
            (
                await session.execute(
                    select(AuditLog)
                    .where(AuditLog.action == "file.downloaded", AuditLog.result == "denied")
                    .order_by(AuditLog.created_at)
                )
            )
            .scalars()
            .all()
        )
    assert denied_audits[-1].metadata_json["dlp_status"] == "blocked"
    assert denied_audits[-1].metadata_json["dlp_match_count"] == 1


@pytest.mark.asyncio
async def test_historical_version_download_applies_dlp_policy(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    storage_adapter: InMemoryStorageAdapter,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space = await create_space(client, csrf_token, slug="security-version")
    fixture = await _seed_file(
        session_factory,
        storage_adapter,
        tenant_id=UUID(str(space["tenant_id"])),
        space_id=UUID(str(space["id"])),
        parent_id=UUID(str(space["root_node_id"])),
        file_name="historical.secret",
        mime_type="text/plain",
        content=b"contains secret",
        search_text="contains secret",
    )
    await _seed_policy(
        session_factory,
        tenant_id=fixture["tenant_id"],
        name="历史版本 DLP",
        extension=".secret",
        download_mode="presigned",
        dlp_keywords=["secret"],
    )

    blocked = await client.get(
        f"/api/v1/files/{fixture['node_id']}/versions/{fixture['version_id']}/download"
    )

    assert blocked.status_code == 403
    assert blocked.json()["code"] == "DLP_DOWNLOAD_BLOCKED"
    async with session_factory() as session:
        denied_audit = (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.action == "file.version.downloaded",
                    AuditLog.result == "denied",
                )
            )
        ).scalar_one()
    assert denied_audit.metadata_json["version_id"] == str(fixture["version_id"])
    assert denied_audit.metadata_json["dlp_status"] == "blocked"


@pytest.mark.asyncio
async def test_watermark_policy_returns_valid_pdf_with_dynamic_mark(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    storage_adapter: InMemoryStorageAdapter,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space = await create_space(client, csrf_token, slug="security-watermark")
    pdf_content = _blank_pdf()
    fixture = await _seed_file(
        session_factory,
        storage_adapter,
        tenant_id=UUID(str(space["tenant_id"])),
        space_id=UUID(str(space["id"])),
        parent_id=UUID(str(space["root_node_id"])),
        file_name="confidential.pdf",
        mime_type="application/pdf",
        content=pdf_content,
        search_text="approved",
    )
    await _seed_policy(
        session_factory,
        tenant_id=fixture["tenant_id"],
        name="PDF 水印",
        extension=".pdf",
        download_mode="watermark",
        dlp_keywords=["secret"],
        watermark_text="CONFIDENTIAL | {user}",
    )

    presigned = await client.get(f"/api/v1/files/{fixture['node_id']}/download")
    proxy = await client.get(f"/api/v1/files/{fixture['node_id']}/content")
    watermarked = await client.get(f"/api/v1/files/{fixture['node_id']}/watermarked-content")

    assert presigned.status_code == 409
    assert presigned.json()["code"] == "DOWNLOAD_WATERMARK_REQUIRED"
    assert proxy.status_code == 409
    assert proxy.json()["code"] == "DOWNLOAD_WATERMARK_REQUIRED"
    assert watermarked.status_code == 200
    assert watermarked.headers["content-type"].startswith("application/pdf")
    assert "confidential_watermarked.pdf" in watermarked.headers["content-disposition"]
    reader = PdfReader(BytesIO(watermarked.content))
    assert len(reader.pages) == 1
    page_stream = reader.pages[0].get_contents().get_data()
    assert b"CONFIDENTIAL" in page_stream
    assert b"admin" in page_stream


async def _seed_file(
    session_factory: async_sessionmaker[AsyncSession],
    storage_adapter: InMemoryStorageAdapter,
    *,
    tenant_id: UUID,
    space_id: UUID,
    parent_id: UUID,
    file_name: str,
    mime_type: str,
    content: bytes,
    search_text: str,
) -> dict[str, UUID]:
    async with session_factory() as session:
        owner = (
            await session.execute(select(Node.owner_id).where(Node.id == parent_id))
        ).scalar_one()
        blob = FileBlob(
            tenant_id=tenant_id,
            hash_algo="sha256",
            content_hash="f" * 64,
            size_bytes=len(content),
            storage_key=f"objects/{tenant_id}/ff/{'f' * 64}",
            mime_type=mime_type,
            ref_count=1,
        )
        node = Node(
            tenant_id=tenant_id,
            space_id=space_id,
            parent_id=parent_id,
            owner_id=owner,
            node_type="file",
            name=file_name,
            normalized_name=file_name.casefold(),
        )
        session.add_all([blob, node])
        await session.flush()
        version = FileVersion(
            tenant_id=tenant_id,
            node_id=node.id,
            blob_id=blob.id,
            version_no=1,
            size_bytes=len(content),
            mime_type=mime_type,
            search_status="indexed",
            search_text=search_text,
            created_by=owner,
        )
        session.add(version)
        await session.flush()
        node.current_version_id = version.id
        await session.commit()
    storage_adapter.object_contents[("enterprise-drive-local", blob.storage_key)] = content
    return {
        "tenant_id": tenant_id,
        "node_id": node.id,
        "version_id": version.id,
    }


async def _seed_policy(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    name: str,
    extension: str,
    download_mode: str,
    dlp_keywords: list[str],
    watermark_text: str | None = None,
) -> None:
    async with session_factory() as session:
        session.add(
            FileSecurityPolicy(
                tenant_id=tenant_id,
                name=name,
                priority=1,
                classification="confidential",
                download_mode=download_mode,
                extensions=[extension],
                mime_prefixes=[],
                dlp_keywords=dlp_keywords,
                dlp_action="block",
                fail_closed=True,
                watermark_text=watermark_text,
            )
        )
        await session.commit()


def _blank_pdf() -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=400)
    writer.write(output)
    return output.getvalue()
