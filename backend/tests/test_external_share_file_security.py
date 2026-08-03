from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.infrastructure.storage.testing import InMemoryStorageAdapter
from app.modules.audit.models import AuditLog
from app.modules.file.models import FileBlob, FileVersion
from app.modules.file_security.models import FileSecurityPolicy
from app.modules.share.models import Share, ShareAccessLog
from tests.helpers import (
    client as client,
)
from tests.helpers import (
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
from tests.test_share_router import create_instant_file


@pytest.mark.asyncio
async def test_external_share_dlp_denial_does_not_consume_download_count(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    storage_adapter: InMemoryStorageAdapter,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space = await create_space(client, csrf_token, slug="external-security")
    file_payload = await create_instant_file(
        client,
        session_factory,
        csrf_token,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        file_name="external.secret",
        content_hash="c" * 64,
    )
    async with session_factory() as session:
        version = (
            await session.execute(
                select(FileVersion).where(FileVersion.id == UUID(str(file_payload["version_id"])))
            )
        ).scalar_one()
        version.search_status = "indexed"
        version.search_text = "contains secret"
        session.add(
            FileSecurityPolicy(
                tenant_id=UUID(str(space["tenant_id"])),
                name="外链 DLP",
                priority=1,
                classification="restricted",
                download_mode="presigned",
                extensions=[".secret"],
                mime_prefixes=[],
                dlp_keywords=["secret"],
                dlp_action="block",
                fail_closed=True,
            )
        )
        await session.commit()

    create_response = await client.post(
        "/api/v1/shares",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "share_type": "external",
            "root_node_id": file_payload["node_id"],
            "max_downloads": 1,
        },
    )
    raw_token = create_response.json()["raw_token"]

    blocked = await client.post(
        "/api/v1/public/shares/download",
        json={
            "tenant_slug": "default",
            "raw_token": raw_token,
            "node_id": file_payload["node_id"],
        },
    )

    assert blocked.status_code == 403
    assert blocked.json()["code"] == "DLP_DOWNLOAD_BLOCKED"
    async with session_factory() as session:
        share = (await session.execute(select(Share))).scalar_one()
    assert share.download_count == 0


@pytest.mark.asyncio
async def test_external_share_watermark_requires_requested_mode_and_presigns_derivative(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    storage_adapter: InMemoryStorageAdapter,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space = await create_space(client, csrf_token, slug="external-watermark")
    file_payload = await create_instant_file(
        client,
        session_factory,
        csrf_token,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        file_name="external.png",
        content_hash="d" * 64,
    )
    png_content = _tiny_png()
    async with session_factory() as session:
        version, blob = (
            await session.execute(
                select(FileVersion, FileBlob)
                .join(FileBlob, FileBlob.id == FileVersion.blob_id)
                .where(FileVersion.id == UUID(str(file_payload["version_id"])))
            )
        ).one()
        version.mime_type = "image/png"
        version.size_bytes = len(png_content)
        version.search_status = "indexed"
        version.search_text = "approved"
        blob.mime_type = "image/png"
        blob.size_bytes = len(png_content)
        session.add(
            FileSecurityPolicy(
                tenant_id=UUID(str(space["tenant_id"])),
                name="外链水印",
                priority=1,
                classification="confidential",
                download_mode="watermark",
                extensions=[".png"],
                mime_prefixes=[],
                dlp_keywords=[],
                dlp_action="audit",
                fail_closed=False,
                watermark_text="EXTERNAL | {timestamp}",
            )
        )
        storage_key = blob.storage_key
        await session.commit()
    storage_adapter.object_contents[(settings.s3_bucket, storage_key)] = png_content

    create_response = await client.post(
        "/api/v1/shares",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "share_type": "external",
            "root_node_id": file_payload["node_id"],
            "max_downloads": 2,
        },
    )
    raw_token = create_response.json()["raw_token"]

    direct = await client.post(
        "/api/v1/public/shares/download",
        json={
            "tenant_slug": "default",
            "raw_token": raw_token,
            "node_id": file_payload["node_id"],
        },
    )
    watermarked = await client.post(
        "/api/v1/public/shares/download",
        json={
            "tenant_slug": "default",
            "raw_token": raw_token,
            "node_id": file_payload["node_id"],
            "delivery_mode": "watermark",
        },
    )

    assert direct.status_code == 409
    assert direct.json()["code"] == "DOWNLOAD_WATERMARK_REQUIRED"
    assert watermarked.status_code == 200
    payload = watermarked.json()
    assert payload["file_name"] == "external_watermarked.png"
    assert payload["mime_type"] == "image/png"
    assert "/exports/" in payload["download_url"]
    assert payload["download_count"] == 1
    derivative_key = next(
        key
        for bucket, key in storage_adapter.object_contents
        if bucket == settings.s3_bucket and "/share-watermarks/" in key
    )
    derivative_size = len(storage_adapter.object_contents[(settings.s3_bucket, derivative_key)])
    assert payload["size_bytes"] == derivative_size

    async with session_factory() as session:
        share = (await session.execute(select(Share))).scalar_one()
        access_log = (
            await session.execute(select(ShareAccessLog).where(ShareAccessLog.result == "allowed"))
        ).scalar_one()
        audit_log = (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.action == "share.external.downloaded",
                    AuditLog.result == "allowed",
                )
            )
        ).scalar_one()
    assert share.download_count == 1
    assert access_log.bytes_sent == derivative_size
    assert audit_log.metadata_json["size_bytes"] == derivative_size
    assert audit_log.metadata_json["source_size_bytes"] == len(png_content)


def _tiny_png() -> bytes:
    from io import BytesIO

    from PIL import Image

    output = BytesIO()
    Image.new("RGB", (64, 64), "white").save(output, format="PNG")
    return output.getvalue()
