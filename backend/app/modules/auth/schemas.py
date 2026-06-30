from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=255)
    tenant_slug: str = Field(default="default", min_length=1, max_length=64)


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
