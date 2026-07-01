from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from app.core.metrics import record_orphan_object_cleanup
from app.infrastructure.storage.base import StorageAdapter, StorageObject
from app.modules.audit.schemas import AuditContext, AuditEvent
from app.modules.audit.service import AuditService
from app.modules.file.models import FileBlob
from app.modules.file.repository import FileRepository

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


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


@dataclass
class OrphanObjectCleanupResult:
    scanned: int = 0
    orphaned: int = 0
    cleaned: int = 0
    dry_run: int = 0
    skipped: int = 0
    storage_errors: int = 0
    next_storage_key: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "scanned": self.scanned,
            "orphaned": self.orphaned,
            "cleaned": self.cleaned,
            "dry_run": self.dry_run,
            "skipped": self.skipped,
            "storage_errors": self.storage_errors,
            "next_storage_key": self.next_storage_key,
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

    async def cleanup_orphaned_objects(
        self,
        *,
        tenant_id: UUID,
        limit: int = 100,
        after_storage_key: str | None = None,
        dry_run: bool = True,
        audit_context: AuditContext | None = None,
    ) -> OrphanObjectCleanupResult:
        if limit <= 0:
            return OrphanObjectCleanupResult()

        prefix = f"objects/{tenant_id}/"
        objects = await self.storage.list_objects(
            bucket=self.bucket,
            prefix=prefix,
            limit=limit + 1,
            start_after=after_storage_key,
        )
        has_more = len(objects) > limit
        objects = objects[:limit]
        candidate_objects = [
            storage_object
            for storage_object in objects
            if _is_managed_object_key(tenant_id=tenant_id, storage_key=storage_object.storage_key)
        ]
        result = OrphanObjectCleanupResult(
            scanned=len(objects),
            skipped=len(objects) - len(candidate_objects),
            next_storage_key=objects[-1].storage_key if has_more and objects else None,
        )
        existing_keys = await self.repository.list_existing_blob_storage_keys(
            tenant_id=tenant_id,
            storage_keys=[storage_object.storage_key for storage_object in candidate_objects],
        )

        for storage_object in candidate_objects:
            if storage_object.storage_key in existing_keys:
                continue
            result.orphaned += 1
            if dry_run:
                result.dry_run += 1
                continue
            await self._cleanup_orphaned_object(
                tenant_id=tenant_id,
                storage_object=storage_object,
                result=result,
                audit_context=audit_context,
            )
        if dry_run and result.orphaned:
            await self._record_orphan_cleanup_summary(
                tenant_id=tenant_id,
                action="file.object.orphan_cleanup_planned",
                result="allowed",
                audit_context=audit_context,
                metadata={
                    "scanned": result.scanned,
                    "orphaned": result.orphaned,
                    "dry_run": result.dry_run,
                    "skipped": result.skipped,
                    "next_storage_key_hash": (
                        _storage_key_hash(result.next_storage_key)
                        if result.next_storage_key is not None
                        else None
                    ),
                },
            )
            await self.repository.commit()
        record_orphan_object_cleanup(status="scanned", count=result.scanned)
        record_orphan_object_cleanup(status="skipped", count=result.skipped)
        record_orphan_object_cleanup(status="planned", count=result.dry_run)
        record_orphan_object_cleanup(status="cleaned", count=result.cleaned)
        record_orphan_object_cleanup(status="failed", count=result.storage_errors)
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

    async def _cleanup_orphaned_object(
        self,
        *,
        tenant_id: UUID,
        storage_object: StorageObject,
        result: OrphanObjectCleanupResult,
        audit_context: AuditContext | None,
    ) -> None:
        try:
            await self.storage.delete_object(
                bucket=self.bucket,
                storage_key=storage_object.storage_key,
            )
        except Exception:
            await self._record_orphan_cleanup_summary(
                tenant_id=tenant_id,
                action="file.object.orphan_cleanup_failed",
                result="error",
                audit_context=audit_context,
                metadata={
                    "reason": "storage_delete_failed",
                    "storage_key_hash": _storage_key_hash(storage_object.storage_key),
                    "size_bytes": storage_object.size_bytes,
                },
            )
            await self.repository.commit()
            result.storage_errors += 1
            return

        await self._record_orphan_cleanup_summary(
            tenant_id=tenant_id,
            action="file.object.orphan_cleaned",
            result="allowed",
            audit_context=audit_context,
            metadata={
                "cleanup_status": "cleaned",
                "storage_key_hash": _storage_key_hash(storage_object.storage_key),
                "size_bytes": storage_object.size_bytes,
            },
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

    async def _record_orphan_cleanup_summary(
        self,
        *,
        tenant_id: UUID,
        action: str,
        result: str,
        audit_context: AuditContext | None,
        metadata: dict[str, object],
    ) -> None:
        if self.audit_service is None:
            return
        await self.audit_service.record(
            event=AuditEvent(
                tenant_id=tenant_id,
                actor_id=None,
                actor_type="system",
                action=action,
                resource_type="storage_object",
                result=result,
                metadata=metadata,
            ),
            context=audit_context or AuditContext(),
        )


def _is_managed_object_key(*, tenant_id: UUID, storage_key: str) -> bool:
    parts = storage_key.split("/")
    if len(parts) != 4:
        return False
    root, key_tenant_id, hash_prefix, content_hash = parts
    return (
        root == "objects"
        and key_tenant_id == str(tenant_id)
        and len(hash_prefix) == 2
        and _SHA256_RE.fullmatch(content_hash) is not None
        and content_hash.startswith(hash_prefix)
    )


def _storage_key_hash(storage_key: str) -> str:
    import hashlib

    return hashlib.sha256(storage_key.encode()).hexdigest()
