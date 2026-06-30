from __future__ import annotations

from app.modules.audit.repository import AuditRepository
from app.modules.audit.schemas import AuditContext, AuditEvent


class AuditService:
    def __init__(self, *, repository: AuditRepository) -> None:
        self.repository = repository

    async def record(self, *, event: AuditEvent, context: AuditContext) -> None:
        audit_log = await self.repository.add_audit_log(event=event, context=context)
        await self.repository.add_outbox_event(
            tenant_id=event.tenant_id,
            event_type=f"audit.{event.action}",
            aggregate_type="audit_log",
            aggregate_id=audit_log.id,
            payload={
                "audit_log_id": str(audit_log.id),
                "action": event.action,
                "result": event.result,
                "resource_type": event.resource_type,
                "resource_id": str(event.resource_id) if event.resource_id else None,
                "actor_id": str(event.actor_id) if event.actor_id else None,
                "risk_level": event.risk_level,
            },
        )
