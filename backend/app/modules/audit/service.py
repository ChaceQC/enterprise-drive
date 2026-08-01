from __future__ import annotations

from uuid import UUID

from app.modules.audit.repository import AuditRepository
from app.modules.audit.schemas import AuditContext, AuditEvent


class AuditService:
    def __init__(self, *, repository: AuditRepository) -> None:
        self.repository = repository

    async def record(self, *, event: AuditEvent, context: AuditContext) -> None:
        audit_log = await self.repository.add_audit_log(
            event=event,
            context=context,
            flush=False,
        )
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
            flush=False,
        )

    async def record_permission_changed(
        self,
        *,
        tenant_id: UUID,
        actor_id: UUID,
        scope: str,
        resource_id: UUID,
        permission_version: int,
        reason: str,
        affected_user_id: UUID | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        payload = {
            "scope": scope,
            "resource_id": str(resource_id),
            "permission_version": permission_version,
            "reason": reason,
            "actor_id": str(actor_id),
            **(metadata or {}),
        }
        if affected_user_id is not None:
            payload["affected_user_id"] = str(affected_user_id)
        await self.repository.add_outbox_event(
            tenant_id=tenant_id,
            event_type="permission.changed",
            aggregate_type=scope,
            aggregate_id=resource_id,
            payload=payload,
            flush=False,
        )
