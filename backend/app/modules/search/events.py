from __future__ import annotations

from uuid import UUID

from app.modules.audit.service import AuditService

SEARCH_ACL_REBUILD_REQUESTED = "search.acl_rebuild_requested"


async def emit_search_acl_rebuild_requested(
    *,
    audit_service: AuditService | None,
    tenant_id: UUID,
    scope: str,
    resource_id: UUID,
    permission_version: int,
    reason: str,
    metadata: dict[str, object] | None = None,
) -> None:
    if audit_service is None:
        return
    await audit_service.repository.add_outbox_event(
        tenant_id=tenant_id,
        event_type=SEARCH_ACL_REBUILD_REQUESTED,
        aggregate_type=scope,
        aggregate_id=resource_id,
        payload={
            "scope": scope,
            "resource_id": str(resource_id),
            "permission_version": permission_version,
            "reason": reason,
            **(metadata or {}),
        },
    )
