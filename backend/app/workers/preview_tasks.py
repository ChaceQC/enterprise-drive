from __future__ import annotations

import asyncio
from uuid import UUID

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.infrastructure.preview.libreoffice import LibreOfficePreviewConverter
from app.infrastructure.preview.poppler import PopplerPdfPreviewConverter
from app.infrastructure.queue.celery_app import celery_app
from app.infrastructure.storage.s3 import S3StorageAdapter
from app.modules.audit.dispatcher import LoggingOutboxPublisher, OutboxDispatcher, OutboxPublisher
from app.modules.audit.models import OutboxEvent
from app.modules.audit.repository import AuditRepository
from app.modules.preview.events import PREVIEW_RENDER_REQUESTED
from app.modules.preview.renderer import PreviewRenderService
from app.modules.preview.repository import PreviewRepository


def dispatch_preview_outbox(batch_size: int | None = None) -> dict[str, int]:
    return asyncio.run(_dispatch_preview_outbox(batch_size=batch_size))


celery_app.task(name="preview.dispatch_outbox")(dispatch_preview_outbox)


async def _dispatch_preview_outbox(batch_size: int | None = None) -> dict[str, int]:
    settings = get_settings()
    session_factory = get_session_factory()
    async with session_factory() as session:
        preview_repository = PreviewRepository(session)
        publisher = PreviewOutboxPublisher(
            render_service=PreviewRenderService(
                repository=preview_repository,
                storage=S3StorageAdapter(settings=settings),
                settings=settings,
                pdf_converter=PopplerPdfPreviewConverter(
                    command=settings.preview_pdf_command,
                    dpi=settings.preview_pdf_dpi,
                    timeout_seconds=settings.preview_command_timeout_seconds,
                    max_rendered_bytes=settings.preview_pdf_max_rendered_bytes,
                ),
                office_converter=LibreOfficePreviewConverter(
                    command=settings.preview_office_command,
                    timeout_seconds=settings.preview_command_timeout_seconds,
                    max_pdf_bytes=settings.preview_office_max_pdf_bytes,
                ),
            ),
            fallback_publisher=LoggingOutboxPublisher(),
        )
        dispatcher = OutboxDispatcher(
            repository=AuditRepository(session),
            publisher=publisher,
            max_retries=settings.outbox_max_retries,
        )
        result = await dispatcher.dispatch_pending(
            batch_size=batch_size or settings.outbox_batch_size,
            event_types=[PREVIEW_RENDER_REQUESTED],
        )
        await session.commit()
        return result.to_dict()


class PreviewOutboxPublisher:
    def __init__(
        self,
        *,
        render_service: PreviewRenderService,
        fallback_publisher: OutboxPublisher,
    ) -> None:
        self.render_service = render_service
        self.fallback_publisher = fallback_publisher

    async def publish(self, event: OutboxEvent) -> None:
        if event.event_type == PREVIEW_RENDER_REQUESTED:
            await self._publish_render_requested(event)
            return
        if event.event_type.startswith("preview."):
            raise ValueError(f"unsupported preview event type: {event.event_type}")
        await self.fallback_publisher.publish(event)

    async def _publish_render_requested(self, event: OutboxEvent) -> None:
        version_id = event.payload.get("version_id")
        if not isinstance(version_id, str):
            raise ValueError("preview render event missing version_id")
        await self.render_service.render_version(
            tenant_id=event.tenant_id,
            version_id=UUID(version_id),
        )
