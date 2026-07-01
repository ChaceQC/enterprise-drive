from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ShareRecipientInput(BaseModel):
    subject_type: str
    subject_id: UUID


class CreateShareResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    share_type: str
    root_node_id: UUID
    permission: str
    status: str
    expires_at: datetime | None
    max_views: int | None
    max_downloads: int | None
    raw_token: str | None = None


class ShareDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    share_type: str
    root_node_id: UUID
    permission: str
    status: str
    expires_at: datetime | None
    max_views: int | None
    max_downloads: int | None
    view_count: int
    download_count: int
    revoked_at: datetime | None
    revoked_by: UUID | None
