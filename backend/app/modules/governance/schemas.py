from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

GovernanceOperationStatus = Literal["pending", "running", "completed", "failed"]
PermissionRebuildScope = Literal["space", "node"]


class GovernanceOverviewResponse(BaseModel):
    generated_at: datetime
    permission_rebuild_pending: int
    permission_rebuild_running: int
    permission_rebuild_completed: int
    permission_rebuild_failed: int
    tree_operations_pending: int
    tree_operations_running: int
    tree_operations_completed: int
    tree_operations_failed: int
    lifecycle_runs_pending: int
    lifecycle_runs_failed: int
    maintenance_alerts: int
    maintenance_stale: int


class LifecyclePolicyResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    trash_retention_days: int
    preview_retention_days: int
    expire_uploads: bool
    expire_shares: bool
    cleanup_unreferenced_blobs: bool
    cleanup_orphaned_objects: bool
    version: int
    updated_by: UUID
    created_at: datetime
    updated_at: datetime


class LifecyclePolicyUpdateRequest(BaseModel):
    trash_retention_days: int = Field(ge=1, le=3650)
    preview_retention_days: int = Field(ge=1, le=3650)
    expire_uploads: bool = True
    expire_shares: bool = True
    cleanup_unreferenced_blobs: bool = True
    cleanup_orphaned_objects: bool = False
    expected_version: int = Field(ge=1)


class LifecycleRunCreateRequest(BaseModel):
    dry_run: bool = True
    limit: int = Field(default=100, ge=1, le=10_000)


class LifecycleRunResponse(BaseModel):
    id: UUID
    status: Literal["pending", "running", "succeeded", "failed"]
    dry_run: bool
    policy_version: int
    result: dict[str, object]
    error_code: str | None
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class LifecycleRunListResponse(BaseModel):
    items: list[LifecycleRunResponse]
    next_cursor: str | None = None


class PermissionRebuildCreateRequest(BaseModel):
    scope: PermissionRebuildScope
    space_id: UUID
    root_node_id: UUID | None = None


class PermissionRebuildOperationResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    space_id: UUID
    root_node_id: UUID | None
    scope: PermissionRebuildScope
    permission_version: int
    status: GovernanceOperationStatus
    total_count: int
    processed_count: int
    indexed_count: int
    attempt_count: int
    restart_requested: bool
    error_code: str | None
    requested_by: UUID | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class PermissionRebuildOperationListResponse(BaseModel):
    items: list[PermissionRebuildOperationResponse]
    next_cursor: str | None = None


class AdminTreeOperationResponse(BaseModel):
    id: UUID
    user_id: UUID
    space_id: UUID
    node_id: UUID
    operation: Literal["delete", "restore", "purge"]
    status: GovernanceOperationStatus
    total_count: int
    processed_count: int
    released_bytes: int
    attempt_count: int
    error_code: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class AdminTreeOperationListResponse(BaseModel):
    items: list[AdminTreeOperationResponse]
    next_cursor: str | None = None
