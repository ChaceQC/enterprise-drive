from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from app.core.pagination import PageCursor
from app.modules.auth.models import User
from app.modules.org.models import Department, DepartmentMember, UserGroup, UserGroupMember


class OrgRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_active_users(
        self,
        *,
        tenant_id: UUID,
        query: str | None,
        cursor: PageCursor | None,
        limit: int,
    ) -> list[User]:
        conditions: list[ColumnElement[bool]] = [
            User.tenant_id == tenant_id,
            User.is_active.is_(True),
        ]
        if query is not None:
            pattern = _contains_pattern(query)
            conditions.append(
                or_(
                    func.lower(User.username).like(pattern, escape="\\"),
                    func.lower(User.display_name).like(pattern, escape="\\"),
                )
            )
        if cursor is not None:
            conditions.append(_before_cursor(User.created_at, User.id, cursor))
        result = await self.session.execute(
            select(User)
            .where(*conditions)
            .order_by(User.created_at.desc(), User.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_active_departments(
        self,
        *,
        tenant_id: UUID,
        query: str | None,
        cursor: PageCursor | None,
        limit: int,
    ) -> list[Department]:
        conditions: list[ColumnElement[bool]] = [
            Department.tenant_id == tenant_id,
            Department.status == "active",
        ]
        if query is not None:
            conditions.append(
                func.lower(Department.name).like(_contains_pattern(query), escape="\\")
            )
        if cursor is not None:
            conditions.append(_before_cursor(Department.created_at, Department.id, cursor))
        result = await self.session.execute(
            select(Department)
            .where(*conditions)
            .order_by(Department.created_at.desc(), Department.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_active_groups(
        self,
        *,
        tenant_id: UUID,
        query: str | None,
        cursor: PageCursor | None,
        limit: int,
    ) -> list[UserGroup]:
        conditions: list[ColumnElement[bool]] = [
            UserGroup.tenant_id == tenant_id,
            UserGroup.status == "active",
        ]
        if query is not None:
            pattern = _contains_pattern(query)
            conditions.append(
                or_(
                    func.lower(UserGroup.slug).like(pattern, escape="\\"),
                    func.lower(UserGroup.name).like(pattern, escape="\\"),
                )
            )
        if cursor is not None:
            conditions.append(_before_cursor(UserGroup.created_at, UserGroup.id, cursor))
        result = await self.session.execute(
            select(UserGroup)
            .where(*conditions)
            .order_by(UserGroup.created_at.desc(), UserGroup.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def create_department(
        self,
        *,
        tenant_id: UUID,
        name: str,
        path: str,
        parent_id: UUID | None = None,
        sort_order: int = 0,
    ) -> Department:
        department = Department(
            tenant_id=tenant_id,
            parent_id=parent_id,
            name=name,
            path=path,
            sort_order=sort_order,
        )
        self.session.add(department)
        await self.session.flush()
        return department

    async def create_user_group(
        self,
        *,
        tenant_id: UUID,
        slug: str,
        name: str,
    ) -> UserGroup:
        group = UserGroup(
            tenant_id=tenant_id,
            slug=slug,
            name=name,
        )
        self.session.add(group)
        await self.session.flush()
        return group

    async def get_active_department(
        self,
        *,
        tenant_id: UUID,
        department_id: UUID,
    ) -> Department | None:
        result = await self.session.execute(
            select(Department).where(
                Department.tenant_id == tenant_id,
                Department.id == department_id,
                Department.status == "active",
            )
        )
        return result.scalar_one_or_none()

    async def get_active_user_group(
        self,
        *,
        tenant_id: UUID,
        group_id: UUID,
    ) -> UserGroup | None:
        result = await self.session.execute(
            select(UserGroup).where(
                UserGroup.tenant_id == tenant_id,
                UserGroup.id == group_id,
                UserGroup.status == "active",
            )
        )
        return result.scalar_one_or_none()

    async def add_department_member(
        self,
        *,
        tenant_id: UUID,
        department_id: UUID,
        user_id: UUID,
    ) -> DepartmentMember:
        member = DepartmentMember(
            tenant_id=tenant_id,
            department_id=department_id,
            user_id=user_id,
        )
        self.session.add(member)
        await self.session.flush()
        return member

    async def add_user_group_member(
        self,
        *,
        tenant_id: UUID,
        group_id: UUID,
        user_id: UUID,
    ) -> UserGroupMember:
        member = UserGroupMember(
            tenant_id=tenant_id,
            group_id=group_id,
            user_id=user_id,
        )
        self.session.add(member)
        await self.session.flush()
        return member

    async def list_user_department_ids(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
    ) -> list[UUID]:
        result = await self.session.execute(
            select(Department.id)
            .join(DepartmentMember, DepartmentMember.department_id == Department.id)
            .where(
                Department.tenant_id == tenant_id,
                Department.status == "active",
                DepartmentMember.tenant_id == tenant_id,
                DepartmentMember.user_id == user_id,
            )
            .order_by(Department.path, Department.id)
        )
        return list(result.scalars().all())

    async def list_user_group_ids(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
    ) -> list[UUID]:
        result = await self.session.execute(
            select(UserGroup.id)
            .join(UserGroupMember, UserGroupMember.group_id == UserGroup.id)
            .where(
                UserGroup.tenant_id == tenant_id,
                UserGroup.status == "active",
                UserGroupMember.tenant_id == tenant_id,
                UserGroupMember.user_id == user_id,
            )
            .order_by(UserGroup.slug, UserGroup.id)
        )
        return list(result.scalars().all())

    async def list_active_department_member_user_ids(
        self,
        *,
        tenant_id: UUID,
        department_id: UUID,
    ) -> list[UUID]:
        result = await self.session.execute(
            select(User.id)
            .join(DepartmentMember, DepartmentMember.user_id == User.id)
            .join(Department, Department.id == DepartmentMember.department_id)
            .where(
                User.tenant_id == tenant_id,
                User.is_active.is_(True),
                DepartmentMember.tenant_id == tenant_id,
                DepartmentMember.department_id == department_id,
                Department.tenant_id == tenant_id,
                Department.status == "active",
            )
            .order_by(User.id)
        )
        return list(result.scalars().all())

    async def list_active_group_member_user_ids(
        self,
        *,
        tenant_id: UUID,
        group_id: UUID,
    ) -> list[UUID]:
        result = await self.session.execute(
            select(User.id)
            .join(UserGroupMember, UserGroupMember.user_id == User.id)
            .join(UserGroup, UserGroup.id == UserGroupMember.group_id)
            .where(
                User.tenant_id == tenant_id,
                User.is_active.is_(True),
                UserGroupMember.tenant_id == tenant_id,
                UserGroupMember.group_id == group_id,
                UserGroup.tenant_id == tenant_id,
                UserGroup.status == "active",
            )
            .order_by(User.id)
        )
        return list(result.scalars().all())

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()


def _before_cursor(
    created_at_column: InstrumentedAttribute[datetime],
    id_column: InstrumentedAttribute[UUID],
    cursor: PageCursor,
) -> ColumnElement[bool]:
    return or_(
        created_at_column < cursor.created_at,
        and_(
            created_at_column == cursor.created_at,
            id_column < cursor.item_id,
        ),
    )


def _contains_pattern(value: str) -> str:
    escaped = value.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
