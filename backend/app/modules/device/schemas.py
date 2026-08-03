from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.auth.schemas import UserProfileResponse

DesktopPlatform = Literal["windows", "macos", "linux"]


class DeviceRegisterRequest(BaseModel):
    tenant_slug: str = Field(default="default", min_length=1, max_length=64)
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=255)
    installation_id: UUID
    device_name: str = Field(min_length=1, max_length=128)
    platform: DesktopPlatform
    client_version: str = Field(min_length=1, max_length=32)


class DeviceRotateRequest(BaseModel):
    client_version: str | None = Field(default=None, min_length=1, max_length=32)


class DeviceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    platform: str
    client_version: str
    status: str
    current: bool = False
    last_seen_at: datetime
    revoked_at: datetime | None
    revoked_reason: str | None
    created_at: datetime


class DeviceSessionResponse(BaseModel):
    token_type: Literal["Device"] = "Device"
    access_token: str
    expires_at: datetime
    device: DeviceResponse
    user: UserProfileResponse


class DeviceListResponse(BaseModel):
    items: list[DeviceResponse]


class DeviceRevokeResponse(BaseModel):
    revoked_device_ids: list[UUID]
