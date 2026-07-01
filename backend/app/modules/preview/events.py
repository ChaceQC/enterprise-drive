from __future__ import annotations

from uuid import UUID

from app.modules.audit.service import AuditService

PREVIEW_RENDER_REQUESTED = "preview.render_requested"


async def emit_preview_render_requested(
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
        event_type=PREVIEW_RENDER_REQUESTED,
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
