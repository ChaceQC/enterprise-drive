from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.transfer_protocol import DriveTransferProtocolResponse

ConflictPolicy = Literal["fail", "keep_both", "replace"]
TreeOperationType = Literal["delete", "restore", "purge"]
TreeOperationStatus = Literal["pending", "running", "completed", "failed"]


class CreateFolderRequest(BaseModel):
    space_id: UUID
    parent_id: UUID | None = None
    name: str = Field(min_length=1, max_length=255)
    conflict_policy: ConflictPolicy = "fail"


class RenameNodeRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class MoveNodeRequest(BaseModel):
    target_parent_id: UUID
    new_name: str | None = Field(default=None, min_length=1, max_length=255)
    conflict_policy: ConflictPolicy = "fail"


class RestoreNodeRequest(BaseModel):
    target_parent_id: UUID | None = None
    new_name: str | None = Field(default=None, min_length=1, max_length=255)
    conflict_policy: ConflictPolicy = "fail"


class BatchDeleteRequest(BaseModel):
    node_ids: list[UUID] = Field(min_length=1, max_length=100)
    mode: Literal["trash"] = "trash"


class BatchMoveRequest(BaseModel):
    node_ids: list[UUID] = Field(min_length=1, max_length=100)
    target_parent_id: UUID
    new_name: str | None = Field(default=None, min_length=1, max_length=255)
    conflict_policy: ConflictPolicy = "fail"


class BatchRestoreRequest(BaseModel):
    node_ids: list[UUID] = Field(min_length=1, max_length=100)
    target_parent_id: UUID | None = None
    new_name: str | None = Field(default=None, min_length=1, max_length=255)
    conflict_policy: ConflictPolicy = "fail"


class BatchPurgeRequest(BaseModel):
    node_ids: list[UUID] = Field(min_length=1, max_length=100)


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


class TrashNodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    space_id: UUID
    parent_id: UUID | None
    node_type: str
    name: str
    current_version_id: UUID | None
    permission_version: int
    deleted_at: datetime
    deleted_by: UUID | None
    permissions: dict[str, bool] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class TrashListResponse(BaseModel):
    space_id: UUID
    items: list[TrashNodeResponse]
    next_cursor: str | None = None


class BatchNodeResult(BaseModel):
    node_id: UUID
    status: Literal["success", "failed"]
    code: str | None = None
    operation_id: UUID | None = None


class BatchOperationResponse(BaseModel):
    results: list[BatchNodeResult]


class FileTreeOperationResponse(BaseModel):
    operation_id: UUID
    node_id: UUID
    operation: TreeOperationType
    status: TreeOperationStatus
    total_count: int
    processed_count: int
    released_bytes: int
    error_code: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


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
