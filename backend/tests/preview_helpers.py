from __future__ import annotations

from io import BytesIO
from uuid import UUID

from httpx import AsyncClient
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.infrastructure.storage.testing import InMemoryStorageAdapter
from app.modules.audit.dispatcher import LoggingOutboxPublisher, OutboxDispatcher
from app.modules.audit.repository import AuditRepository
from app.modules.file.models import FileBlob
from app.modules.preview.converters import OfficePreviewConverter, PdfPreviewConverter
from app.modules.preview.events import PREVIEW_RENDER_REQUESTED
from app.modules.preview.renderer import PreviewRenderService
from app.modules.preview.repository import PreviewRepository
from app.workers.preview_tasks import PreviewOutboxPublisher


async def dispatch_preview_events(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    storage_adapter: InMemoryStorageAdapter,
    pdf_converter: PdfPreviewConverter | None = None,
    office_converter: OfficePreviewConverter | None = None,
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
                    pdf_converter=pdf_converter,
                    office_converter=office_converter,
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


async def create_instant_uploaded_file(
    *,
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    storage_adapter: InMemoryStorageAdapter,
    token: str,
    space: dict[str, object],
    tenant_id: UUID,
    content: bytes,
    storage_key: str,
    content_hash: str,
    file_name: str,
    mime_type: str,
) -> tuple[str, UUID]:
    storage_adapter.object_contents[(settings.s3_bucket, storage_key)] = content

    async with session_factory() as session:
        session.add(
            FileBlob(
                tenant_id=tenant_id,
                hash_algo="sha256",
                content_hash=content_hash,
                size_bytes=len(content),
                storage_key=storage_key,
                mime_type=mime_type,
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
            "file_name": file_name,
            "size_bytes": len(content),
            "content_hash": content_hash,
            "hash_algo": "sha256",
            "mime_type": mime_type,
        },
    )
    assert response.status_code == 201
    return str(response.json()["node_id"]), UUID(response.json()["version_id"])


class FakePdfPreviewConverter:
    def __init__(self) -> None:
        self.sources: list[bytes] = []

    async def render_first_page_png(self, source: bytes) -> bytes:
        self.sources.append(source)
        return png_bytes()


class FakeOfficePreviewConverter:
    def __init__(self, pdf: bytes = b"%PDF-1.7\n% converted\n") -> None:
        self.pdf = pdf
        self.calls: list[tuple[bytes, str]] = []

    async def convert_to_pdf(self, source: bytes, *, file_extension: str) -> bytes:
        self.calls.append((source, file_extension))
        return self.pdf


def png_bytes() -> bytes:
    image = Image.new("RGB", (32, 24), color=(80, 120, 200))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
