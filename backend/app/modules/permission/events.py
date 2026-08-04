from __future__ import annotations

from uuid import UUID

from app.modules.audit.service import AuditService
from app.modules.search.events import emit_search_acl_rebuild_requested
from app.modules.share.events import emit_share_recipients_rebuild_requested


async def emit_permission_changed(
    *,
    audit_service: AuditService | None,
    tenant_id: UUID,
    actor_id: UUID,
    scope: str,
    resource_id: UUID,
    permission_version: int,
    reason: str,
    affected_user_id: UUID | None = None,
    metadata: dict[str, object],
) -> None:
    if audit_service is None:
        return
    await audit_service.record_permission_changed(
        tenant_id=tenant_id,
        actor_id=actor_id,
        scope=scope,
        resource_id=resource_id,
        permission_version=permission_version,
        reason=reason,
        affected_user_id=affected_user_id,
        metadata=metadata,
    )
    await emit_search_acl_rebuild_requested(
        audit_service=audit_service,
        tenant_id=tenant_id,
        scope=scope,
        resource_id=resource_id,
        permission_version=permission_version,
        reason=reason,
        metadata={
            "actor_id": str(actor_id),
            **metadata,
        },
    )
    if scope == "tenant":
        await emit_share_recipients_rebuild_requested(
            audit_service=audit_service,
            tenant_id=tenant_id,
            scope=scope,
            resource_id=resource_id,
            reason=reason,
            affected_user_id=affected_user_id,
            metadata=metadata,
        )
