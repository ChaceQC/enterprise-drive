from __future__ import annotations

from uuid import UUID

from app.api.errors import ApiError
from app.core.security import utc_now
from app.modules.audit.schemas import AuditContext, AuditEvent
from app.modules.audit.service import AuditService
from app.modules.file.models import FileTreeOperation, FileVersion, Node
from app.modules.file.repository import FileRepository
from app.modules.file.tree import touch_node
from app.modules.quota.service import QuotaService
from app.modules.search.events import emit_search_index_requested


class FileTreeOperationProcessor:
    def __init__(
        self,
        *,
        repository: FileRepository,
        quota_service: QuotaService,
        batch_size: int,
        audit_service: AuditService | None = None,
    ) -> None:
        self.repository = repository
        self.quota_service = quota_service
        self.batch_size = batch_size
        self.audit_service = audit_service

    async def process_pending(
        self,
        *,
        limit: int,
        tenant_id: UUID | None = None,
    ) -> dict[str, int]:
        operation_ids = await self.repository.list_runnable_tree_operation_ids(
            limit=limit,
            tenant_id=tenant_id,
        )
        result = {"scanned": len(operation_ids), "completed": 0, "failed": 0}
        for operation_id in operation_ids:
            status = await self.process_operation(operation_id=operation_id)
            if status == "completed":
                result["completed"] += 1
            elif status == "failed":
                result["failed"] += 1
        return result

    async def process_operation(
        self,
        *,
        operation_id: UUID,
        max_batches: int | None = None,
    ) -> str:
        processed_batches = 0
        try:
            while True:
                operation = await self.repository.get_tree_operation_for_update(
                    operation_id=operation_id
                )
                if operation is None:
                    return "missing"
                if operation.status == "completed":
                    await self.repository.rollback()
                    return "completed"
                if operation.status == "failed":
                    await self.repository.rollback()
                    return "failed"
                if operation.status == "pending":
                    operation.status = "running"
                    operation.attempt_count += 1
                    operation.updated_at = utc_now()

                has_more = await self._process_batch(operation=operation)
                if not has_more:
                    await self._complete_operation(operation=operation)
                    await self.repository.commit()
                    return "completed"
                await self.repository.commit()
                processed_batches += 1
                if max_batches is not None and processed_batches >= max_batches:
                    return "running"
        except Exception as exc:
            await self.repository.rollback()
            await self._mark_failed(operation_id=operation_id, exc=exc)
            return "failed"

    async def _process_batch(self, *, operation: FileTreeOperation) -> bool:
        if operation.operation == "delete":
            return await self._process_delete_batch(operation=operation)
        if operation.operation == "restore":
            return await self._process_restore_batch(operation=operation)
        if operation.operation == "purge":
            return await self._process_purge_batch(operation=operation)
        raise ApiError(
            "FILE_TREE_OPERATION_INVALID",
            "文件树操作类型不合法",
            status_code=500,
        )

    async def _process_delete_batch(self, *, operation: FileTreeOperation) -> bool:
        root = await self.repository.get_node_by_id(
            tenant_id=operation.tenant_id,
            node_id=operation.node_id,
            include_deleted=True,
        )
        if root is None or not root.is_deleted:
            raise ApiError(
                "FILE_TREE_OPERATION_ROOT_INVALID",
                "后台删除根节点状态异常",
                status_code=500,
            )
        nodes = await self.repository.list_subtree_nodes_for_update(
            tenant_id=operation.tenant_id,
            space_id=operation.space_id,
            node_id=operation.node_id,
            limit=self.batch_size,
            is_deleted=False,
            deepest_first=False,
        )
        if not nodes:
            return False

        deleted_at = root.deleted_at or utc_now()
        for node in nodes:
            node.is_deleted = True
            node.deleted_at = deleted_at
            node.deleted_by = operation.user_id
            node.deleted_root_id = operation.node_id
            touch_node(node)
        await self.repository.flush()
        await self._emit_search_requests(
            nodes=nodes,
            reason="file_deleted",
            root_node_id=operation.node_id,
        )
        operation.processed_count += len(nodes)
        operation.updated_at = utc_now()
        return True

    async def _process_restore_batch(self, *, operation: FileTreeOperation) -> bool:
        root = await self.repository.get_node_by_id(
            tenant_id=operation.tenant_id,
            node_id=operation.node_id,
        )
        if root is None or root.is_deleted:
            raise ApiError(
                "FILE_TREE_OPERATION_ROOT_INVALID",
                "后台恢复根节点状态异常",
                status_code=500,
            )
        nodes = await self.repository.list_subtree_nodes_for_update(
            tenant_id=operation.tenant_id,
            space_id=operation.space_id,
            node_id=operation.node_id,
            limit=self.batch_size,
            is_deleted=True,
            deepest_first=False,
            deleted_root_id=operation.node_id,
        )
        if not nodes:
            return False

        for node in nodes:
            node.is_deleted = False
            node.deleted_at = None
            node.deleted_by = None
            node.deleted_root_id = None
            touch_node(node)
        await self.repository.flush()
        await self._emit_search_requests(
            nodes=nodes,
            reason="file_restored",
            root_node_id=operation.node_id,
        )
        operation.processed_count += len(nodes)
        operation.updated_at = utc_now()
        return True

    async def _process_purge_batch(self, *, operation: FileTreeOperation) -> bool:
        nodes = await self.repository.list_subtree_nodes_for_update(
            tenant_id=operation.tenant_id,
            space_id=operation.space_id,
            node_id=operation.node_id,
            limit=self.batch_size,
            is_deleted=True,
            deepest_first=True,
        )
        if not nodes:
            return False

        node_ids = [node.id for node in nodes]
        versions = await self.repository.list_versions_for_nodes(
            tenant_id=operation.tenant_id,
            node_ids=node_ids,
        )
        released_bytes = sum(version.size_bytes for version in versions)
        await self.quota_service.release_file_usage(
            tenant_id=operation.tenant_id,
            space_id=operation.space_id,
            ref_id=operation.node_id,
            size_bytes=released_bytes,
            version_ids=[version.id for version in versions],
        )
        blob_refs_updated = await self.repository.decrement_blob_ref_counts(
            tenant_id=operation.tenant_id,
            blob_counts=self._blob_ref_counts(versions=versions),
        )
        if not blob_refs_updated:
            raise ApiError("BLOB_REFCOUNT_INVALID", "文件引用计数异常", status_code=500)

        await self._emit_search_requests(
            nodes=nodes,
            reason="file_purged",
            root_node_id=operation.node_id,
        )
        await self.repository.delete_versions_for_nodes(
            tenant_id=operation.tenant_id,
            node_ids=node_ids,
        )
        for node in nodes:
            await self.repository.delete_node(
                tenant_id=operation.tenant_id,
                node_id=node.id,
            )
        operation.processed_count += len(nodes)
        operation.released_bytes += released_bytes
        operation.updated_at = utc_now()
        return True

    async def _complete_operation(self, *, operation: FileTreeOperation) -> None:
        now = utc_now()
        operation.status = "completed"
        operation.processed_count = operation.total_count
        operation.error_code = None
        operation.completed_at = now
        operation.updated_at = now
        await self._record_operation_audit(
            operation=operation,
            action="file.tree_operation.completed",
            result="allowed",
        )

    async def _mark_failed(self, *, operation_id: UUID, exc: Exception) -> None:
        operation = await self.repository.get_tree_operation_for_update(operation_id=operation_id)
        if operation is None or operation.status == "completed":
            await self.repository.rollback()
            return
        operation.status = "failed"
        operation.error_code = (
            exc.code if isinstance(exc, ApiError) else "FILE_TREE_OPERATION_FAILED"
        )
        operation.updated_at = utc_now()
        await self._record_operation_audit(
            operation=operation,
            action="file.tree_operation.failed",
            result="failed",
        )
        await self.repository.commit()

    async def _record_operation_audit(
        self,
        *,
        operation: FileTreeOperation,
        action: str,
        result: str,
    ) -> None:
        if self.audit_service is None:
            return
        await self.audit_service.record(
            event=AuditEvent(
                tenant_id=operation.tenant_id,
                actor_id=operation.user_id,
                action=action,
                resource_type="node",
                resource_id=operation.node_id,
                result=result,
                metadata={
                    "operation_id": str(operation.id),
                    "operation": operation.operation,
                    "processed_count": operation.processed_count,
                    "total_count": operation.total_count,
                    "released_bytes": operation.released_bytes,
                    "error_code": operation.error_code,
                },
            ),
            context=AuditContext(request_id=operation.request_id),
        )

    async def _emit_search_requests(
        self,
        *,
        nodes: list[Node],
        reason: str,
        root_node_id: UUID,
    ) -> None:
        for node in nodes:
            if node.node_type != "file":
                continue
            await emit_search_index_requested(
                audit_service=self.audit_service,
                tenant_id=node.tenant_id,
                node_id=node.id,
                space_id=node.space_id,
                reason=reason,
                metadata={"root_node_id": str(root_node_id), "background": True},
            )

    def _blob_ref_counts(self, *, versions: list[FileVersion]) -> dict[UUID, int]:
        counts: dict[UUID, int] = {}
        for version in versions:
            counts[version.blob_id] = counts.get(version.blob_id, 0) + 1
        return counts
