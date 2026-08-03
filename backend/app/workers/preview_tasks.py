from __future__ import annotations

import asyncio
import logging
from typing import Protocol
from uuid import UUID

from app.core.config import get_settings
from app.core.worker_metrics import record_preview_failure
from app.db.session import get_session_factory
from app.infrastructure.preview.libreoffice import LibreOfficePreviewConverter
from app.infrastructure.preview.poppler import PopplerPdfPreviewConverter
from app.infrastructure.queue.celery_app import celery_app
from app.infrastructure.storage.s3 import S3StorageAdapter
from app.modules.audit.dispatcher import LoggingOutboxPublisher, OutboxDispatcher, OutboxPublisher
from app.modules.audit.models import OutboxEvent
from app.modules.audit.repository import AuditRepository
from app.modules.audit.schemas import AuditContext
from app.modules.audit.service import AuditService
from app.modules.auth.repository import AuthRepository
from app.modules.preview.events import PREVIEW_RENDER_REQUESTED
from app.modules.preview.lifecycle import PreviewArtifactLifecycleService
from app.modules.preview.renderer import PreviewRenderResult, PreviewRenderService
from app.modules.preview.repository import PreviewRepository

logger = logging.getLogger("enterprise_drive.preview")


class PreviewRenderHandler(Protocol):
    async def render_version(
        self,
        *,
        tenant_id: UUID,
        version_id: UUID,
    ) -> PreviewRenderResult: ...


def dispatch_preview_outbox(batch_size: int | None = None) -> dict[str, int]:
    return asyncio.run(_dispatch_preview_outbox(batch_size=batch_size))


celery_app.task(name="preview.dispatch_outbox")(dispatch_preview_outbox)


def cleanup_preview_artifacts(
    tenant_id: str | None = None,
    limit: int = 100,
    retention_days: int | None = None,
    dry_run: bool = False,
    request_id: str | None = None,
    scan_all: bool = True,
) -> dict[str, object]:
    return asyncio.run(
        _cleanup_preview_artifacts(
            tenant_id=UUID(tenant_id) if tenant_id else None,
            limit=limit,
            retention_days=retention_days,
            dry_run=dry_run,
            request_id=request_id,
            scan_all=scan_all,
        )
    )


celery_app.task(name="preview.cleanup_artifacts")(cleanup_preview_artifacts)


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


async def _cleanup_preview_artifacts(
    *,
    tenant_id: UUID | None,
    limit: int,
    retention_days: int | None,
    dry_run: bool,
    request_id: str | None,
    scan_all: bool,
) -> dict[str, object]:
    settings = get_settings()
    session_factory = get_session_factory()
    total: dict[str, object] = {
        "stale_scanned": 0,
        "stale_cleaned": 0,
        "orphan_scanned": 0,
        "orphan_cleaned": 0,
        "dry_run": 0,
        "storage_errors": 0,
        "next_storage_key": None,
    }
    async with session_factory() as session:
        tenant_ids = [tenant_id] if tenant_id else await AuthRepository(session).list_tenant_ids()
        for current_tenant_id in tenant_ids:
            repository = PreviewRepository(session)
            service = PreviewArtifactLifecycleService(
                repository=repository,
                storage=S3StorageAdapter(settings=settings),
                bucket=settings.s3_bucket,
                audit_service=AuditService(repository=AuditRepository(session)),
            )
            after_storage_key: str | None = None
            include_stale = True
            while True:
                result = await service.cleanup(
                    tenant_id=current_tenant_id,
                    retention_days=(
                        retention_days
                        if retention_days is not None
                        else settings.preview_artifact_retention_days
                    ),
                    limit=limit,
                    after_storage_key=after_storage_key,
                    dry_run=dry_run,
                    include_stale=include_stale,
                    audit_context=AuditContext(request_id=request_id),
                )
                payload = result.to_dict()
                for key in (
                    "stale_scanned",
                    "stale_cleaned",
                    "orphan_scanned",
                    "orphan_cleaned",
                    "dry_run",
                    "storage_errors",
                ):
                    value = payload[key]
                    assert isinstance(value, int)
                    current_value = total[key]
                    assert isinstance(current_value, int)
                    total[key] = current_value + value
                total["next_storage_key"] = result.next_storage_key
                if not scan_all or result.next_storage_key is None:
                    break
                after_storage_key = result.next_storage_key
                include_stale = False
    return total


class PreviewOutboxPublisher:
    def __init__(
        self,
        *,
        render_service: PreviewRenderHandler,
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
        version_uuid = UUID(version_id)
        try:
            result = await self.render_service.render_version(
                tenant_id=event.tenant_id,
                version_id=version_uuid,
            )
        except Exception:
            record_preview_failure(status="failed", reason="exception")
            logger.exception(
                "preview render failed and will be retried by outbox",
                extra={
                    "event_id": str(event.id),
                    "tenant_id": str(event.tenant_id),
                    "version_id": str(version_uuid),
                    "event_type": event.event_type,
                    "retry_count": event.retry_count,
                },
            )
            raise
        if result.status != "ready":
            record_preview_failure(
                status=result.status,
                reason=result.reason or "unknown",
            )
            logger.warning(
                "preview render finished without artifact",
                extra={
                    "event_id": str(event.id),
                    "tenant_id": str(event.tenant_id),
                    "version_id": str(version_uuid),
                    "event_type": event.event_type,
                    "preview_status": result.status,
                    "preview_reason": result.reason,
                },
            )
