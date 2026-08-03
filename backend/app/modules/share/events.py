from __future__ import annotations

from uuid import UUID

from app.modules.audit.service import AuditService

SHARE_RECIPIENTS_REBUILD_REQUESTED = "share.recipients_rebuild_requested"


async def emit_share_recipients_rebuild_requested(
    *,
    audit_service: AuditService | None,
    tenant_id: UUID,
    scope: str,
    resource_id: UUID,
    reason: str,
    affected_user_id: UUID | None,
    metadata: dict[str, object],
) -> None:
    if audit_service is None:
        return
    await audit_service.repository.add_outbox_event(
        tenant_id=tenant_id,
        event_type=SHARE_RECIPIENTS_REBUILD_REQUESTED,
        aggregate_type=scope,
        aggregate_id=resource_id,
        payload={
            "scope": scope,
            "resource_id": str(resource_id),
            "reason": reason,
            "affected_user_id": str(affected_user_id) if affected_user_id is not None else None,
            **metadata,
        },
        flush=False,
    )
