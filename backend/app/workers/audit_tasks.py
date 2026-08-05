from __future__ import annotations

import asyncio

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.infrastructure.queue.celery_app import celery_app
from app.infrastructure.storage.s3 import S3StorageAdapter
from app.modules.audit.archive import archive_retained_audit_logs
from app.modules.audit.dispatcher import (
    LoggingOutboxPublisher,
    OutboxDispatcher,
    OutboxPublisher,
)
from app.modules.audit.external import HttpAuditPublisher, MisconfiguredAuditPublisher
from app.modules.audit.partitioning import ensure_audit_partitions
from app.modules.audit.repository import AuditRepository


def dispatch_outbox(batch_size: int | None = None) -> dict[str, int]:
    return asyncio.run(_dispatch_outbox(batch_size=batch_size))


def ensure_partitions(months_ahead: int | None = None) -> dict[str, object]:
    return asyncio.run(_ensure_partitions(months_ahead=months_ahead))


def archive_retention(
    tenant_id: str | None = None,
    delete_source: bool | None = None,
    retention_days: int | None = None,
) -> dict[str, object]:
    return asyncio.run(
        _archive_retention(
            tenant_id=tenant_id,
            delete_source=delete_source,
            retention_days=retention_days,
        )
    )


celery_app.task(name="audit.dispatch_outbox")(dispatch_outbox)
celery_app.task(name="audit.ensure_partitions")(ensure_partitions)
celery_app.task(name="audit.archive_retention")(archive_retention)


async def _dispatch_outbox(batch_size: int | None = None) -> dict[str, int]:
    settings = get_settings()
    session_factory = get_session_factory()
    async with session_factory() as session:
        repository = AuditRepository(session)
        publisher: OutboxPublisher
        if not settings.audit_external_delivery_url:
            publisher = LoggingOutboxPublisher()
        elif not settings.audit_external_hmac_key:
            publisher = MisconfiguredAuditPublisher()
        else:
            publisher = HttpAuditPublisher(
                repository=repository,
                endpoint_url=settings.audit_external_delivery_url,
                hmac_key=settings.audit_external_hmac_key,
                key_id=settings.audit_external_key_id,
                timeout_seconds=settings.audit_external_timeout_seconds,
            )
        dispatcher = OutboxDispatcher(
            repository=repository,
            publisher=publisher,
            max_retries=settings.outbox_max_retries,
            retry_max_delay_seconds=settings.outbox_retry_max_delay_seconds,
            retry_jitter_ratio=settings.outbox_retry_jitter_ratio,
            processing_timeout_seconds=settings.outbox_processing_timeout_seconds,
        )
        result = await dispatcher.dispatch_pending(
            batch_size=batch_size or settings.outbox_batch_size,
            event_type_prefixes=["audit."],
        )
        await session.commit()
        return result.to_dict()


async def _ensure_partitions(months_ahead: int | None = None) -> dict[str, object]:
    settings = get_settings()
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await ensure_audit_partitions(
            session=session,
            months_ahead=months_ahead or settings.audit_partition_months_ahead,
        )
        await session.commit()
        return result


async def _archive_retention(
    *,
    tenant_id: str | None,
    delete_source: bool | None,
    retention_days: int | None,
) -> dict[str, object]:
    from uuid import UUID

    settings = get_settings()
    session_factory = get_session_factory()
    async with session_factory() as session:
        return await archive_retained_audit_logs(
            session=session,
            storage=S3StorageAdapter(settings=settings),
            bucket=settings.s3_bucket,
            retention_days=retention_days or settings.audit_retention_days,
            max_rows=settings.audit_archive_max_rows,
            delete_source=(
                settings.audit_archive_delete_source if delete_source is None else delete_source
            ),
            signing_key=settings.audit_signing_key or settings.secret_key,
            signing_key_id=settings.audit_signing_key_id,
            tenant_id=UUID(tenant_id) if tenant_id else None,
        )
