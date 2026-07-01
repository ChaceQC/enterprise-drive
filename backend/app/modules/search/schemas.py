from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class SearchFileItem(BaseModel):
    node_id: UUID
    space_id: UUID
    name: str
    mime_type: str | None
    size_bytes: int
    updated_at: datetime
    score: float | None = None
    highlights: dict[str, list[str]] = Field(default_factory=dict)


class SearchFilesResponse(BaseModel):
    query: str
    total: int
    items: list[SearchFileItem]
    next_cursor: str | None = None
