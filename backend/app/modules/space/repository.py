from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import PageCursor
from app.modules.permission.models import SpaceMember
from app.modules.space.models import Space


class SpaceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_space(
        self,
        *,
        tenant_id: UUID,
        owner_id: UUID,
        slug: str,
        name: str,
        space_type: str,
    ) -> Space:
        space = Space(
            tenant_id=tenant_id,
            owner_id=owner_id,
            slug=slug,
            name=name,
            space_type=space_type,
        )
        self.session.add(space)
        await self.session.flush()
        return space

    async def get_space_by_slug(self, *, tenant_id: UUID, slug: str) -> Space | None:
        result = await self.session.execute(
            select(Space).where(Space.tenant_id == tenant_id, Space.slug == slug)
        )
        return result.scalar_one_or_none()

    async def get_active_space(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
    ) -> Space | None:
        result = await self.session.execute(
            select(Space).where(
                Space.tenant_id == tenant_id,
                Space.id == space_id,
                Space.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def list_member_active_spaces(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        limit: int,
        cursor: PageCursor | None,
    ) -> list[Space]:
        conditions = [
            Space.tenant_id == tenant_id,
            Space.is_active.is_(True),
            SpaceMember.tenant_id == tenant_id,
            SpaceMember.user_id == user_id,
            SpaceMember.space_id == Space.id,
        ]
        if cursor is not None:
            conditions.append(
                or_(
                    Space.created_at < cursor.created_at,
                    and_(Space.created_at == cursor.created_at, Space.id < cursor.item_id),
                )
            )

        result = await self.session.execute(
            select(Space)
            .join(SpaceMember, SpaceMember.space_id == Space.id)
            .where(*conditions)
            .order_by(Space.created_at.desc(), Space.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
