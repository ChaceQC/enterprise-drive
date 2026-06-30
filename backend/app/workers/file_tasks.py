from __future__ import annotations

import asyncio
from uuid import UUID

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.infrastructure.queue.celery_app import celery_app
from app.infrastructure.storage.s3 import S3StorageAdapter
from app.modules.audit.repository import AuditRepository
from app.modules.audit.schemas import AuditContext
from app.modules.audit.service import AuditService
from app.modules.auth.repository import AuthRepository
from app.modules.file.blob_cleanup import BlobCleanupService
from app.modules.file.repository import FileRepository

_COUNTER_KEYS = (
    "scanned",
    "claimed",
    "cleaned",
    "skipped",
    "storage_errors",
    "db_conflicts",
)


def cleanup_unreferenced_blobs(
    tenant_id: str | None = None,
    limit: int = 100,
    request_id: str | None = None,
) -> dict[str, int]:
    return asyncio.run(
        _cleanup_unreferenced_blobs(
            tenant_id=UUID(tenant_id) if tenant_id else None,
            limit=limit,
            request_id=request_id,
        )
    )


celery_app.task(name="file.cleanup_unreferenced_blobs")(cleanup_unreferenced_blobs)


async def _cleanup_unreferenced_blobs(
    *,
    tenant_id: UUID | None,
    limit: int,
    request_id: str | None,
) -> dict[str, int]:
    settings = get_settings()
    session_factory = get_session_factory()
    async with session_factory() as session:
        tenant_ids = [tenant_id] if tenant_id else await AuthRepository(session).list_tenant_ids()
        total = {key: 0 for key in _COUNTER_KEYS}
        for current_tenant_id in tenant_ids:
            service = BlobCleanupService(
                repository=FileRepository(session),
                storage=S3StorageAdapter(settings=settings),
                bucket=settings.s3_bucket,
                audit_service=AuditService(repository=AuditRepository(session)),
            )
            result = await service.cleanup_unreferenced_blobs(
                tenant_id=current_tenant_id,
                limit=limit,
                audit_context=AuditContext(request_id=request_id),
            )
            payload = result.to_dict()
            for key in _COUNTER_KEYS:
                total[key] += payload[key]
        return total
