from __future__ import annotations

from uuid import UUID

from app.modules.audit.service import AuditService

SEARCH_ACL_REBUILD_REQUESTED = "search.acl_rebuild_requested"
SEARCH_EXTRACT_REQUESTED = "search.extract_requested"
SEARCH_INDEX_REQUESTED = "search.index_requested"


async def emit_search_index_requested(
    *,
    audit_service: AuditService | None,
    tenant_id: UUID,
    node_id: UUID,
    space_id: UUID,
    reason: str,
    metadata: dict[str, object] | None = None,
) -> None:
    if audit_service is None:
        return
    await audit_service.repository.add_outbox_event(
        tenant_id=tenant_id,
        event_type=SEARCH_INDEX_REQUESTED,
        aggregate_type="node",
        aggregate_id=node_id,
        payload={
            "node_id": str(node_id),
            "space_id": str(space_id),
            "reason": reason,
            **(metadata or {}),
        },
    )


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


async def emit_search_extract_requested(
    *,
    audit_service: AuditService | None,
    tenant_id: UUID,
    node_id: UUID,
    version_id: UUID,
    blob_id: UUID,
    reason: str,
    metadata: dict[str, object] | None = None,
) -> None:
    if audit_service is None:
        return
    await audit_service.repository.add_outbox_event(
        tenant_id=tenant_id,
        event_type=SEARCH_EXTRACT_REQUESTED,
        aggregate_type="file_version",
        aggregate_id=version_id,
        payload={
            "node_id": str(node_id),
            "version_id": str(version_id),
            "blob_id": str(blob_id),
            "reason": reason,
            **(metadata or {}),
        },
    )
