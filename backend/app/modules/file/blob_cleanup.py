from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.infrastructure.storage.base import StorageAdapter
from app.modules.audit.schemas import AuditContext, AuditEvent
from app.modules.audit.service import AuditService
from app.modules.file.models import FileBlob
from app.modules.file.repository import FileRepository


@dataclass
class BlobCleanupResult:
    scanned: int = 0
    claimed: int = 0
    cleaned: int = 0
    skipped: int = 0
    storage_errors: int = 0
    db_conflicts: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "scanned": self.scanned,
            "claimed": self.claimed,
            "cleaned": self.cleaned,
            "skipped": self.skipped,
            "storage_errors": self.storage_errors,
            "db_conflicts": self.db_conflicts,
        }


class BlobCleanupService:
    def __init__(
        self,
        *,
        repository: FileRepository,
        storage: StorageAdapter,
        bucket: str,
        audit_service: AuditService | None = None,
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.bucket = bucket
        self.audit_service = audit_service

    async def cleanup_unreferenced_blobs(
        self,
        *,
        tenant_id: UUID,
        limit: int = 100,
        audit_context: AuditContext | None = None,
    ) -> BlobCleanupResult:
        if limit <= 0:
            return BlobCleanupResult()

        blob_ids = await self.repository.list_unreferenced_blob_ids(
            tenant_id=tenant_id,
            limit=limit,
        )
        result = BlobCleanupResult(scanned=len(blob_ids))
        for blob_id in blob_ids:
            await self._cleanup_one(
                tenant_id=tenant_id,
                blob_id=blob_id,
                result=result,
                audit_context=audit_context,
            )
        return result

    async def _cleanup_one(
        self,
        *,
        tenant_id: UUID,
        blob_id: UUID,
        result: BlobCleanupResult,
        audit_context: AuditContext | None,
    ) -> None:
        claimed = await self.repository.mark_blob_deleting(
            tenant_id=tenant_id,
            blob_id=blob_id,
        )
        if not claimed:
            await self.repository.rollback()
            result.skipped += 1
            return
        await self.repository.commit()
        result.claimed += 1

        blob = await self.repository.get_deleting_blob_for_update(
            tenant_id=tenant_id,
            blob_id=blob_id,
        )
        if blob is None:
            await self.repository.rollback()
            result.skipped += 1
            return
        await self.repository.commit()

        try:
            await self.storage.delete_object(
                bucket=self.bucket,
                storage_key=blob.storage_key,
            )
        except Exception:
            await self.repository.restore_blob_active(tenant_id=tenant_id, blob_id=blob_id)
            await self._record_blob_event(
                blob=blob,
                action="file.blob.cleanup_failed",
                result="error",
                audit_context=audit_context,
                metadata={"reason": "storage_delete_failed"},
            )
            await self.repository.commit()
            result.storage_errors += 1
            return

        deleted = await self.repository.delete_deleting_blob(
            tenant_id=tenant_id,
            blob_id=blob_id,
        )
        if not deleted:
            await self.repository.rollback()
            result.db_conflicts += 1
            return

        await self._record_blob_event(
            blob=blob,
            action="file.blob.cleaned",
            result="allowed",
            audit_context=audit_context,
            metadata={"cleanup_status": "cleaned"},
        )
        await self.repository.commit()
        result.cleaned += 1

    async def _record_blob_event(
        self,
        *,
        blob: FileBlob,
        action: str,
        result: str,
        audit_context: AuditContext | None,
        metadata: dict[str, object],
    ) -> None:
        if self.audit_service is None:
            return
        await self.audit_service.record(
            event=AuditEvent(
                tenant_id=blob.tenant_id,
                actor_id=None,
                actor_type="system",
                action=action,
                resource_type="file_blob",
                resource_id=blob.id,
                result=result,
                metadata={
                    "hash_algo": blob.hash_algo,
                    "size_bytes": blob.size_bytes,
                    "ref_count": blob.ref_count,
                    **metadata,
                },
            ),
            context=audit_context or AuditContext(),
        )
