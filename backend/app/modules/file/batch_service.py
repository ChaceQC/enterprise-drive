from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.api.errors import ApiError
from app.modules.audit.schemas import AuditContext
from app.modules.auth.models import User
from app.modules.file.models import FileBatchOperation
from app.modules.file.repository import FileRepository
from app.modules.file.schemas import (
    BatchNodeResult,
    BatchOperationResponse,
    FileTreeOperationResponse,
)
from app.modules.file.service import FileService


class FileBatchService:
    def __init__(
        self,
        *,
        repository: FileRepository,
        file_service: FileService,
    ) -> None:
        self.repository = repository
        self.file_service = file_service

    async def batch_delete(
        self,
        *,
        current_user: User,
        node_ids: list[UUID],
        idempotency_key: str,
        audit_context: AuditContext | None = None,
    ) -> BatchOperationResponse:
        return await self._run_batch(
            current_user=current_user,
            operation="delete",
            node_ids=node_ids,
            idempotency_key=idempotency_key,
            request_payload={"node_ids": [str(node_id) for node_id in node_ids], "mode": "trash"},
            handler=lambda node_id: self.file_service.delete_node_in_transaction(
                current_user=current_user,
                node_id=node_id,
                expected_current_version_id=None,
                audit_context=audit_context,
            ),
        )

    async def batch_move(
        self,
        *,
        current_user: User,
        node_ids: list[UUID],
        target_parent_id: UUID,
        new_name: str | None,
        conflict_policy: str,
        idempotency_key: str,
        audit_context: AuditContext | None = None,
    ) -> BatchOperationResponse:
        return await self._run_batch(
            current_user=current_user,
            operation="move",
            node_ids=node_ids,
            idempotency_key=idempotency_key,
            request_payload={
                "node_ids": [str(node_id) for node_id in node_ids],
                "target_parent_id": str(target_parent_id),
                "new_name": new_name,
                "conflict_policy": conflict_policy,
            },
            handler=lambda node_id: self.file_service.move_node_in_transaction(
                current_user=current_user,
                node_id=node_id,
                target_parent_id=target_parent_id,
                new_name=new_name,
                conflict_policy=conflict_policy,
                expected_current_version_id=None,
                audit_context=audit_context,
            ),
        )

    async def batch_restore(
        self,
        *,
        current_user: User,
        node_ids: list[UUID],
        target_parent_id: UUID | None,
        new_name: str | None,
        conflict_policy: str,
        idempotency_key: str,
        audit_context: AuditContext | None = None,
    ) -> BatchOperationResponse:
        return await self._run_batch(
            current_user=current_user,
            operation="restore",
            node_ids=node_ids,
            idempotency_key=idempotency_key,
            request_payload={
                "node_ids": [str(node_id) for node_id in node_ids],
                "target_parent_id": str(target_parent_id) if target_parent_id else None,
                "new_name": new_name,
                "conflict_policy": conflict_policy,
            },
            handler=lambda node_id: self.file_service.restore_node_in_transaction(
                current_user=current_user,
                node_id=node_id,
                target_parent_id=target_parent_id,
                new_name=new_name,
                conflict_policy=conflict_policy,
                audit_context=audit_context,
            ),
        )

    async def batch_purge(
        self,
        *,
        current_user: User,
        node_ids: list[UUID],
        idempotency_key: str,
        audit_context: AuditContext | None = None,
    ) -> BatchOperationResponse:
        return await self._run_batch(
            current_user=current_user,
            operation="purge",
            node_ids=node_ids,
            idempotency_key=idempotency_key,
            request_payload={"node_ids": [str(node_id) for node_id in node_ids]},
            handler=lambda node_id: self.file_service.purge_node_in_transaction(
                current_user=current_user,
                node_id=node_id,
                audit_context=audit_context,
            ),
        )

    async def _run_batch(
        self,
        *,
        current_user: User,
        operation: str,
        node_ids: list[UUID],
        idempotency_key: str,
        request_payload: dict[str, object],
        handler: Callable[[UUID], Awaitable[object]],
    ) -> BatchOperationResponse:
        operation_record, replay = await self._start_batch_operation(
            current_user=current_user,
            operation=operation,
            idempotency_key=idempotency_key,
            request_payload=request_payload,
        )
        if replay is not None:
            return replay
        assert operation_record is not None

        results: list[BatchNodeResult] = []
        for node_id in node_ids:
            try:
                async with self.repository.begin_nested():
                    item_response = await handler(node_id)
            except ApiError as exc:
                results.append(BatchNodeResult(node_id=node_id, status="failed", code=exc.code))
            except IntegrityError:
                results.append(
                    BatchNodeResult(node_id=node_id, status="failed", code="NODE_NAME_EXISTS")
                )
            else:
                results.append(
                    BatchNodeResult(
                        node_id=node_id,
                        status="success",
                        operation_id=(
                            item_response.operation_id
                            if isinstance(item_response, FileTreeOperationResponse)
                            else None
                        ),
                    )
                )

        response = BatchOperationResponse(results=results)
        operation_record.response_json = response.model_dump(mode="json")
        await self.repository.commit()
        return response

    async def _start_batch_operation(
        self,
        *,
        current_user: User,
        operation: str,
        idempotency_key: str,
        request_payload: dict[str, object],
    ) -> tuple[FileBatchOperation | None, BatchOperationResponse | None]:
        normalized_key = idempotency_key.strip()
        if not normalized_key:
            raise ApiError("IDEMPOTENCY_KEY_INVALID", "幂等键不能为空", status_code=400)

        idempotency_key_hash = hashlib.sha256(normalized_key.encode("utf-8")).hexdigest()
        request_hash = self._batch_request_hash(
            operation=operation,
            request_payload=request_payload,
        )
        existing = await self.repository.get_batch_operation(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            operation=operation,
            idempotency_key_hash=idempotency_key_hash,
        )
        if existing is not None:
            return self._replay_batch_operation(existing=existing, request_hash=request_hash)

        try:
            async with self.repository.begin_nested():
                record = await self.repository.create_batch_operation(
                    tenant_id=current_user.tenant_id,
                    user_id=current_user.id,
                    operation=operation,
                    idempotency_key_hash=idempotency_key_hash,
                    request_hash=request_hash,
                    response_json={"results": []},
                )
        except IntegrityError as exc:
            existing = await self.repository.get_batch_operation(
                tenant_id=current_user.tenant_id,
                user_id=current_user.id,
                operation=operation,
                idempotency_key_hash=idempotency_key_hash,
            )
            if existing is None:
                raise ApiError(
                    "IDEMPOTENCY_KEY_CONFLICT",
                    "幂等键正在被其他请求使用",
                    status_code=409,
                ) from exc
            return self._replay_batch_operation(existing=existing, request_hash=request_hash)
        return record, None

    def _replay_batch_operation(
        self,
        *,
        existing: FileBatchOperation,
        request_hash: str,
    ) -> tuple[None, BatchOperationResponse]:
        if existing.request_hash != request_hash:
            raise ApiError(
                "IDEMPOTENCY_KEY_REUSED",
                "幂等键已用于其他请求",
                status_code=409,
            )
        return None, BatchOperationResponse.model_validate(existing.response_json)

    def _batch_request_hash(
        self,
        *,
        operation: str,
        request_payload: dict[str, object],
    ) -> str:
        payload = json.dumps(
            {"operation": operation, "payload": request_payload},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()
