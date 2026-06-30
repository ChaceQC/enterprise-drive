from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.core.security import ensure_utc, utc_now
from app.infrastructure.storage.base import StorageAdapter
from app.modules.audit.schemas import AuditContext
from app.modules.audit.service import AuditService
from app.modules.upload.audit import (
    expired_upload_metadata,
    record_system_upload_event,
)
from app.modules.upload.models import UploadSession
from app.modules.upload.repository import UploadRepository
from app.modules.upload.storage_keys import is_upload_temp_storage_key

EXPIRABLE_UPLOAD_STATUSES = {"initiated", "uploading", "completing"}


@dataclass
class ExpireUploadSessionsResult:
    scanned: int = 0
    expired: int = 0
    skipped: int = 0
    aborted: int = 0
    deleted: int = 0
    storage_errors: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "scanned": self.scanned,
            "expired": self.expired,
            "skipped": self.skipped,
            "aborted": self.aborted,
            "deleted": self.deleted,
            "storage_errors": self.storage_errors,
        }


class UploadCleanupService:
    def __init__(
        self,
        *,
        repository: UploadRepository,
        storage: StorageAdapter,
        audit_service: AuditService | None = None,
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.audit_service = audit_service

    async def expire_upload_sessions(
        self,
        *,
        tenant_id: UUID,
        cutoff: datetime | None = None,
        limit: int = 100,
        audit_context: AuditContext | None = None,
    ) -> ExpireUploadSessionsResult:
        if limit <= 0:
            return ExpireUploadSessionsResult()

        expires_before = cutoff or utc_now()
        session_ids = await self.repository.list_expired_active_upload_session_ids(
            tenant_id=tenant_id,
            cutoff=expires_before,
            limit=limit,
        )
        result = ExpireUploadSessionsResult(scanned=len(session_ids))
        for session_id in session_ids:
            await self._expire_one(
                tenant_id=tenant_id,
                session_id=session_id,
                cutoff=expires_before,
                result=result,
                audit_context=audit_context,
            )
        return result

    async def _expire_one(
        self,
        *,
        tenant_id: UUID,
        session_id: UUID,
        cutoff: datetime,
        result: ExpireUploadSessionsResult,
        audit_context: AuditContext | None,
    ) -> None:
        upload_session = await self.repository.get_upload_session_for_update_by_id(
            tenant_id=tenant_id,
            session_id=session_id,
        )
        if not self._is_still_expirable(upload_session=upload_session, cutoff=cutoff):
            await self.repository.rollback()
            result.skipped += 1
            return

        assert upload_session is not None
        storage_bucket = upload_session.storage_bucket
        storage_key = upload_session.storage_key
        provider_upload_id = upload_session.provider_upload_id
        upload_session.status = "expired"
        await self.repository.commit()
        result.expired += 1

        cleanup_errors = await self._cleanup_storage(
            bucket=storage_bucket,
            storage_key=storage_key,
            provider_upload_id=provider_upload_id,
            result=result,
        )
        cleanup_status = "failed" if cleanup_errors else "cleaned"

        upload_session = await self.repository.get_upload_session_for_update_by_id(
            tenant_id=tenant_id,
            session_id=session_id,
        )
        if upload_session is None:
            await self.repository.rollback()
            return
        await record_system_upload_event(
            audit_service=self.audit_service,
            upload_session=upload_session,
            action="upload.expired",
            audit_context=audit_context,
            metadata=expired_upload_metadata(
                upload_session=upload_session,
                cleanup_status=cleanup_status,
                cleanup_errors=cleanup_errors,
            ),
        )
        await self.repository.commit()

    def _is_still_expirable(
        self,
        *,
        upload_session: UploadSession | None,
        cutoff: datetime,
    ) -> bool:
        if upload_session is None:
            return False
        return upload_session.status in EXPIRABLE_UPLOAD_STATUSES and ensure_utc(
            upload_session.expires_at
        ) <= ensure_utc(cutoff)

    async def _cleanup_storage(
        self,
        *,
        bucket: str,
        storage_key: str,
        provider_upload_id: str | None,
        result: ExpireUploadSessionsResult,
    ) -> list[str]:
        errors: list[str] = []
        if provider_upload_id is not None:
            try:
                await self.storage.abort_multipart_upload(
                    bucket=bucket,
                    storage_key=storage_key,
                    provider_upload_id=provider_upload_id,
                )
                result.aborted += 1
            except Exception:
                errors.append("abort_multipart_upload_failed")
                result.storage_errors += 1

        if is_upload_temp_storage_key(storage_key):
            try:
                await self.storage.delete_object(bucket=bucket, storage_key=storage_key)
                result.deleted += 1
            except Exception:
                errors.append("delete_temp_object_failed")
                result.storage_errors += 1
        return errors
