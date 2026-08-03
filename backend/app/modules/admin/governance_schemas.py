from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

AdminJobStatus = Literal["pending", "running", "succeeded", "failed", "expired"]
AdminMaintenanceOperation = Literal[
    "upload.expire_sessions",
    "file.cleanup_expired_trash",
    "share.expire_shares",
    "preview.cleanup_artifacts",
    "file.process_tree_operations",
    "file.cleanup_unreferenced_blobs",
    "file.cleanup_orphaned_objects",
    "quota.reconcile_space_usage",
    "admin.cleanup_expired_exports",
]
AdminExportResource = Literal["audit_logs", "spaces", "users"]


class AdminOverviewStatsResponse(BaseModel):
    generated_at: datetime
    users_total: int
    users_active: int
    spaces_total: int
    spaces_active: int
    nodes_total: int
    nodes_deleted: int
    file_versions_total: int
    stored_bytes: int
    quota_limit_bytes: int
    quota_used_bytes: int
    active_shares: int
    pending_uploads: int
    outbox_pending: int
    outbox_dead: int


class AdminMaintenanceTaskHealthResponse(BaseModel):
    task_name: AdminMaintenanceOperation
    expected_interval_seconds: int
    consecutive_failures: int
    alert_active: bool
    stale: bool
    last_status: str
    last_finished_at: datetime | None
    last_success_at: datetime | None
    last_failure_at: datetime | None


class AdminMaintenanceOverviewResponse(BaseModel):
    generated_at: datetime
    tasks: list[AdminMaintenanceTaskHealthResponse]


class AdminMaintenanceRunRequest(BaseModel):
    task_name: AdminMaintenanceOperation
    dry_run: bool = True
    repair: bool = False
    limit: int = Field(default=100, ge=1, le=10_000)
    retention_days: int | None = Field(default=None, ge=1, le=3650)
    scan_all: bool = True


class AdminJobResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    kind: Literal["maintenance", "export"]
    operation: str
    status: AdminJobStatus
    created_by: UUID
    parameters: dict[str, object]
    result: dict[str, object]
    file_name: str | None
    content_type: str | None
    size_bytes: int | None
    error_code: str | None
    error_message: str | None
    version: int
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class AdminJobListResponse(BaseModel):
    items: list[AdminJobResponse]
    next_cursor: str | None = None


class AdminExportCreateRequest(BaseModel):
    resource: AdminExportResource
    filters: dict[str, object] = Field(default_factory=dict)


class AdminExportDownloadResponse(BaseModel):
    job_id: UUID
    file_name: str
    content_type: str
    size_bytes: int
    download_url: str
    expires_at: datetime
