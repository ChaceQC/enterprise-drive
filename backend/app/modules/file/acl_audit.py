from __future__ import annotations

from app.modules.audit.schemas import AuditContext, AuditEvent
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.file.models import Node


async def record_acl_event(
    *,
    audit_service: AuditService | None,
    current_user: User,
    node: Node,
    action: str,
    audit_context: AuditContext | None,
    metadata: dict[str, object],
) -> None:
    if audit_service is None:
        return
    await audit_service.record(
        event=AuditEvent(
            tenant_id=current_user.tenant_id,
            actor_id=current_user.id,
            action=action,
            resource_type="node",
            resource_id=node.id,
            result="allowed",
            risk_level="high",
            metadata={"space_id": str(node.space_id), **metadata},
        ),
        context=audit_context or AuditContext(),
    )
