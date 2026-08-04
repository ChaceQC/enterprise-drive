from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class DirectoryUserResponse(BaseModel):
    id: UUID
    username: str
    display_name: str


class DirectoryUserListResponse(BaseModel):
    items: list[DirectoryUserResponse]
    next_cursor: str | None = None


class DirectoryDepartmentResponse(BaseModel):
    id: UUID
    name: str
    path: str


class DirectoryDepartmentListResponse(BaseModel):
    items: list[DirectoryDepartmentResponse]
    next_cursor: str | None = None


class DirectoryGroupResponse(BaseModel):
    id: UUID
    slug: str
    name: str


class DirectoryGroupListResponse(BaseModel):
    items: list[DirectoryGroupResponse]
    next_cursor: str | None = None
