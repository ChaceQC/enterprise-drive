from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.core.security import utc_now
from app.modules.sync.models import ClientOperation

_OPERATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


@dataclass(frozen=True)
class ClientOperationStart:
    record: ClientOperation | None
    replay_json: dict[str, object] | None
    pending: bool = False


class ClientOperationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def start(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        operation_id: str | None,
        action: str,
        request_payload: dict[str, object],
        allow_pending_recovery: bool = False,
    ) -> ClientOperationStart:
        if operation_id is None:
            self._bind_context(actor_id=user_id, operation_id=None)
            return ClientOperationStart(record=None, replay_json=None)

        normalized_id = operation_id.strip()
        if not _OPERATION_ID_PATTERN.fullmatch(normalized_id):
            raise ApiError(
                "CLIENT_OPERATION_ID_INVALID",
                "客户端操作 ID 格式不合法",
                status_code=400,
            )
        request_hash = self._request_hash(action=action, payload=request_payload)
        existing = await self._get(
            tenant_id=tenant_id,
            user_id=user_id,
            operation_id=normalized_id,
        )
        if existing is not None:
            return self._existing_start(
                existing=existing,
                request_hash=request_hash,
                allow_pending_recovery=allow_pending_recovery,
            )

        try:
            async with self.session.begin_nested():
                record = ClientOperation(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    operation_id=normalized_id,
                    action=action,
                    request_hash=request_hash,
                    status="pending",
                    response_json={},
                )
                self.session.add(record)
                await self.session.flush()
        except IntegrityError as exc:
            existing = await self._get(
                tenant_id=tenant_id,
                user_id=user_id,
                operation_id=normalized_id,
            )
            if existing is None:
                raise ApiError(
                    "CLIENT_OPERATION_IN_PROGRESS",
                    "客户端操作正在处理中",
                    status_code=409,
                ) from exc
            return self._existing_start(
                existing=existing,
                request_hash=request_hash,
                allow_pending_recovery=allow_pending_recovery,
            )

        self._bind_context(actor_id=user_id, operation_id=normalized_id)
        return ClientOperationStart(record=record, replay_json=None)

    def complete(
        self,
        *,
        record: ClientOperation | None,
        response: BaseModel | dict[str, object],
        response_status: int,
    ) -> None:
        if record is None:
            return
        response_json = (
            response.model_dump(mode="json") if isinstance(response, BaseModel) else response
        )
        record.status = "completed"
        record.response_status = response_status
        record.response_json = response_json
        record.updated_at = utc_now()

    async def _get(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        operation_id: str,
    ) -> ClientOperation | None:
        result = await self.session.execute(
            select(ClientOperation).where(
                ClientOperation.tenant_id == tenant_id,
                ClientOperation.user_id == user_id,
                ClientOperation.operation_id == operation_id,
            )
        )
        return result.scalar_one_or_none()

    def _existing_start(
        self,
        *,
        existing: ClientOperation,
        request_hash: str,
        allow_pending_recovery: bool,
    ) -> ClientOperationStart:
        if existing.request_hash != request_hash or existing.action == "":
            raise ApiError(
                "CLIENT_OPERATION_ID_REUSED",
                "客户端操作 ID 已用于其他请求",
                status_code=409,
            )
        self._bind_context(
            actor_id=existing.user_id,
            operation_id=existing.operation_id,
        )
        if existing.status == "completed":
            return ClientOperationStart(
                record=None,
                replay_json=dict(existing.response_json),
            )
        if allow_pending_recovery:
            return ClientOperationStart(record=existing, replay_json=None, pending=True)
        raise ApiError(
            "CLIENT_OPERATION_IN_PROGRESS",
            "客户端操作正在处理中",
            status_code=409,
        )

    def _bind_context(self, *, actor_id: UUID, operation_id: str | None) -> None:
        self.session.info["actor_id"] = actor_id
        if operation_id is None:
            self.session.info.pop("client_operation_id", None)
        else:
            self.session.info["client_operation_id"] = operation_id

    @staticmethod
    def _request_hash(*, action: str, payload: dict[str, object]) -> str:
        encoded = json.dumps(
            {"action": action, "payload": payload},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
