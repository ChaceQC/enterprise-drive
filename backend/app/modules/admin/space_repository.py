from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import ColumnElement

from app.core.pagination import PageCursor
from app.modules.auth.models import User
from app.modules.file.models import Node
from app.modules.permission.models import SpaceMember
from app.modules.quota.models import QuotaAccount
from app.modules.space.models import Space


@dataclass(frozen=True, slots=True)
class AdminSpaceRecord:
    space: Space
    member_count: int
    node_count: int
    used_bytes: int
    limit_bytes: int


class AdminSpaceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_spaces(
        self,
        *,
        tenant_id: UUID,
        is_active: bool | None,
        space_type: str | None,
        owner_id: UUID | None,
        query: str | None,
        cursor: PageCursor | None,
        limit: int,
    ) -> list[AdminSpaceRecord]:
        conditions = [Space.tenant_id == tenant_id]
        if is_active is not None:
            conditions.append(Space.is_active.is_(is_active))
        if space_type is not None:
            conditions.append(Space.space_type == space_type)
        if owner_id is not None:
            conditions.append(Space.owner_id == owner_id)
        if query is not None:
            pattern = f"%{_escape_like(query.casefold())}%"
            conditions.append(
                or_(
                    func.lower(Space.slug).like(pattern, escape="\\"),
                    func.lower(Space.name).like(pattern, escape="\\"),
                )
            )
        if cursor is not None:
            conditions.append(_before_cursor(Space.created_at, Space.id, cursor))
        result = await self.session.execute(
            _space_records_query(tenant_id=tenant_id)
            .where(*conditions)
            .order_by(Space.created_at.desc(), Space.id.desc())
            .limit(limit)
        )
        return [_record(row) for row in result.all()]

    async def get_space_record(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
    ) -> AdminSpaceRecord | None:
        result = await self.session.execute(
            _space_records_query(tenant_id=tenant_id).where(
                Space.tenant_id == tenant_id,
                Space.id == space_id,
            )
        )
        row = result.one_or_none()
        return _record(row) if row is not None else None

    async def get_space_for_update(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
    ) -> Space | None:
        result = await self.session.execute(
            select(Space)
            .where(Space.tenant_id == tenant_id, Space.id == space_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_active_user(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
    ) -> User | None:
        result = await self.session.execute(
            select(User).where(
                User.tenant_id == tenant_id,
                User.id == user_id,
                User.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()


def _space_records_query(
    *,
    tenant_id: UUID,
) -> Select[tuple[Space, int, int, int, int]]:
    member_counts = (
        select(
            SpaceMember.space_id.label("space_id"),
            func.count(SpaceMember.id).label("member_count"),
        )
        .where(SpaceMember.tenant_id == tenant_id)
        .group_by(SpaceMember.space_id)
        .subquery()
    )
    node_counts = (
        select(
            Node.space_id.label("space_id"),
            func.count(Node.id).label("node_count"),
        )
        .where(Node.tenant_id == tenant_id)
        .group_by(Node.space_id)
        .subquery()
    )
    return (
        select(
            Space,
            func.coalesce(member_counts.c.member_count, 0),
            func.coalesce(node_counts.c.node_count, 0),
            func.coalesce(QuotaAccount.used_bytes, 0),
            func.coalesce(QuotaAccount.limit_bytes, 0),
        )
        .outerjoin(member_counts, member_counts.c.space_id == Space.id)
        .outerjoin(node_counts, node_counts.c.space_id == Space.id)
        .outerjoin(
            QuotaAccount,
            and_(
                QuotaAccount.tenant_id == Space.tenant_id,
                QuotaAccount.owner_type == "space",
                QuotaAccount.owner_id == Space.id,
            ),
        )
    )


def _record(row: Row[tuple[Space, int, int, int, int]]) -> AdminSpaceRecord:
    values = row._tuple()
    return AdminSpaceRecord(
        space=values[0],
        member_count=int(values[1]),
        node_count=int(values[2]),
        used_bytes=int(values[3]),
        limit_bytes=int(values[4]),
    )


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


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
