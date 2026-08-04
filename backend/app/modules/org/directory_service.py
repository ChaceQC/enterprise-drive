from __future__ import annotations

from uuid import UUID

from app.core.config import Settings
from app.core.pagination import decode_page_cursor, encode_page_cursor
from app.modules.auth.models import User
from app.modules.org.directory_schemas import (
    DirectoryDepartmentListResponse,
    DirectoryDepartmentResponse,
    DirectoryGroupListResponse,
    DirectoryGroupResponse,
    DirectoryUserListResponse,
    DirectoryUserResponse,
)
from app.modules.org.models import Department, UserGroup
from app.modules.org.repository import OrgRepository


class DirectoryService:
    def __init__(
        self,
        *,
        repository: OrgRepository,
        settings: Settings,
    ) -> None:
        self.repository = repository
        self.settings = settings

    async def list_users(
        self,
        *,
        tenant_id: UUID,
        query: str | None,
        cursor: str | None,
        page_size: int,
    ) -> DirectoryUserListResponse:
        users = await self.repository.list_active_users(
            tenant_id=tenant_id,
            query=_normalize_query(query),
            cursor=decode_page_cursor(self.settings, cursor),
            limit=page_size + 1,
        )
        page = users[:page_size]
        return DirectoryUserListResponse(
            items=[
                DirectoryUserResponse(
                    id=user.id,
                    username=user.username,
                    display_name=user.display_name,
                )
                for user in page
            ],
            next_cursor=_next_cursor(self.settings, users, page_size),
        )

    async def list_departments(
        self,
        *,
        tenant_id: UUID,
        query: str | None,
        cursor: str | None,
        page_size: int,
    ) -> DirectoryDepartmentListResponse:
        departments = await self.repository.list_active_departments(
            tenant_id=tenant_id,
            query=_normalize_query(query),
            cursor=decode_page_cursor(self.settings, cursor),
            limit=page_size + 1,
        )
        page = departments[:page_size]
        return DirectoryDepartmentListResponse(
            items=[
                DirectoryDepartmentResponse(
                    id=department.id,
                    name=department.name,
                    path=department.path,
                )
                for department in page
            ],
            next_cursor=_next_cursor(self.settings, departments, page_size),
        )

    async def list_groups(
        self,
        *,
        tenant_id: UUID,
        query: str | None,
        cursor: str | None,
        page_size: int,
    ) -> DirectoryGroupListResponse:
        groups = await self.repository.list_active_groups(
            tenant_id=tenant_id,
            query=_normalize_query(query),
            cursor=decode_page_cursor(self.settings, cursor),
            limit=page_size + 1,
        )
        page = groups[:page_size]
        return DirectoryGroupListResponse(
            items=[
                DirectoryGroupResponse(
                    id=group.id,
                    slug=group.slug,
                    name=group.name,
                )
                for group in page
            ],
            next_cursor=_next_cursor(self.settings, groups, page_size),
        )


def _normalize_query(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().casefold()
    return normalized or None


def _next_cursor(
    settings: Settings,
    items: list[User] | list[Department] | list[UserGroup],
    page_size: int,
) -> str | None:
    if len(items) <= page_size:
        return None
    last = items[page_size - 1]
    return encode_page_cursor(
        settings,
        created_at=last.created_at,
        item_id=last.id,
    )
