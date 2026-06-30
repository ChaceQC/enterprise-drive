from __future__ import annotations

from uuid import UUID

from app.modules.audit.schemas import AuditContext, AuditEvent
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.file.models import Node
from app.modules.upload.models import UploadSession


async def record_upload_event(
    *,
    audit_service: AuditService | None,
    current_user: User,
    action: str,
    resource_id: UUID,
    result: str = "allowed",
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
            resource_type="upload",
            resource_id=resource_id,
            result=result,
            metadata=metadata,
        ),
        context=audit_context or AuditContext(),
    )


def instant_upload_metadata(*, node: Node, blob_id: UUID) -> dict[str, object]:
    return {
        "mode": "instant",
        "node_id": str(node.id),
        "space_id": str(node.space_id),
        "parent_id": str(node.parent_id) if node.parent_id else None,
        "blob_id": str(blob_id),
    }


def multipart_upload_metadata(*, upload_session: UploadSession) -> dict[str, object]:
    return {
        "mode": "multipart",
        "space_id": str(upload_session.space_id),
        "parent_id": str(upload_session.parent_id),
        "size_bytes": upload_session.size_bytes,
        "total_parts": upload_session.total_parts,
    }
