from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import and_, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import utc_now
from app.modules.file.models import FileVersion, Node
from app.modules.quota.models import QuotaAccount, QuotaLedger, QuotaPolicy
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

    async def ensure_account(
        self,
        *,
        tenant_id: UUID,
        owner_type: str,
        owner_id: UUID,
        limit_bytes: int,
    ) -> QuotaAccount:
        account = await self.get_account(
            tenant_id=tenant_id,
            owner_type=owner_type,
            owner_id=owner_id,
        )
        if account is not None:
            return account
        try:
            async with self.session.begin_nested():
                account = QuotaAccount(
                    tenant_id=tenant_id,
                    owner_type=owner_type,
                    owner_id=owner_id,
                    limit_bytes=limit_bytes,
                    used_bytes=0,
                )
                self.session.add(account)
                await self.session.flush()
        except IntegrityError:
            # 并发请求已经创建了同一维度账户，读取已提交的事实即可。
            account = None
        if account is None:
            account = await self.get_account(
                tenant_id=tenant_id,
                owner_type=owner_type,
                owner_id=owner_id,
            )
        if account is None:
            raise RuntimeError("quota account creation race did not resolve")
        return account

    async def list_active_policies(self, *, tenant_id: UUID) -> list[QuotaPolicy]:
        result = await self.session.execute(
            select(QuotaPolicy)
            .where(
                QuotaPolicy.tenant_id == tenant_id,
                QuotaPolicy.is_active.is_(True),
            )
            .order_by(QuotaPolicy.priority, QuotaPolicy.created_at, QuotaPolicy.id)
        )
        return list(result.scalars().all())

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

    async def subtract_usage_by_account_id(
        self,
        *,
        tenant_id: UUID,
        account_id: UUID,
        delta_bytes: int,
    ) -> UUID | None:
        result = await self.session.execute(
            update(QuotaAccount)
            .where(
                QuotaAccount.tenant_id == tenant_id,
                QuotaAccount.id == account_id,
                QuotaAccount.used_bytes >= delta_bytes,
            )
            .values(
                used_bytes=QuotaAccount.used_bytes - delta_bytes,
                updated_at=utc_now(),
            )
            .returning(QuotaAccount.id)
        )
        return result.scalar_one_or_none()

    async def list_ledger_entries_for_refs(
        self,
        *,
        tenant_id: UUID,
        ref_type: str,
        ref_ids: list[UUID],
    ) -> list[QuotaLedger]:
        if not ref_ids:
            return []
        result = await self.session.execute(
            select(QuotaLedger).where(
                QuotaLedger.tenant_id == tenant_id,
                QuotaLedger.ref_type == ref_type,
                QuotaLedger.ref_id.in_(ref_ids),
                QuotaLedger.delta_bytes > 0,
            )
        )
        return list(result.scalars().all())

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
            id=uuid4(),
            tenant_id=tenant_id,
            account_id=account_id,
            account_type=account_type,
            delta_bytes=delta_bytes,
            reason=reason,
            ref_type=ref_type,
            ref_id=ref_id,
        )
        self.session.add(ledger)
        return ledger

    async def get_account_by_id_for_update(
        self,
        *,
        tenant_id: UUID,
        account_id: UUID,
    ) -> QuotaAccount | None:
        result = await self.session.execute(
            select(QuotaAccount)
            .where(
                QuotaAccount.tenant_id == tenant_id,
                QuotaAccount.id == account_id,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def sum_space_actual_bytes(self, *, tenant_id: UUID, space_id: UUID) -> int:
        result = await self.session.execute(
            select(func.coalesce(func.sum(FileVersion.size_bytes), 0))
            .select_from(Node)
            .join(
                FileVersion,
                and_(
                    FileVersion.tenant_id == Node.tenant_id,
                    FileVersion.node_id == Node.id,
                ),
            )
            .where(
                Node.tenant_id == tenant_id,
                Node.space_id == space_id,
            )
        )
        return int(result.scalar_one())

    async def sum_account_ledger_bytes(
        self,
        *,
        tenant_id: UUID,
        account_id: UUID,
    ) -> int:
        result = await self.session.execute(
            select(func.coalesce(func.sum(QuotaLedger.delta_bytes), 0)).where(
                QuotaLedger.tenant_id == tenant_id,
                QuotaLedger.account_id == account_id,
            )
        )
        return int(result.scalar_one())

    async def list_space_usage_snapshots(
        self,
        *,
        tenant_id: UUID,
        limit: int,
        after_space_id: UUID | None = None,
    ) -> list[SpaceQuotaUsageSnapshot]:
        conditions = [Space.tenant_id == tenant_id]
        if after_space_id is not None:
            conditions.append(Space.id > after_space_id)

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
            .where(*conditions)
            .order_by(Space.id)
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
