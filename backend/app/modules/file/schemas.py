from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.transfer_protocol import DriveTransferProtocolResponse


class CreateFolderRequest(BaseModel):
    space_id: UUID
    parent_id: UUID | None = None
    name: str = Field(min_length=1, max_length=255)


class RenameNodeRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class MoveNodeRequest(BaseModel):
    target_parent_id: UUID
    new_name: str | None = Field(default=None, min_length=1, max_length=255)


class RestoreNodeRequest(BaseModel):
    target_parent_id: UUID | None = None
    new_name: str | None = Field(default=None, min_length=1, max_length=255)


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
    permissions: dict[str, bool] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class FileListResponse(BaseModel):
    space_id: UUID
    parent_id: UUID
    items: list[FileNodeResponse]
    next_cursor: str | None = None


class DeleteNodeResponse(BaseModel):
    node_id: UUID
    deleted_count: int


class PurgeNodeResponse(BaseModel):
    node_id: UUID
    purged_count: int
    released_bytes: int


class FileDownloadUrlResponse(DriveTransferProtocolResponse):
    node_id: UUID
    version_id: UUID
    file_name: str
    size_bytes: int
    mime_type: str | None
    download_url: str
    expires_at: datetime
    headers: dict[str, str]


class FileVersionResponse(BaseModel):
    id: UUID
    node_id: UUID
    version_no: int
    size_bytes: int
    mime_type: str | None
    created_by: UUID
    created_at: datetime
    is_current: bool


class FileVersionListResponse(BaseModel):
    node_id: UUID
    current_version_id: UUID | None
    items: list[FileVersionResponse]
    next_cursor: str | None = None


class FileVersionRollbackRequest(BaseModel):
    expected_current_version_id: UUID | None = None


class FileVersionRollbackResponse(BaseModel):
    node_id: UUID
    source_version_id: UUID
    new_version_id: UUID
    version_no: int
    current_version_id: UUID
