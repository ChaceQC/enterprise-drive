from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

AdminSpaceType = Literal["team", "personal"]


class AdminSpaceResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    owner_id: UUID
    slug: str
    name: str
    space_type: AdminSpaceType
    is_active: bool
    version: int
    permission_version: int
    member_count: int
    node_count: int
    used_bytes: int
    limit_bytes: int
    created_at: datetime
    updated_at: datetime


class AdminSpaceListResponse(BaseModel):
    items: list[AdminSpaceResponse]
    next_cursor: str | None = None


class AdminSpaceCreateRequest(BaseModel):
    owner_id: UUID | None = None
    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=128)
    space_type: AdminSpaceType = "team"
    limit_bytes: int | None = Field(default=None, ge=0)


class AdminSpaceUpdateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    owner_id: UUID | None = None
    slug: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
    )
    name: str | None = Field(default=None, min_length=1, max_length=128)
    space_type: AdminSpaceType | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def ensure_change_requested(self) -> AdminSpaceUpdateRequest:
        if (
            self.owner_id is None
            and self.slug is None
            and self.name is None
            and self.space_type is None
            and self.is_active is None
        ):
            raise ValueError("至少提供一个空间变更字段")
        return self
