from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from app.core.pagination import PageCursor
from app.core.security import utc_now
from app.modules.auth.models import AuthSession, Tenant, User
from app.modules.org.models import Department, DepartmentMember, UserGroup, UserGroupMember


class AdminOrganizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_users(
        self,
        *,
        tenant_id: UUID,
        is_active: bool | None,
        is_super_admin: bool | None,
        query: str | None,
        cursor: PageCursor | None,
        limit: int,
    ) -> list[User]:
        conditions = [User.tenant_id == tenant_id]
        if is_active is not None:
            conditions.append(User.is_active.is_(is_active))
        if is_super_admin is not None:
            conditions.append(User.is_super_admin.is_(is_super_admin))
        if query is not None:
            pattern = _contains_pattern(query)
            conditions.append(
                or_(
                    func.lower(User.username).like(pattern, escape="\\"),
                    func.lower(User.email).like(pattern, escape="\\"),
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

    async def get_user(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
    ) -> User | None:
        result = await self.session.execute(
            select(User).where(User.tenant_id == tenant_id, User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_user_for_update(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
    ) -> User | None:
        result = await self.session.execute(
            select(User).where(User.tenant_id == tenant_id, User.id == user_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def create_user(
        self,
        *,
        tenant_id: UUID,
        username: str,
        email: str | None,
        display_name: str,
        password_hash: str,
        is_active: bool,
        is_super_admin: bool,
        must_change_password: bool,
    ) -> User:
        user = User(
            tenant_id=tenant_id,
            username=username,
            email=email,
            display_name=display_name,
            password_hash=password_hash,
            is_active=is_active,
            is_super_admin=is_super_admin,
            must_change_password=must_change_password,
        )
        self.session.add(user)
        await self.session.flush()
        return user

    async def count_active_super_admins(self, *, tenant_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(User)
            .where(
                User.tenant_id == tenant_id,
                User.is_active.is_(True),
                User.is_super_admin.is_(True),
            )
        )
        return int(result.scalar_one())

    async def lock_tenant_for_update(self, *, tenant_id: UUID) -> None:
        result = await self.session.execute(
            select(Tenant.id).where(Tenant.id == tenant_id).with_for_update()
        )
        result.scalar_one()

    async def revoke_user_sessions(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        reason: str,
    ) -> None:
        now = utc_now()
        await self.session.execute(
            update(AuthSession)
            .where(
                AuthSession.tenant_id == tenant_id,
                AuthSession.user_id == user_id,
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=now, revoked_reason=reason)
        )

    async def list_departments(
        self,
        *,
        tenant_id: UUID,
        status: str | None,
        parent_id: UUID | None,
        root_only: bool,
        query: str | None,
        cursor: PageCursor | None,
        limit: int,
    ) -> list[Department]:
        conditions = [Department.tenant_id == tenant_id]
        if status is not None:
            conditions.append(Department.status == status)
        if parent_id is not None:
            conditions.append(Department.parent_id == parent_id)
        elif root_only:
            conditions.append(Department.parent_id.is_(None))
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

    async def get_department(
        self,
        *,
        tenant_id: UUID,
        department_id: UUID,
    ) -> Department | None:
        result = await self.session.execute(
            select(Department).where(
                Department.tenant_id == tenant_id,
                Department.id == department_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_department_for_update(
        self,
        *,
        tenant_id: UUID,
        department_id: UUID,
    ) -> Department | None:
        result = await self.session.execute(
            select(Department)
            .where(
                Department.tenant_id == tenant_id,
                Department.id == department_id,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def create_department(
        self,
        *,
        tenant_id: UUID,
        parent_id: UUID | None,
        name: str,
        path: str,
        sort_order: int,
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

    async def list_department_subtree_for_update(
        self,
        *,
        tenant_id: UUID,
        root_path: str,
    ) -> list[Department]:
        escaped_path = _escape_like(root_path)
        result = await self.session.execute(
            select(Department)
            .where(
                Department.tenant_id == tenant_id,
                or_(
                    Department.path == root_path,
                    Department.path.like(f"{escaped_path}/%", escape="\\"),
                ),
            )
            .order_by(Department.path, Department.id)
            .with_for_update()
        )
        return list(result.scalars().all())

    async def count_active_department_children(
        self,
        *,
        tenant_id: UUID,
        department_id: UUID,
    ) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(Department)
            .where(
                Department.tenant_id == tenant_id,
                Department.parent_id == department_id,
                Department.status == "active",
            )
        )
        return int(result.scalar_one())

    async def list_department_members(
        self,
        *,
        tenant_id: UUID,
        department_id: UUID,
        is_active: bool | None,
        query: str | None,
        cursor: PageCursor | None,
        limit: int,
    ) -> list[tuple[DepartmentMember, User]]:
        conditions = [
            DepartmentMember.tenant_id == tenant_id,
            DepartmentMember.department_id == department_id,
            User.tenant_id == tenant_id,
        ]
        if is_active is not None:
            conditions.append(User.is_active.is_(is_active))
        if query is not None:
            pattern = _contains_pattern(query)
            conditions.append(
                or_(
                    func.lower(User.username).like(pattern, escape="\\"),
                    func.lower(User.email).like(pattern, escape="\\"),
                    func.lower(User.display_name).like(pattern, escape="\\"),
                )
            )
        if cursor is not None:
            conditions.append(
                _before_cursor(DepartmentMember.created_at, DepartmentMember.id, cursor)
            )
        result = await self.session.execute(
            select(DepartmentMember, User)
            .join(
                User,
                (User.id == DepartmentMember.user_id)
                & (User.tenant_id == DepartmentMember.tenant_id),
            )
            .where(*conditions)
            .order_by(DepartmentMember.created_at.desc(), DepartmentMember.id.desc())
            .limit(limit)
        )
        return [(row[0], row[1]) for row in result.all()]

    async def get_department_member(
        self,
        *,
        tenant_id: UUID,
        department_id: UUID,
        user_id: UUID,
    ) -> DepartmentMember | None:
        result = await self.session.execute(
            select(DepartmentMember).where(
                DepartmentMember.tenant_id == tenant_id,
                DepartmentMember.department_id == department_id,
                DepartmentMember.user_id == user_id,
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

    async def remove_department_member(
        self,
        *,
        tenant_id: UUID,
        department_id: UUID,
        user_id: UUID,
    ) -> None:
        await self.session.execute(
            delete(DepartmentMember).where(
                DepartmentMember.tenant_id == tenant_id,
                DepartmentMember.department_id == department_id,
                DepartmentMember.user_id == user_id,
            )
        )
        await self.session.flush()

    async def list_groups(
        self,
        *,
        tenant_id: UUID,
        status: str | None,
        query: str | None,
        cursor: PageCursor | None,
        limit: int,
    ) -> list[UserGroup]:
        conditions = [UserGroup.tenant_id == tenant_id]
        if status is not None:
            conditions.append(UserGroup.status == status)
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

    async def get_group(
        self,
        *,
        tenant_id: UUID,
        group_id: UUID,
    ) -> UserGroup | None:
        result = await self.session.execute(
            select(UserGroup).where(
                UserGroup.tenant_id == tenant_id,
                UserGroup.id == group_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_group_for_update(
        self,
        *,
        tenant_id: UUID,
        group_id: UUID,
    ) -> UserGroup | None:
        result = await self.session.execute(
            select(UserGroup)
            .where(
                UserGroup.tenant_id == tenant_id,
                UserGroup.id == group_id,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def create_group(
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

    async def list_group_members(
        self,
        *,
        tenant_id: UUID,
        group_id: UUID,
        is_active: bool | None,
        query: str | None,
        cursor: PageCursor | None,
        limit: int,
    ) -> list[tuple[UserGroupMember, User]]:
        conditions = [
            UserGroupMember.tenant_id == tenant_id,
            UserGroupMember.group_id == group_id,
            User.tenant_id == tenant_id,
        ]
        if is_active is not None:
            conditions.append(User.is_active.is_(is_active))
        if query is not None:
            pattern = _contains_pattern(query)
            conditions.append(
                or_(
                    func.lower(User.username).like(pattern, escape="\\"),
                    func.lower(User.email).like(pattern, escape="\\"),
                    func.lower(User.display_name).like(pattern, escape="\\"),
                )
            )
        if cursor is not None:
            conditions.append(
                _before_cursor(UserGroupMember.created_at, UserGroupMember.id, cursor)
            )
        result = await self.session.execute(
            select(UserGroupMember, User)
            .join(
                User,
                (User.id == UserGroupMember.user_id)
                & (User.tenant_id == UserGroupMember.tenant_id),
            )
            .where(*conditions)
            .order_by(UserGroupMember.created_at.desc(), UserGroupMember.id.desc())
            .limit(limit)
        )
        return [(row[0], row[1]) for row in result.all()]

    async def get_group_member(
        self,
        *,
        tenant_id: UUID,
        group_id: UUID,
        user_id: UUID,
    ) -> UserGroupMember | None:
        result = await self.session.execute(
            select(UserGroupMember).where(
                UserGroupMember.tenant_id == tenant_id,
                UserGroupMember.group_id == group_id,
                UserGroupMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def add_group_member(
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

    async def remove_group_member(
        self,
        *,
        tenant_id: UUID,
        group_id: UUID,
        user_id: UUID,
    ) -> None:
        await self.session.execute(
            delete(UserGroupMember).where(
                UserGroupMember.tenant_id == tenant_id,
                UserGroupMember.group_id == group_id,
                UserGroupMember.user_id == user_id,
            )
        )
        await self.session.flush()

    async def bump_tenant_permission_version(self, *, tenant_id: UUID) -> int:
        await self.session.execute(
            update(Tenant)
            .where(Tenant.id == tenant_id)
            .values(
                permission_version=Tenant.permission_version + 1,
                updated_at=utc_now(),
            )
        )
        await self.session.flush()
        result = await self.session.execute(
            select(Tenant.permission_version).where(Tenant.id == tenant_id)
        )
        return int(result.scalar_one())

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()

    async def refresh_user(self, user: User) -> None:
        await self.session.refresh(user)


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
    return f"%{_escape_like(value.casefold())}%"


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
