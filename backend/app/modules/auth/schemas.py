from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=255)
    tenant_slug: str = Field(default="default", min_length=1, max_length=64)
    captcha_token: str | None = Field(default=None, min_length=1, max_length=4096)


class UserProfileResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    username: str
    email: str | None
    display_name: str
    is_super_admin: bool
    must_change_password: bool


class SessionResponse(BaseModel):
    authenticated: Literal[True] = True
    expires_at: datetime
    user: UserProfileResponse


class LogoutResponse(BaseModel):
    authenticated: Literal[False] = False


class PasswordPolicyResponse(BaseModel):
    min_length: int
    max_length: int = 255
    require_uppercase: bool
    require_lowercase: bool
    require_digit: bool
    require_special: bool


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=255)
    new_password: str = Field(min_length=1, max_length=255)


class PasswordChangeResponse(BaseModel):
    changed: Literal[True] = True
    reauthentication_required: Literal[True] = True


class BrowserSessionResponse(BaseModel):
    id: UUID
    family_id: UUID
    auth_method: str
    oidc_provider_id: UUID | None
    ip: str | None
    user_agent: str | None
    current: bool
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime


class BrowserSessionListResponse(BaseModel):
    items: list[BrowserSessionResponse]


class BrowserSessionRevokeResponse(BaseModel):
    revoked_session_id: UUID
    current_session_revoked: bool
