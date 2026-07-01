from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.infrastructure.storage.testing import InMemoryStorageAdapter
from app.modules.file.models import FileVersion
from app.modules.preview.models import PreviewArtifact
from tests.helpers import client as client
from tests.helpers import create_space, login, seed_admin
from tests.helpers import session_factory as session_factory
from tests.helpers import settings as settings
from tests.helpers import storage_adapter as storage_adapter
from tests.preview_helpers import (
    FakePdfPreviewConverter,
    create_instant_uploaded_file,
    dispatch_preview_events,
)


@pytest.mark.asyncio
async def test_preview_render_requested_creates_pdf_page_artifact(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    storage_adapter: InMemoryStorageAdapter,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="preview-pdf-space")
    tenant_id = UUID(str(space["tenant_id"]))
    pdf_bytes = b"%PDF-1.7\n% test preview\n"
    converter = FakePdfPreviewConverter()
    node_id, version_id = await create_instant_uploaded_file(
        client=client,
        session_factory=session_factory,
        settings=settings,
        storage_adapter=storage_adapter,
        token=token,
        space=space,
        tenant_id=tenant_id,
        content=pdf_bytes,
        storage_key="objects/test/preview-pdf",
        content_hash="f" * 64,
        file_name="预览文档.pdf",
        mime_type="application/pdf",
    )

    await dispatch_preview_events(
        session_factory=session_factory,
        settings=settings,
        storage_adapter=storage_adapter,
        pdf_converter=converter,
    )

    async with session_factory() as session:
        version = await session.get(FileVersion, version_id)
        artifact = (
            await session.execute(
                select(PreviewArtifact).where(PreviewArtifact.version_id == version_id)
            )
        ).scalar_one()

    assert converter.sources == [pdf_bytes]
    assert version is not None
    assert version.preview_status == "ready"
    assert version.preview_error is None
    assert artifact.artifact_type == "image"
    assert artifact.mime_type == "image/webp"
    assert artifact.storage_key == f"previews/{tenant_id}/{node_id}/{version_id}/image.webp"
    assert storage_adapter.object_contents[(settings.s3_bucket, artifact.storage_key)].startswith(
        b"RIFF"
    )


@pytest.mark.asyncio
async def test_preview_render_requested_marks_pdf_unsupported_when_renderer_missing(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    storage_adapter: InMemoryStorageAdapter,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="preview-pdf-missing-space")
    tenant_id = UUID(str(space["tenant_id"]))
    _, version_id = await create_instant_uploaded_file(
        client=client,
        session_factory=session_factory,
        settings=settings,
        storage_adapter=storage_adapter,
        token=token,
        space=space,
        tenant_id=tenant_id,
        content=b"%PDF-1.7\n% renderer missing\n",
        storage_key="objects/test/preview-pdf-missing",
        content_hash="a" * 64,
        file_name="缺少渲染器.pdf",
        mime_type="application/pdf",
    )

    await dispatch_preview_events(
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
    assert version.preview_error == "pdf_renderer_missing"
    assert artifacts == []
