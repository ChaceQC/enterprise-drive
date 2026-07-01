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
    FakeOfficePreviewConverter,
    FakePdfPreviewConverter,
    create_instant_uploaded_file,
    dispatch_preview_events,
)

DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.mark.asyncio
async def test_preview_render_requested_creates_office_page_artifact(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    storage_adapter: InMemoryStorageAdapter,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="preview-office-space")
    tenant_id = UUID(str(space["tenant_id"]))
    office_bytes = b"fake office content"
    pdf_bytes = b"%PDF-1.7\n% converted office\n"
    office_converter = FakeOfficePreviewConverter(pdf=pdf_bytes)
    pdf_converter = FakePdfPreviewConverter()
    node_id, version_id = await create_instant_uploaded_file(
        client=client,
        session_factory=session_factory,
        settings=settings,
        storage_adapter=storage_adapter,
        token=token,
        space=space,
        tenant_id=tenant_id,
        content=office_bytes,
        storage_key="objects/test/preview-office",
        content_hash="b" * 64,
        file_name="方案.docx",
        mime_type=DOCX_MIME_TYPE,
    )

    await dispatch_preview_events(
        session_factory=session_factory,
        settings=settings,
        storage_adapter=storage_adapter,
        pdf_converter=pdf_converter,
        office_converter=office_converter,
    )

    async with session_factory() as session:
        version = await session.get(FileVersion, version_id)
        artifact = (
            await session.execute(
                select(PreviewArtifact).where(PreviewArtifact.version_id == version_id)
            )
        ).scalar_one()

    assert office_converter.calls == [(office_bytes, ".docx")]
    assert pdf_converter.sources == [pdf_bytes]
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
async def test_preview_render_requested_marks_office_unsupported_when_renderer_missing(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    storage_adapter: InMemoryStorageAdapter,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="preview-office-missing-space")
    tenant_id = UUID(str(space["tenant_id"]))
    _, version_id = await create_instant_uploaded_file(
        client=client,
        session_factory=session_factory,
        settings=settings,
        storage_adapter=storage_adapter,
        token=token,
        space=space,
        tenant_id=tenant_id,
        content=b"fake office content",
        storage_key="objects/test/preview-office-missing",
        content_hash="c" * 64,
        file_name="缺少转换器.docx",
        mime_type=DOCX_MIME_TYPE,
    )

    await dispatch_preview_events(
        session_factory=session_factory,
        settings=settings,
        storage_adapter=storage_adapter,
        pdf_converter=FakePdfPreviewConverter(),
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
    assert version.preview_error == "office_renderer_missing"
    assert artifacts == []
