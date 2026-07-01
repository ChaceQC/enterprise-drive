from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class SearchFileItem(BaseModel):
    node_id: UUID
    space_id: UUID
    name: str
    mime_type: str | None
    size_bytes: int
    updated_at: datetime
    score: float | None = None


class SearchFilesResponse(BaseModel):
    query: str
    total: int
    items: list[SearchFileItem]
