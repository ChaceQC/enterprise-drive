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
from app.modules.file.trash_cleanup import TrashCleanupService
from app.modules.quota.repository import QuotaRepository
from app.modules.quota.service import QuotaService

_BLOB_COUNTER_KEYS = (
    "scanned",
    "claimed",
    "cleaned",
    "skipped",
    "storage_errors",
    "db_conflicts",
)

_ORPHAN_OBJECT_COUNTER_KEYS = (
    "scanned",
    "orphaned",
    "cleaned",
    "dry_run",
    "skipped",
    "storage_errors",
)

_TRASH_COUNTER_KEYS = (
    "scanned",
    "purged_roots",
    "purged_nodes",
    "released_bytes",
    "skipped",
    "failed",
)


def cleanup_expired_trash(
    tenant_id: str | None = None,
    limit: int = 100,
    retention_days: int | None = None,
    request_id: str | None = None,
) -> dict[str, int]:
    return asyncio.run(
        _cleanup_expired_trash(
            tenant_id=UUID(tenant_id) if tenant_id else None,
            limit=limit,
            retention_days=retention_days,
            request_id=request_id,
        )
    )


celery_app.task(name="file.cleanup_expired_trash")(cleanup_expired_trash)


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


def cleanup_orphaned_objects(
    tenant_id: str | None = None,
    limit: int = 100,
    after_storage_key: str | None = None,
    dry_run: bool = True,
    request_id: str | None = None,
    scan_all: bool = True,
) -> dict[str, object]:
    return asyncio.run(
        _cleanup_orphaned_objects(
            tenant_id=UUID(tenant_id) if tenant_id else None,
            limit=limit,
            after_storage_key=after_storage_key,
            dry_run=dry_run,
            request_id=request_id,
            scan_all=scan_all,
        )
    )


celery_app.task(name="file.cleanup_orphaned_objects")(cleanup_orphaned_objects)


async def _cleanup_expired_trash(
    *,
    tenant_id: UUID | None,
    limit: int,
    retention_days: int | None,
    request_id: str | None,
) -> dict[str, int]:
    settings = get_settings()
    session_factory = get_session_factory()
    async with session_factory() as session:
        tenant_ids = [tenant_id] if tenant_id else await AuthRepository(session).list_tenant_ids()
        total = {key: 0 for key in _TRASH_COUNTER_KEYS}
        for current_tenant_id in tenant_ids:
            service = TrashCleanupService(
                repository=FileRepository(session),
                quota_service=QuotaService(
                    repository=QuotaRepository(session),
                    default_space_limit_bytes=settings.default_space_quota_bytes,
                    default_user_limit_bytes=settings.default_user_quota_bytes,
                    default_tenant_limit_bytes=settings.default_tenant_quota_bytes,
                    policy_enabled=settings.quota_policy_enabled,
                ),
                audit_service=AuditService(repository=AuditRepository(session)),
            )
            result = await service.cleanup_expired_trash(
                tenant_id=current_tenant_id,
                retention_days=retention_days or settings.trash_retention_days,
                limit=limit,
                audit_context=AuditContext(request_id=request_id),
            )
            payload = result.to_dict()
            for key in _TRASH_COUNTER_KEYS:
                total[key] += payload[key]
        return total


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
        total = {key: 0 for key in _BLOB_COUNTER_KEYS}
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
            for key in _BLOB_COUNTER_KEYS:
                total[key] += payload[key]
        return total


async def _cleanup_orphaned_objects(
    *,
    tenant_id: UUID | None,
    limit: int,
    dry_run: bool,
    request_id: str | None,
    after_storage_key: str | None = None,
    scan_all: bool = True,
) -> dict[str, object]:
    settings = get_settings()
    session_factory = get_session_factory()
    async with session_factory() as session:
        tenant_ids = [tenant_id] if tenant_id else await AuthRepository(session).list_tenant_ids()
        total: dict[str, object] = {key: 0 for key in _ORPHAN_OBJECT_COUNTER_KEYS}
        total["next_storage_key"] = after_storage_key
        for current_tenant_id in tenant_ids:
            service = BlobCleanupService(
                repository=FileRepository(session),
                storage=S3StorageAdapter(settings=settings),
                bucket=settings.s3_bucket,
                audit_service=AuditService(repository=AuditRepository(session)),
            )
            current_after_storage_key = after_storage_key if tenant_id is not None else None
            while True:
                result = await service.cleanup_orphaned_objects(
                    tenant_id=current_tenant_id,
                    limit=limit,
                    after_storage_key=current_after_storage_key,
                    dry_run=dry_run,
                    audit_context=AuditContext(request_id=request_id),
                )
                payload = result.to_dict()
                for key in _ORPHAN_OBJECT_COUNTER_KEYS:
                    total[key] = _counter(total, key) + _counter(payload, key)
                total["next_storage_key"] = result.next_storage_key
                if not scan_all or result.next_storage_key is None:
                    break
                current_after_storage_key = result.next_storage_key
        return total


def _counter(payload: dict[str, object], key: str) -> int:
    value = payload[key]
    assert isinstance(value, int)
    return value
