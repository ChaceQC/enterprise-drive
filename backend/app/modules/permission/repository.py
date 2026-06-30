from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.permission.constants import SPACE_ROLES
from app.modules.permission.models import SpaceMember


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
