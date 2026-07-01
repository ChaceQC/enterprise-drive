from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class PreviewArtifactResponse(BaseModel):
    artifact_id: UUID
    artifact_type: str
    mime_type: str
    size_bytes: int
    preview_url: str
    expires_at: datetime
    headers: dict[str, str]


class FilePreviewResponse(BaseModel):
    node_id: UUID
    version_id: UUID
    status: str
    error: str | None
    artifact: PreviewArtifactResponse | None = None
