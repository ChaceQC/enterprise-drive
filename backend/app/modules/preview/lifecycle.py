from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from app.core.security import ensure_utc, utc_now
from app.core.worker_metrics import record_preview_artifact_cleanup
from app.infrastructure.storage.base import StorageAdapter, StorageObject
from app.modules.audit.schemas import AuditContext, AuditEvent
from app.modules.audit.service import AuditService
from app.modules.preview.models import PreviewArtifact
from app.modules.preview.repository import PreviewRepository


@dataclass
class PreviewArtifactCleanupResult:
    stale_scanned: int = 0
    stale_cleaned: int = 0
    orphan_scanned: int = 0
    orphan_cleaned: int = 0
    dry_run: int = 0
    storage_errors: int = 0
    next_storage_key: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "stale_scanned": self.stale_scanned,
            "stale_cleaned": self.stale_cleaned,
            "orphan_scanned": self.orphan_scanned,
            "orphan_cleaned": self.orphan_cleaned,
            "dry_run": self.dry_run,
            "storage_errors": self.storage_errors,
            "next_storage_key": self.next_storage_key,
        }


class PreviewArtifactLifecycleService:
    def __init__(
        self,
        *,
        repository: PreviewRepository,
        storage: StorageAdapter,
        bucket: str,
        audit_service: AuditService | None = None,
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.bucket = bucket
        self.audit_service = audit_service

    async def cleanup(
        self,
        *,
        tenant_id: UUID,
        retention_days: int,
        limit: int,
        after_storage_key: str | None = None,
        dry_run: bool = False,
        include_stale: bool = True,
        audit_context: AuditContext | None = None,
    ) -> PreviewArtifactCleanupResult:
        result = PreviewArtifactCleanupResult()
        candidates = (
            await self.repository.list_lifecycle_candidates(
                tenant_id=tenant_id,
                accessed_before=utc_now() - timedelta(days=retention_days),
                limit=limit,
            )
            if include_stale
            else []
        )
        result.stale_scanned = len(candidates)
        for artifact in candidates:
            if dry_run:
                result.dry_run += 1
                continue
            await self._delete_stale_artifact(
                artifact=artifact,
                result=result,
                audit_context=audit_context,
            )
        if dry_run and candidates:
            await self._record(
                tenant_id=tenant_id,
                action="preview.artifact.cleanup_planned",
                result="allowed",
                audit_context=audit_context,
                metadata={"stale_count": len(candidates)},
            )
            await self.repository.commit()

        objects = await self.storage.list_objects(
            bucket=self.bucket,
            prefix=f"previews/{tenant_id}/",
            limit=limit + 1,
            start_after=after_storage_key,
        )
        has_more = len(objects) > limit
        page = objects[:limit]
        result.orphan_scanned = len(page)
        result.next_storage_key = page[-1].storage_key if has_more and page else None
        existing_keys = await self.repository.list_existing_storage_keys(
            tenant_id=tenant_id,
            storage_keys=[item.storage_key for item in page],
        )
        orphan_cutoff = utc_now() - timedelta(days=retention_days)
        for storage_object in page:
            if storage_object.storage_key in existing_keys:
                continue
            if (
                storage_object.last_modified is None
                or ensure_utc(storage_object.last_modified) > orphan_cutoff
            ):
                continue
            if dry_run:
                result.dry_run += 1
                continue
            await self._delete_orphan_object(
                tenant_id=tenant_id,
                storage_object=storage_object,
                result=result,
                audit_context=audit_context,
            )

        record_preview_artifact_cleanup(status="stale_scanned", count=result.stale_scanned)
        record_preview_artifact_cleanup(status="stale_cleaned", count=result.stale_cleaned)
        record_preview_artifact_cleanup(status="orphan_scanned", count=result.orphan_scanned)
        record_preview_artifact_cleanup(status="orphan_cleaned", count=result.orphan_cleaned)
        record_preview_artifact_cleanup(status="planned", count=result.dry_run)
        record_preview_artifact_cleanup(status="failed", count=result.storage_errors)
        return result

    async def _delete_stale_artifact(
        self,
        *,
        artifact: PreviewArtifact,
        result: PreviewArtifactCleanupResult,
        audit_context: AuditContext | None,
    ) -> None:
        try:
            await self.storage.delete_object(
                bucket=self.bucket,
                storage_key=artifact.storage_key,
            )
        except Exception:
            result.storage_errors += 1
            await self._record(
                tenant_id=artifact.tenant_id,
                action="preview.artifact.cleanup_failed",
                result="error",
                audit_context=audit_context,
                metadata={
                    "artifact_id": str(artifact.id),
                    "reason": "storage_delete_failed",
                    "storage_key_hash": _storage_key_hash(artifact.storage_key),
                },
            )
            await self.repository.commit()
            return
        await self.repository.delete_artifact(artifact)
        await self._record(
            tenant_id=artifact.tenant_id,
            action="preview.artifact.cleaned",
            result="allowed",
            audit_context=audit_context,
            metadata={
                "artifact_id": str(artifact.id),
                "size_bytes": artifact.size_bytes,
                "storage_key_hash": _storage_key_hash(artifact.storage_key),
            },
        )
        await self.repository.commit()
        result.stale_cleaned += 1

    async def _delete_orphan_object(
        self,
        *,
        tenant_id: UUID,
        storage_object: StorageObject,
        result: PreviewArtifactCleanupResult,
        audit_context: AuditContext | None,
    ) -> None:
        try:
            await self.storage.delete_object(
                bucket=self.bucket,
                storage_key=storage_object.storage_key,
            )
        except Exception:
            result.storage_errors += 1
            await self._record(
                tenant_id=tenant_id,
                action="preview.object.cleanup_failed",
                result="error",
                audit_context=audit_context,
                metadata={
                    "reason": "storage_delete_failed",
                    "storage_key_hash": _storage_key_hash(storage_object.storage_key),
                },
            )
            await self.repository.commit()
            return
        await self._record(
            tenant_id=tenant_id,
            action="preview.object.cleaned",
            result="allowed",
            audit_context=audit_context,
            metadata={
                "size_bytes": storage_object.size_bytes,
                "storage_key_hash": _storage_key_hash(storage_object.storage_key),
            },
        )
        await self.repository.commit()
        result.orphan_cleaned += 1

    async def _record(
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
                resource_type="preview_artifact",
                result=result,
                metadata=metadata,
            ),
            context=audit_context or AuditContext(),
        )


def _storage_key_hash(storage_key: str) -> str:
    return hashlib.sha256(storage_key.encode("utf-8")).hexdigest()
