from __future__ import annotations

from uuid import UUID, uuid4


def build_upload_storage_key(*, tenant_id: UUID, upload_session_hint: str) -> str:
    safe_hint = upload_session_hint.lower().replace(":", "-")[:48]
    return f"uploads/{tenant_id}/{safe_hint}/{uuid4()}"


def build_object_storage_key(*, tenant_id: UUID, content_hash: str) -> str:
    normalized_hash = content_hash.lower()
    hash_prefix = normalized_hash[:2]
    return f"objects/{tenant_id}/{hash_prefix}/{normalized_hash}"
