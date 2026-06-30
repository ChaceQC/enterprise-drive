from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import utc_now
from app.modules.file.models import FileVersion, Node
from app.modules.quota.models import QuotaAccount, QuotaLedger
from app.modules.space.models import Space


@dataclass(frozen=True)
class SpaceQuotaUsageSnapshot:
    space_id: UUID
    account_id: UUID | None
    limit_bytes: int | None
    used_bytes: int | None
    actual_bytes: int
    ledger_bytes: int


class QuotaRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_account(
        self,
        *,
        tenant_id: UUID,
        owner_type: str,
        owner_id: UUID,
    ) -> QuotaAccount | None:
        result = await self.session.execute(
            select(QuotaAccount).where(
                QuotaAccount.tenant_id == tenant_id,
                QuotaAccount.owner_type == owner_type,
                QuotaAccount.owner_id == owner_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_account(
        self,
        *,
        tenant_id: UUID,
        owner_type: str,
        owner_id: UUID,
        limit_bytes: int,
    ) -> QuotaAccount:
        account = QuotaAccount(
            tenant_id=tenant_id,
            owner_type=owner_type,
            owner_id=owner_id,
            limit_bytes=limit_bytes,
            used_bytes=0,
        )
        self.session.add(account)
        await self.session.flush()
        return account

    async def try_add_usage(
        self,
        *,
        tenant_id: UUID,
        owner_type: str,
        owner_id: UUID,
        delta_bytes: int,
    ) -> UUID | None:
        result = await self.session.execute(
            update(QuotaAccount)
            .where(
                QuotaAccount.tenant_id == tenant_id,
                QuotaAccount.owner_type == owner_type,
                QuotaAccount.owner_id == owner_id,
                QuotaAccount.used_bytes + delta_bytes <= QuotaAccount.limit_bytes,
            )
            .values(
                used_bytes=QuotaAccount.used_bytes + delta_bytes,
                updated_at=utc_now(),
            )
            .returning(QuotaAccount.id)
        )
        return result.scalar_one_or_none()

    async def subtract_usage(
        self,
        *,
        tenant_id: UUID,
        owner_type: str,
        owner_id: UUID,
        delta_bytes: int,
    ) -> UUID | None:
        result = await self.session.execute(
            update(QuotaAccount)
            .where(
                QuotaAccount.tenant_id == tenant_id,
                QuotaAccount.owner_type == owner_type,
                QuotaAccount.owner_id == owner_id,
                QuotaAccount.used_bytes >= delta_bytes,
            )
            .values(
                used_bytes=QuotaAccount.used_bytes - delta_bytes,
                updated_at=utc_now(),
            )
            .returning(QuotaAccount.id)
        )
        return result.scalar_one_or_none()

    async def add_ledger(
        self,
        *,
        tenant_id: UUID,
        account_id: UUID,
        account_type: str,
        delta_bytes: int,
        reason: str,
        ref_type: str,
        ref_id: UUID,
    ) -> QuotaLedger:
        ledger = QuotaLedger(
            tenant_id=tenant_id,
            account_id=account_id,
            account_type=account_type,
            delta_bytes=delta_bytes,
            reason=reason,
            ref_type=ref_type,
            ref_id=ref_id,
        )
        self.session.add(ledger)
        await self.session.flush()
        return ledger

    async def list_space_usage_snapshots(
        self,
        *,
        tenant_id: UUID,
        limit: int,
    ) -> list[SpaceQuotaUsageSnapshot]:
        actual_usage = (
            select(
                Node.space_id.label("space_id"),
                func.coalesce(func.sum(FileVersion.size_bytes), 0).label("actual_bytes"),
            )
            .join(
                FileVersion,
                and_(
                    FileVersion.tenant_id == Node.tenant_id,
                    FileVersion.node_id == Node.id,
                ),
            )
            .where(Node.tenant_id == tenant_id)
            .group_by(Node.space_id)
            .subquery()
        )
        ledger_usage = (
            select(
                QuotaLedger.account_id.label("account_id"),
                func.coalesce(func.sum(QuotaLedger.delta_bytes), 0).label("ledger_bytes"),
            )
            .where(QuotaLedger.tenant_id == tenant_id)
            .group_by(QuotaLedger.account_id)
            .subquery()
        )
        result = await self.session.execute(
            select(
                Space.id,
                QuotaAccount.id,
                QuotaAccount.limit_bytes,
                QuotaAccount.used_bytes,
                func.coalesce(actual_usage.c.actual_bytes, 0),
                func.coalesce(ledger_usage.c.ledger_bytes, 0),
            )
            .select_from(Space)
            .outerjoin(
                QuotaAccount,
                and_(
                    QuotaAccount.tenant_id == Space.tenant_id,
                    QuotaAccount.owner_type == "space",
                    QuotaAccount.owner_id == Space.id,
                ),
            )
            .outerjoin(actual_usage, actual_usage.c.space_id == Space.id)
            .outerjoin(ledger_usage, ledger_usage.c.account_id == QuotaAccount.id)
            .where(Space.tenant_id == tenant_id)
            .order_by(Space.created_at, Space.id)
            .limit(limit)
        )
        return [
            SpaceQuotaUsageSnapshot(
                space_id=row[0],
                account_id=row[1],
                limit_bytes=row[2],
                used_bytes=row[3],
                actual_bytes=int(row[4]),
                ledger_bytes=int(row[5]),
            )
            for row in result.all()
        ]

    async def set_account_used_bytes(
        self,
        *,
        tenant_id: UUID,
        account_id: UUID,
        used_bytes: int,
    ) -> bool:
        result = await self.session.execute(
            update(QuotaAccount)
            .where(
                QuotaAccount.tenant_id == tenant_id,
                QuotaAccount.id == account_id,
            )
            .values(
                used_bytes=used_bytes,
                updated_at=utc_now(),
            )
            .returning(QuotaAccount.id)
        )
        return result.scalar_one_or_none() is not None

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
