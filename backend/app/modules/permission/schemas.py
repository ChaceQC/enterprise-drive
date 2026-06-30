from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

SpaceMemberRole = Literal["owner", "admin", "editor", "viewer"]


class SpaceMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    space_id: UUID
    user_id: UUID
    role: str
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime


class SpaceMemberListResponse(BaseModel):
    items: list[SpaceMemberResponse]


class AddSpaceMemberRequest(BaseModel):
    user_id: UUID
    role: SpaceMemberRole


class UpdateSpaceMemberRequest(BaseModel):
    role: SpaceMemberRole


class RemoveSpaceMemberResponse(BaseModel):
    user_id: UUID
    removed: bool
