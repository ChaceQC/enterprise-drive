from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CreateSpaceRequest(BaseModel):
    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=128)
    space_type: Literal["team", "personal"] = "team"


class SpaceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    owner_id: UUID
    slug: str
    name: str
    space_type: str
    is_active: bool
    permission_version: int
    created_at: datetime
    updated_at: datetime


class CreateSpaceResponse(SpaceResponse):
    root_node_id: UUID


class SpaceListResponse(BaseModel):
    items: list[SpaceResponse]
    next_cursor: str | None = None
