from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from app.api.errors import ApiError
from app.core.security import utc_now
from app.core.worker_metrics import record_trash_cleanup, record_trash_cleanup_released_bytes
from app.modules.audit.schemas import AuditContext, AuditEvent
from app.modules.audit.service import AuditService
from app.modules.file.models import FileVersion, Node
from app.modules.file.repository import FileRepository
from app.modules.quota.service import QuotaService
from app.modules.search.events import emit_search_index_requested


@dataclass
class TrashCleanupResult:
    scanned: int = 0
    purged_roots: int = 0
    purged_nodes: int = 0
    released_bytes: int = 0
    skipped: int = 0
    failed: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "scanned": self.scanned,
            "purged_roots": self.purged_roots,
            "purged_nodes": self.purged_nodes,
            "released_bytes": self.released_bytes,
            "skipped": self.skipped,
            "failed": self.failed,
        }


class TrashCleanupService:
    def __init__(
        self,
        *,
        repository: FileRepository,
        quota_service: QuotaService,
        audit_service: AuditService | None = None,
    ) -> None:
        self.repository = repository
        self.quota_service = quota_service
        self.audit_service = audit_service

    async def cleanup_expired_trash(
        self,
        *,
        tenant_id: UUID,
        retention_days: int,
        limit: int = 100,
        now: datetime | None = None,
        audit_context: AuditContext | None = None,
    ) -> TrashCleanupResult:
        if limit <= 0 or retention_days <= 0:
            return TrashCleanupResult()

        cutoff = (now or utc_now()) - timedelta(days=retention_days)
        root_ids = await self.repository.list_expired_trash_root_ids(
            tenant_id=tenant_id,
            cutoff=cutoff,
            limit=limit,
        )
        result = TrashCleanupResult(scanned=len(root_ids))
        for root_id in root_ids:
            try:
                purged = await self._purge_root(
                    tenant_id=tenant_id,
                    root_id=root_id,
                    cutoff=cutoff,
                    retention_days=retention_days,
                    audit_context=audit_context,
                )
            except ApiError as error:
                await self.repository.rollback()
                result.failed += 1
                await self._record_failure(
                    tenant_id=tenant_id,
                    root_id=root_id,
                    error=error,
                    retention_days=retention_days,
                    cutoff=cutoff,
                    audit_context=audit_context,
                )
                await self.repository.commit()
                continue

            if purged is None:
                result.skipped += 1
                continue
            purged_nodes, released_bytes = purged
            result.purged_roots += 1
            result.purged_nodes += purged_nodes
            result.released_bytes += released_bytes

        record_trash_cleanup(status="scanned_roots", count=result.scanned)
        record_trash_cleanup(status="purged_roots", count=result.purged_roots)
        record_trash_cleanup(status="purged_nodes", count=result.purged_nodes)
        record_trash_cleanup(status="skipped_roots", count=result.skipped)
        record_trash_cleanup(status="failed_roots", count=result.failed)
        record_trash_cleanup_released_bytes(size_bytes=result.released_bytes)
        return result

    async def _purge_root(
        self,
        *,
        tenant_id: UUID,
        root_id: UUID,
        cutoff: datetime,
        retention_days: int,
        audit_context: AuditContext | None,
    ) -> tuple[int, int] | None:
        root = await self.repository.get_expired_trash_root_for_update(
            tenant_id=tenant_id,
            node_id=root_id,
            cutoff=cutoff,
        )
        if root is None:
            await self.repository.rollback()
            return None

        subtree_nodes = await self._collect_deleted_subtree_for_update(root=root)
        node_ids = [node.id for node in subtree_nodes]
        versions = await self.repository.list_versions_for_nodes(
            tenant_id=tenant_id,
            node_ids=node_ids,
        )
        released_bytes = sum(version.size_bytes for version in versions)
        blob_counts = self._blob_ref_counts(versions=versions)

        await self.quota_service.release_file_usage(
            tenant_id=tenant_id,
            space_id=root.space_id,
            ref_id=root.id,
            size_bytes=released_bytes,
        )
        blob_refs_updated = await self.repository.decrement_blob_ref_counts(
            tenant_id=tenant_id,
            blob_counts=blob_counts,
        )
        if not blob_refs_updated:
            raise ApiError("BLOB_REFCOUNT_INVALID", "文件引用计数异常", status_code=500)

        await self._record_purged(
            root=root,
            retention_days=retention_days,
            cutoff=cutoff,
            purged_count=len(subtree_nodes),
            released_bytes=released_bytes,
            audit_context=audit_context,
        )
        await self._emit_search_delete_requests(
            nodes=subtree_nodes,
            root_id=root.id,
        )
        await self.repository.delete_versions_for_nodes(
            tenant_id=tenant_id,
            node_ids=node_ids,
        )
        for node in reversed(subtree_nodes):
            await self.repository.delete_node(
                tenant_id=tenant_id,
                node_id=node.id,
            )
        await self.repository.commit()
        return len(subtree_nodes), released_bytes

    async def _collect_deleted_subtree_for_update(self, *, root: Node) -> list[Node]:
        collected = [root]
        cursor = 0
        while cursor < len(collected):
            current = collected[cursor]
            cursor += 1
            if current.node_type != "folder":
                continue
            children = await self.repository.list_child_nodes_for_update(
                tenant_id=current.tenant_id,
                space_id=current.space_id,
                parent_id=current.id,
            )
            if any(not child.is_deleted for child in children):
                raise ApiError("NODE_PURGE_CONFLICT", "节点包含未删除子节点", status_code=409)
            collected.extend(children)
        return collected

    async def _emit_search_delete_requests(
        self,
        *,
        nodes: list[Node],
        root_id: UUID,
    ) -> None:
        for node in nodes:
            if node.node_type != "file":
                continue
            await emit_search_index_requested(
                audit_service=self.audit_service,
                tenant_id=node.tenant_id,
                node_id=node.id,
                space_id=node.space_id,
                reason="trash_retention_expired",
                metadata={"root_node_id": str(root_id)},
            )

    async def _record_purged(
        self,
        *,
        root: Node,
        retention_days: int,
        cutoff: datetime,
        purged_count: int,
        released_bytes: int,
        audit_context: AuditContext | None,
    ) -> None:
        if self.audit_service is None:
            return
        await self.audit_service.record(
            event=AuditEvent(
                tenant_id=root.tenant_id,
                actor_id=None,
                actor_type="system",
                action="file.trash.retention_purged",
                resource_type="node",
                resource_id=root.id,
                result="allowed",
                risk_level="medium",
                metadata={
                    "space_id": str(root.space_id),
                    "deleted_at": root.deleted_at.isoformat() if root.deleted_at else None,
                    "cutoff": cutoff.isoformat(),
                    "retention_days": retention_days,
                    "purged_count": purged_count,
                    "released_bytes": released_bytes,
                },
            ),
            context=audit_context or AuditContext(),
        )

    async def _record_failure(
        self,
        *,
        tenant_id: UUID,
        root_id: UUID,
        error: ApiError,
        retention_days: int,
        cutoff: datetime,
        audit_context: AuditContext | None,
    ) -> None:
        if self.audit_service is None:
            return
        await self.audit_service.record(
            event=AuditEvent(
                tenant_id=tenant_id,
                actor_id=None,
                actor_type="system",
                action="file.trash.retention_cleanup_failed",
                resource_type="node",
                resource_id=root_id,
                result="error",
                risk_level="medium",
                metadata={
                    "error_code": error.code,
                    "cutoff": cutoff.isoformat(),
                    "retention_days": retention_days,
                },
            ),
            context=audit_context or AuditContext(),
        )

    @staticmethod
    def _blob_ref_counts(*, versions: list[FileVersion]) -> dict[UUID, int]:
        counts: dict[UUID, int] = {}
        for version in versions:
            counts[version.blob_id] = counts.get(version.blob_id, 0) + 1
        return counts
