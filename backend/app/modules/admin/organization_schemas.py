from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

OrganizationStatus = Literal["active", "disabled"]


class AdminUserResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    username: str
    email: str | None
    display_name: str
    is_active: bool
    is_super_admin: bool
    must_change_password: bool
    failed_login_attempts: int
    locked_until: datetime | None
    locked: bool
    version: int
    created_at: datetime
    updated_at: datetime


class AdminUserListResponse(BaseModel):
    items: list[AdminUserResponse]
    next_cursor: str | None = None


class AdminUserCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    email: str | None = Field(default=None, max_length=255)
    display_name: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=12, max_length=255)
    is_active: bool = True
    is_super_admin: bool = False
    must_change_password: bool = True


class AdminUserUpdateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    username: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$",
    )
    email: str | None = Field(default=None, max_length=255)
    clear_email: bool = False
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    is_active: bool | None = None
    is_super_admin: bool | None = None
    must_change_password: bool | None = None

    @model_validator(mode="after")
    def ensure_change_requested(self) -> AdminUserUpdateRequest:
        if self.clear_email and self.email is not None:
            raise ValueError("email 与 clear_email 不能同时提供")
        if (
            self.username is None
            and self.email is None
            and not self.clear_email
            and self.display_name is None
            and self.is_active is None
            and self.is_super_admin is None
            and self.must_change_password is None
        ):
            raise ValueError("至少提供一个用户变更字段")
        return self


class AdminUserPasswordResetRequest(BaseModel):
    expected_version: int = Field(ge=1)
    new_password: str = Field(min_length=1, max_length=255)


class AdminUserUnlockRequest(BaseModel):
    expected_version: int = Field(ge=1)


class AdminDepartmentResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    parent_id: UUID | None
    name: str
    path: str
    sort_order: int
    status: OrganizationStatus
    version: int
    created_at: datetime
    updated_at: datetime


class AdminDepartmentListResponse(BaseModel):
    items: list[AdminDepartmentResponse]
    next_cursor: str | None = None


class AdminDepartmentCreateRequest(BaseModel):
    parent_id: UUID | None = None
    name: str = Field(min_length=1, max_length=255)
    sort_order: int = Field(default=0, ge=-1_000_000, le=1_000_000)


class AdminDepartmentUpdateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    parent_id: UUID | None = None
    move_to_root: bool = False
    name: str | None = Field(default=None, min_length=1, max_length=255)
    sort_order: int | None = Field(default=None, ge=-1_000_000, le=1_000_000)
    status: OrganizationStatus | None = None

    @model_validator(mode="after")
    def ensure_change_requested(self) -> AdminDepartmentUpdateRequest:
        if self.parent_id is not None and self.move_to_root:
            raise ValueError("parent_id 与 move_to_root 不能同时提供")
        if (
            self.parent_id is None
            and not self.move_to_root
            and self.name is None
            and self.sort_order is None
            and self.status is None
        ):
            raise ValueError("至少提供一个部门变更字段")
        return self


class AdminGroupResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    slug: str
    name: str
    status: OrganizationStatus
    version: int
    created_at: datetime
    updated_at: datetime


class AdminGroupListResponse(BaseModel):
    items: list[AdminGroupResponse]
    next_cursor: str | None = None


class AdminGroupCreateRequest(BaseModel):
    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=255)


class AdminGroupUpdateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    slug: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
    )
    name: str | None = Field(default=None, min_length=1, max_length=255)
    status: OrganizationStatus | None = None

    @model_validator(mode="after")
    def ensure_change_requested(self) -> AdminGroupUpdateRequest:
        if self.slug is None and self.name is None and self.status is None:
            raise ValueError("至少提供一个用户组变更字段")
        return self


class AdminOrganizationMemberRequest(BaseModel):
    user_id: UUID
    expected_version: int = Field(ge=1)


class AdminOrganizationMemberResponse(BaseModel):
    id: UUID
    user: AdminUserResponse
    created_at: datetime
    organization_version: int


class AdminOrganizationMemberListResponse(BaseModel):
    items: list[AdminOrganizationMemberResponse]
    next_cursor: str | None = None
    organization_version: int


class AdminOrganizationMemberRemovalResponse(BaseModel):
    user_id: UUID
    removed: Literal[True] = True
    organization_version: int
