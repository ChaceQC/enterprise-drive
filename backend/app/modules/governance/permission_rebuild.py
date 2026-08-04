from __future__ import annotations

from uuid import UUID

from app.core.security import utc_now
from app.modules.audit.schemas import AuditContext, AuditEvent
from app.modules.audit.service import AuditService
from app.modules.governance.models import PermissionRebuildOperation
from app.modules.governance.repository import GovernanceRepository
from app.modules.search.indexer import SearchIndexService


class PermissionRebuildProcessor:
    def __init__(
        self,
        *,
        repository: GovernanceRepository,
        index_service: SearchIndexService,
        audit_service: AuditService,
        batch_size: int,
    ) -> None:
        self.repository = repository
        self.index_service = index_service
        self.audit_service = audit_service
        self.batch_size = batch_size

    async def process_pending(
        self,
        *,
        limit: int,
        tenant_id: UUID | None = None,
    ) -> dict[str, int]:
        operation_ids = await self.repository.list_runnable_permission_rebuild_ids(
            limit=limit,
            tenant_id=tenant_id,
        )
        result = {
            "scanned": len(operation_ids),
            "completed": 0,
            "running": 0,
            "failed": 0,
        }
        for operation_id in operation_ids:
            status = await self.process_operation(operation_id=operation_id)
            if status in result:
                result[status] += 1
        return result

    async def process_operation(
        self,
        *,
        operation_id: UUID,
        max_batches: int | None = None,
    ) -> str:
        batches = 0
        try:
            while True:
                operation = await self.repository.get_permission_rebuild_for_update(
                    operation_id=operation_id
                )
                if operation is None:
                    await self.repository.rollback()
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
                if operation.restart_requested:
                    await self._restart(operation)
                    await self.repository.commit()
                    continue

                batch = await self.repository.list_permission_rebuild_batch(
                    operation=operation,
                    limit=self.batch_size,
                )
                if not batch:
                    if operation.restart_requested:
                        await self._restart(operation)
                        await self.repository.commit()
                        continue
                    await self._complete(operation)
                    await self.repository.commit()
                    return "completed"

                indexed = 0
                for node_id, created_at in batch:
                    if await self.index_service.index_file(
                        tenant_id=operation.tenant_id,
                        node_id=node_id,
                    ):
                        indexed += 1
                    operation.cursor_created_at = created_at
                    operation.cursor_node_id = node_id
                    operation.processed_count += 1
                operation.indexed_count += indexed
                operation.updated_at = utc_now()
                await self.repository.commit()
                batches += 1
                if max_batches is not None and batches >= max_batches:
                    return "running"
        except Exception as exc:
            await self.repository.rollback()
            await self._fail(operation_id=operation_id, exc=exc)
            return "failed"

    async def _restart(self, operation: PermissionRebuildOperation) -> None:
        operation.snapshot_at = utc_now()
        operation.cursor_created_at = None
        operation.cursor_node_id = None
        operation.processed_count = 0
        operation.indexed_count = 0
        operation.total_count = await self.repository.count_permission_rebuild_files(
            tenant_id=operation.tenant_id,
            space_id=operation.space_id,
            root_node_id=operation.root_node_id,
            snapshot_at=operation.snapshot_at,
        )
        operation.restart_requested = False
        operation.updated_at = utc_now()

    async def _complete(self, operation: PermissionRebuildOperation) -> None:
        now = utc_now()
        operation.status = "completed"
        operation.total_count = operation.processed_count
        operation.error_code = None
        operation.completed_at = now
        operation.updated_at = now
        await self._record(
            operation=operation,
            action="permission.rebuild.completed",
            result="allowed",
        )

    async def _fail(self, *, operation_id: UUID, exc: Exception) -> None:
        operation = await self.repository.get_permission_rebuild_for_update(
            operation_id=operation_id
        )
        if operation is None or operation.status == "completed":
            await self.repository.rollback()
            return
        operation.status = "failed"
        operation.error_code = type(exc).__name__[:128]
        operation.updated_at = utc_now()
        await self._record(
            operation=operation,
            action="permission.rebuild.failed",
            result="failed",
        )
        await self.repository.commit()

    async def _record(
        self,
        *,
        operation: PermissionRebuildOperation,
        action: str,
        result: str,
    ) -> None:
        await self.audit_service.record(
            event=AuditEvent(
                tenant_id=operation.tenant_id,
                actor_id=operation.requested_by,
                action=action,
                resource_type=operation.scope,
                resource_id=operation.root_node_id or operation.space_id,
                result=result,
                risk_level="medium",
                metadata={
                    "operation_id": str(operation.id),
                    "scope": operation.scope,
                    "permission_version": operation.permission_version,
                    "processed_count": operation.processed_count,
                    "indexed_count": operation.indexed_count,
                    "attempt_count": operation.attempt_count,
                    "error_code": operation.error_code,
                },
            ),
            context=AuditContext(request_id=operation.request_id),
        )
