from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import utc_now
from app.modules.quota.models import QuotaAccount, QuotaLedger


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
