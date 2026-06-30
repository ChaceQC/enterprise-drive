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
from app.modules.upload.cleanup import UploadCleanupService
from app.modules.upload.repository import UploadRepository


def expire_upload_sessions(
    tenant_id: str | None = None,
    limit: int = 100,
    request_id: str | None = None,
) -> dict[str, int]:
    return asyncio.run(
        _expire_upload_sessions(
            tenant_id=UUID(tenant_id) if tenant_id else None,
            limit=limit,
            request_id=request_id,
        )
    )


celery_app.task(name="upload.expire_sessions")(expire_upload_sessions)


async def _expire_upload_sessions(
    *,
    tenant_id: UUID | None,
    limit: int,
    request_id: str | None,
) -> dict[str, int]:
    settings = get_settings()
    session_factory = get_session_factory()
    async with session_factory() as session:
        tenant_ids = [tenant_id] if tenant_id else await AuthRepository(session).list_tenant_ids()
        total = {
            "scanned": 0,
            "expired": 0,
            "skipped": 0,
            "aborted": 0,
            "deleted": 0,
            "storage_errors": 0,
        }
        for current_tenant_id in tenant_ids:
            service = UploadCleanupService(
                repository=UploadRepository(session),
                storage=S3StorageAdapter(settings=settings),
                audit_service=AuditService(repository=AuditRepository(session)),
            )
            result = await service.expire_upload_sessions(
                tenant_id=current_tenant_id,
                limit=limit,
                audit_context=AuditContext(request_id=request_id),
            )
            for key, value in result.to_dict().items():
                total[key] += value
        return total
