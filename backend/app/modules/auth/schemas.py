from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=255)
    tenant_slug: str = Field(default="default", min_length=1, max_length=64)


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=32)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_expires_at: datetime


class UserProfileResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    username: str
    email: str | None
    display_name: str
    is_super_admin: bool
    must_change_password: bool
