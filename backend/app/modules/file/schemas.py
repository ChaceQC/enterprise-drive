from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CreateFolderRequest(BaseModel):
    space_id: UUID
    parent_id: UUID | None = None
    name: str = Field(min_length=1, max_length=255)


class FileNodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    space_id: UUID
    parent_id: UUID | None
    node_type: str
    name: str
    current_version_id: UUID | None
    permission_version: int
    created_at: datetime
    updated_at: datetime


class FileListResponse(BaseModel):
    space_id: UUID
    parent_id: UUID
    items: list[FileNodeResponse]
    next_cursor: str | None = None
