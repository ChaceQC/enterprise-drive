from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog, OutboxEvent
from app.modules.audit.schemas import AuditContext, AuditEvent


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_audit_log(self, *, event: AuditEvent, context: AuditContext) -> AuditLog:
        audit_log = AuditLog(
            tenant_id=event.tenant_id,
            actor_id=event.actor_id,
            actor_type=event.actor_type,
            action=event.action,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            result=event.result,
            risk_level=event.risk_level,
            request_id=context.request_id,
            ip=context.ip,
            user_agent=context.user_agent,
            metadata_json=event.metadata,
        )
        self.session.add(audit_log)
        await self.session.flush()
        return audit_log

    async def add_outbox_event(
        self,
        *,
        tenant_id: UUID,
        event_type: str,
        aggregate_type: str,
        aggregate_id: UUID,
        payload: dict[str, object],
    ) -> OutboxEvent:
        outbox_event = OutboxEvent(
            tenant_id=tenant_id,
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=payload,
        )
        self.session.add(outbox_event)
        await self.session.flush()
        return outbox_event
