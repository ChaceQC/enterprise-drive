from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ShareType = Literal["internal", "external"]
SharePermission = Literal["preview", "download"]
ShareRecipientType = Literal["user", "department", "group"]


class ShareRecipientInput(BaseModel):
    subject_type: ShareRecipientType
    subject_id: UUID


class CreateShareRequest(BaseModel):
    share_type: ShareType
    root_node_id: UUID
    permission: SharePermission = "download"
    item_node_ids: list[UUID] = Field(default_factory=list)
    recipients: list[ShareRecipientInput] = Field(default_factory=list)
    passcode: str | None = Field(default=None, min_length=1, max_length=128)
    expires_at: datetime | None = None
    max_views: int | None = Field(default=None, gt=0)
    max_downloads: int | None = Field(default=None, gt=0)


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


class CreateShareResponse(CreateShareResult):
    pass


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


class RevokeShareResponse(BaseModel):
    share_id: UUID
    revoked: Literal[True] = True


class ExternalShareAccessRequest(BaseModel):
    tenant_slug: str = Field(min_length=1, max_length=64)
    raw_token: str = Field(min_length=32, max_length=256)
    passcode: str | None = Field(default=None, min_length=1, max_length=128)


class ExternalShareAccessResponse(BaseModel):
    share_id: UUID
    root_node_id: UUID
    permission: str
    expires_at: datetime | None
    max_views: int | None
    max_downloads: int | None
    view_count: int
    download_count: int
    item_node_ids: list[UUID]


class ExternalShareDownloadRequest(BaseModel):
    tenant_slug: str = Field(min_length=1, max_length=64)
    raw_token: str = Field(min_length=32, max_length=256)
    node_id: UUID
    passcode: str | None = Field(default=None, min_length=1, max_length=128)


class ExternalShareDownloadResponse(BaseModel):
    share_id: UUID
    node_id: UUID
    version_id: UUID
    file_name: str
    size_bytes: int
    mime_type: str | None
    download_url: str
    expires_at: datetime
    headers: dict[str, str]
    download_count: int
