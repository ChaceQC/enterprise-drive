from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

SpaceMemberRole = Literal["owner", "admin", "editor", "viewer"]
AclSubjectType = Literal["user", "department", "group"]
AclEffect = Literal["allow", "deny"]
AclAction = Literal[
    "delete",
    "download",
    "grant",
    "list",
    "manage",
    "preview",
    "read_meta",
    "restore",
    "share",
    "update",
    "upload",
]


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


class AclEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    node_id: UUID
    subject_type: str
    subject_id: UUID
    effect: str
    actions: list[str]
    inherit: bool
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class AclEntryListResponse(BaseModel):
    items: list[AclEntryResponse]


class CreateAclEntryRequest(BaseModel):
    subject_type: AclSubjectType
    subject_id: UUID
    effect: AclEffect
    actions: list[AclAction] = Field(min_length=1)
    inherit: bool = True


class UpdateAclEntryRequest(BaseModel):
    effect: AclEffect
    actions: list[AclAction] = Field(min_length=1)
    inherit: bool = True


class RemoveAclEntryResponse(BaseModel):
    entry_id: UUID
    removed: bool
