from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.api.errors import ApiError
from app.core.config import Settings
from app.core.pagination import decode_page_cursor, encode_page_cursor
from app.core.security import ensure_utc
from app.modules.admin.schemas import AdminAuditLogListResponse, AdminAuditLogResponse
from app.modules.audit.repository import AuditRepository
from app.modules.audit.schemas import AuditContext, AuditEvent
from app.modules.audit.service import AuditService
from app.modules.auth.models import User


class AdminAuditService:
    def __init__(
        self,
        *,
        repository: AuditRepository,
        audit_service: AuditService,
        settings: Settings,
    ) -> None:
        self.repository = repository
        self.audit_service = audit_service
        self.settings = settings

    async def list_audit_logs(
        self,
        *,
        current_user: User,
        actor_id: UUID | None,
        actor_type: str | None,
        action: str | None,
        resource_type: str | None,
        resource_id: UUID | None,
        result: str | None,
        risk_level: str | None,
        request_id: str | None,
        created_from: datetime | None,
        created_to: datetime | None,
        cursor: str | None,
        page_size: int,
        audit_context: AuditContext | None = None,
    ) -> AdminAuditLogListResponse:
        normalized_from = ensure_utc(created_from) if created_from is not None else None
        normalized_to = ensure_utc(created_to) if created_to is not None else None
        filters = self._filter_metadata(
            actor_id=actor_id,
            actor_type=actor_type,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            result=result,
            risk_level=risk_level,
            request_id=request_id,
            created_from=normalized_from,
            created_to=normalized_to,
        )
        if not current_user.is_super_admin:
            await self._record_query(
                current_user=current_user,
                result="denied",
                audit_context=audit_context,
                metadata={"reason": "super_admin_required", "filters": filters},
            )
            await self.repository.commit()
            raise ApiError("ADMIN_REQUIRED", "需要系统管理员权限", status_code=403)
        if (
            normalized_from is not None
            and normalized_to is not None
            and normalized_from > normalized_to
        ):
            await self._record_query(
                current_user=current_user,
                result="denied",
                audit_context=audit_context,
                metadata={"reason": "invalid_time_range", "filters": filters},
            )
            await self.repository.commit()
            raise ApiError(
                "AUDIT_TIME_RANGE_INVALID",
                "审计时间范围不合法",
                status_code=422,
            )

        decoded_cursor = decode_page_cursor(self.settings, cursor)
        logs = await self.repository.list_audit_logs(
            tenant_id=current_user.tenant_id,
            actor_id=actor_id,
            actor_type=actor_type,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            result=result,
            risk_level=risk_level,
            request_id=request_id,
            created_from=normalized_from,
            created_to=normalized_to,
            cursor=decoded_cursor,
            limit=page_size + 1,
        )
        page_logs = logs[:page_size]
        next_cursor = None
        if len(logs) > page_size and page_logs:
            last_log = page_logs[-1]
            next_cursor = encode_page_cursor(
                self.settings,
                created_at=last_log.created_at,
                item_id=last_log.id,
            )

        response = AdminAuditLogListResponse(
            items=[
                AdminAuditLogResponse(
                    id=log.id,
                    tenant_id=log.tenant_id,
                    actor_id=log.actor_id,
                    actor_type=log.actor_type,
                    action=log.action,
                    resource_type=log.resource_type,
                    resource_id=log.resource_id,
                    result=log.result,
                    risk_level=log.risk_level,
                    request_id=log.request_id,
                    ip=log.ip,
                    user_agent=log.user_agent,
                    metadata=log.metadata_json,
                    created_at=log.created_at,
                )
                for log in page_logs
            ],
            next_cursor=next_cursor,
        )
        await self._record_query(
            current_user=current_user,
            result="allowed",
            audit_context=audit_context,
            metadata={
                "filters": filters,
                "page_size": page_size,
                "returned_count": len(page_logs),
                "has_next": next_cursor is not None,
            },
        )
        await self.repository.commit()
        return response

    async def _record_query(
        self,
        *,
        current_user: User,
        result: str,
        audit_context: AuditContext | None,
        metadata: dict[str, object],
    ) -> None:
        await self.audit_service.record(
            event=AuditEvent(
                tenant_id=current_user.tenant_id,
                actor_id=current_user.id,
                action="admin.audit_logs.queried",
                resource_type="audit_log",
                result=result,
                risk_level="medium",
                metadata=metadata,
            ),
            context=audit_context or AuditContext(),
        )

    @staticmethod
    def _filter_metadata(
        *,
        actor_id: UUID | None,
        actor_type: str | None,
        action: str | None,
        resource_type: str | None,
        resource_id: UUID | None,
        result: str | None,
        risk_level: str | None,
        request_id: str | None,
        created_from: datetime | None,
        created_to: datetime | None,
    ) -> dict[str, object]:
        values: dict[str, object | None] = {
            "actor_id": str(actor_id) if actor_id is not None else None,
            "actor_type": actor_type,
            "action": action,
            "resource_type": resource_type,
            "resource_id": str(resource_id) if resource_id is not None else None,
            "result": result,
            "risk_level": risk_level,
            "request_id": request_id,
            "created_from": created_from.isoformat() if created_from is not None else None,
            "created_to": created_to.isoformat() if created_to is not None else None,
        }
        return {key: value for key, value in values.items() if value is not None}
