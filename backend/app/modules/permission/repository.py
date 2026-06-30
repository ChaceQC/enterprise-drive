from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import utc_now
from app.modules.permission.constants import SPACE_ROLE_OWNER, SPACE_ROLES
from app.modules.permission.models import SpaceMember
from app.modules.space.models import Space


class PermissionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_space_member(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        user_id: UUID,
        role: str,
        created_by: UUID | None,
    ) -> SpaceMember:
        if role not in SPACE_ROLES:
            raise ValueError(f"unsupported space role: {role}")
        member = SpaceMember(
            tenant_id=tenant_id,
            space_id=space_id,
            user_id=user_id,
            role=role,
            created_by=created_by,
        )
        self.session.add(member)
        await self.session.flush()
        return member

    async def get_space_member(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        user_id: UUID,
    ) -> SpaceMember | None:
        result = await self.session.execute(
            select(SpaceMember).where(
                SpaceMember.tenant_id == tenant_id,
                SpaceMember.space_id == space_id,
                SpaceMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_space_members(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
    ) -> list[SpaceMember]:
        result = await self.session.execute(
            select(SpaceMember)
            .where(
                SpaceMember.tenant_id == tenant_id,
                SpaceMember.space_id == space_id,
            )
            .order_by(SpaceMember.created_at, SpaceMember.id)
        )
        return list(result.scalars().all())

    async def get_space_member_for_update(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        user_id: UUID,
    ) -> SpaceMember | None:
        result = await self.session.execute(
            select(SpaceMember)
            .where(
                SpaceMember.tenant_id == tenant_id,
                SpaceMember.space_id == space_id,
                SpaceMember.user_id == user_id,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def count_space_owners(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
    ) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(SpaceMember)
            .where(
                SpaceMember.tenant_id == tenant_id,
                SpaceMember.space_id == space_id,
                SpaceMember.role == SPACE_ROLE_OWNER,
            )
        )
        return int(result.scalar_one())

    async def update_space_member_role(
        self,
        *,
        member: SpaceMember,
        role: str,
    ) -> SpaceMember:
        if role not in SPACE_ROLES:
            raise ValueError(f"unsupported space role: {role}")
        member.role = role
        member.updated_at = utc_now()
        await self.session.flush()
        return member

    async def delete_space_member(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        user_id: UUID,
    ) -> None:
        await self.session.execute(
            delete(SpaceMember).where(
                SpaceMember.tenant_id == tenant_id,
                SpaceMember.space_id == space_id,
                SpaceMember.user_id == user_id,
            )
        )
        await self.session.flush()

    async def bump_space_permission_version(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
    ) -> None:
        await self.session.execute(
            update(Space)
            .where(Space.tenant_id == tenant_id, Space.id == space_id)
            .values(
                permission_version=Space.permission_version + 1,
                updated_at=utc_now(),
            )
        )
        await self.session.flush()

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
