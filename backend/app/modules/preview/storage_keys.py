from __future__ import annotations

from uuid import UUID


def build_preview_storage_key(
    *,
    tenant_id: UUID,
    node_id: UUID,
    version_id: UUID,
    artifact_type: str,
    extension: str,
) -> str:
    safe_extension = extension.lstrip(".").lower() or "bin"
    return f"previews/{tenant_id}/{node_id}/{version_id}/{artifact_type}.{safe_extension}"
