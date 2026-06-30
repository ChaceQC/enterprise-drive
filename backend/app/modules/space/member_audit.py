from __future__ import annotations

from uuid import UUID

from app.modules.audit.schemas import AuditContext, AuditEvent
from app.modules.audit.service import AuditService
from app.modules.auth.models import User


async def record_member_event(
    *,
    audit_service: AuditService | None,
    current_user: User,
    space_id: UUID,
    target_user_id: UUID | None,
    action: str,
    audit_context: AuditContext | None,
    result: str = "allowed",
    metadata: dict[str, object] | None = None,
) -> None:
    if audit_service is None:
        return
    event_metadata = dict(metadata or {})
    if target_user_id is not None:
        event_metadata["target_user_id"] = str(target_user_id)
    await audit_service.record(
        event=AuditEvent(
            tenant_id=current_user.tenant_id,
            actor_id=current_user.id,
            action=action,
            resource_type="space",
            resource_id=space_id,
            result=result,
            risk_level="high",
            metadata=event_metadata,
        ),
        context=audit_context or AuditContext(),
    )
