from __future__ import annotations

from io import BytesIO
from uuid import UUID

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.infrastructure.storage.testing import InMemoryStorageAdapter
from app.modules.audit.dispatcher import LoggingOutboxPublisher, OutboxDispatcher
from app.modules.audit.models import OutboxEvent
from app.modules.audit.repository import AuditRepository
from app.modules.file.models import FileBlob, FileVersion
from app.modules.preview.events import PREVIEW_RENDER_REQUESTED
from app.modules.preview.models import PreviewArtifact
from app.modules.preview.renderer import PreviewRenderService
from app.modules.preview.repository import PreviewRepository
from app.workers.preview_tasks import PreviewOutboxPublisher
from tests.helpers import client as client
from tests.helpers import create_space, login, seed_admin
from tests.helpers import session_factory as session_factory
from tests.helpers import settings as settings
from tests.helpers import storage_adapter as storage_adapter


@pytest.mark.asyncio
async def test_preview_render_requested_creates_image_artifact_and_url(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    storage_adapter: InMemoryStorageAdapter,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="preview-image-space")
    tenant_id = UUID(str(space["tenant_id"]))
    image_bytes = _png_bytes()
    storage_key = "objects/test/preview-image"
    storage_adapter.object_contents[(settings.s3_bucket, storage_key)] = image_bytes

    async with session_factory() as session:
        session.add(
            FileBlob(
                tenant_id=tenant_id,
                hash_algo="sha256",
                content_hash="d" * 64,
                size_bytes=len(image_bytes),
                storage_key=storage_key,
                mime_type="image/png",
                ref_count=0,
            )
        )
        await session.commit()

    response = await client.post(
        "/api/v1/uploads/init",
        headers={"X-CSRF-Token": token},
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "file_name": "预览图片.png",
            "size_bytes": len(image_bytes),
            "content_hash": "d" * 64,
            "hash_algo": "sha256",
            "mime_type": "image/png",
        },
    )
    assert response.status_code == 201
    node_id = response.json()["node_id"]
    version_id = UUID(response.json()["version_id"])

    async with session_factory() as session:
        event = (
            await session.execute(
                select(OutboxEvent).where(OutboxEvent.event_type == PREVIEW_RENDER_REQUESTED)
            )
        ).scalar_one()
    assert event.aggregate_type == "file_version"
    assert event.aggregate_id == version_id
    assert event.payload["node_id"] == node_id
    assert event.payload["reason"] == "upload_instant"

    await _dispatch_preview_events(
        session_factory=session_factory,
        settings=settings,
        storage_adapter=storage_adapter,
    )

    async with session_factory() as session:
        version = await session.get(FileVersion, version_id)
        artifact = (
            await session.execute(
                select(PreviewArtifact).where(PreviewArtifact.version_id == version_id)
            )
        ).scalar_one()

    assert version is not None
    assert version.preview_status == "ready"
    assert version.preview_error is None
    assert artifact.mime_type == "image/webp"
    assert artifact.storage_key.startswith(f"previews/{tenant_id}/{node_id}/{version_id}/")
    assert storage_adapter.object_contents[(settings.s3_bucket, artifact.storage_key)].startswith(
        b"RIFF"
    )

    preview_response = await client.get(f"/api/v1/files/{node_id}/preview")
    assert preview_response.status_code == 200
    payload = preview_response.json()
    assert payload["status"] == "ready"
    assert payload["artifact"]["artifact_id"] == str(artifact.id)
    assert payload["artifact"]["mime_type"] == "image/webp"
    assert payload["artifact"]["preview_url"].startswith("https://storage.test/")
    assert storage_adapter.presigned_downloads[-1][1] == artifact.storage_key


@pytest.mark.asyncio
async def test_preview_render_requested_marks_text_as_unsupported(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    storage_adapter: InMemoryStorageAdapter,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="preview-unsupported-space")
    tenant_id = UUID(str(space["tenant_id"]))
    storage_key = "objects/test/preview-text"
    storage_adapter.object_contents[(settings.s3_bucket, storage_key)] = b"plain text"

    async with session_factory() as session:
        session.add(
            FileBlob(
                tenant_id=tenant_id,
                hash_algo="sha256",
                content_hash="e" * 64,
                size_bytes=10,
                storage_key=storage_key,
                mime_type="text/plain",
                ref_count=0,
            )
        )
        await session.commit()

    response = await client.post(
        "/api/v1/uploads/init",
        headers={"X-CSRF-Token": token},
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "file_name": "不可预览.txt",
            "size_bytes": 10,
            "content_hash": "e" * 64,
            "hash_algo": "sha256",
            "mime_type": "text/plain",
        },
    )
    assert response.status_code == 201
    node_id = response.json()["node_id"]
    version_id = UUID(response.json()["version_id"])

    await _dispatch_preview_events(
        session_factory=session_factory,
        settings=settings,
        storage_adapter=storage_adapter,
    )

    async with session_factory() as session:
        version = await session.get(FileVersion, version_id)
        artifacts = (
            (
                await session.execute(
                    select(PreviewArtifact).where(PreviewArtifact.version_id == version_id)
                )
            )
            .scalars()
            .all()
        )

    assert version is not None
    assert version.preview_status == "unsupported"
    assert version.preview_error == "unsupported_mime_type"
    assert artifacts == []

    preview_response = await client.get(f"/api/v1/files/{node_id}/preview")
    assert preview_response.status_code == 200
    assert preview_response.json()["status"] == "unsupported"
    assert preview_response.json()["artifact"] is None


async def _dispatch_preview_events(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    storage_adapter: InMemoryStorageAdapter,
) -> None:
    async with session_factory() as session:
        repository = PreviewRepository(session)
        dispatcher = OutboxDispatcher(
            repository=AuditRepository(session),
            publisher=PreviewOutboxPublisher(
                render_service=PreviewRenderService(
                    repository=repository,
                    storage=storage_adapter,
                    settings=settings,
                ),
                fallback_publisher=LoggingOutboxPublisher(),
            ),
            max_retries=settings.outbox_max_retries,
        )
        result = await dispatcher.dispatch_pending(
            batch_size=10,
            event_types=[PREVIEW_RENDER_REQUESTED],
        )
        await session.commit()
    assert result.failed == 0
    assert result.dead == 0


def _png_bytes() -> bytes:
    image = Image.new("RGB", (32, 24), color=(80, 120, 200))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
