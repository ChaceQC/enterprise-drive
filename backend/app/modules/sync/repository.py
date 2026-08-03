from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.sync.models import SyncChange


class SyncRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def max_sequence(self, *, tenant_id: UUID, space_id: UUID) -> int:
        result = await self.session.execute(
            select(func.max(SyncChange.sequence)).where(
                SyncChange.tenant_id == tenant_id,
                or_(SyncChange.space_id == space_id, SyncChange.space_id.is_(None)),
            )
        )
        return int(result.scalar_one_or_none() or 0)

    async def list_changes_after(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        sequence: int,
        limit: int,
    ) -> list[SyncChange]:
        result = await self.session.execute(
            select(SyncChange)
            .where(
                SyncChange.tenant_id == tenant_id,
                or_(SyncChange.space_id == space_id, SyncChange.space_id.is_(None)),
                SyncChange.sequence > sequence,
            )
            .order_by(SyncChange.sequence)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def has_changes_after(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        sequence: int,
    ) -> bool:
        result = await self.session.execute(
            select(SyncChange.sequence)
            .where(
                SyncChange.tenant_id == tenant_id,
                or_(SyncChange.space_id == space_id, SyncChange.space_id.is_(None)),
                SyncChange.sequence > sequence,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None
