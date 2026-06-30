from __future__ import annotations

from uuid import UUID

from app.api.errors import ApiError
from app.modules.quota.models import QuotaAccount
from app.modules.quota.repository import QuotaRepository


class QuotaService:
    def __init__(
        self,
        *,
        repository: QuotaRepository,
        default_space_limit_bytes: int,
    ) -> None:
        self.repository = repository
        self.default_space_limit_bytes = default_space_limit_bytes

    async def ensure_space_account(self, *, tenant_id: UUID, space_id: UUID) -> QuotaAccount:
        account = await self.repository.get_account(
            tenant_id=tenant_id,
            owner_type="space",
            owner_id=space_id,
        )
        if account is not None:
            return account
        return await self.repository.create_account(
            tenant_id=tenant_id,
            owner_type="space",
            owner_id=space_id,
            limit_bytes=self.default_space_limit_bytes,
        )

    async def ensure_space_capacity(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        size_bytes: int,
    ) -> None:
        account = await self.ensure_space_account(tenant_id=tenant_id, space_id=space_id)
        if account.used_bytes + size_bytes > account.limit_bytes:
            raise quota_exceeded_error()

    async def reserve_file_version(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        version_id: UUID,
        size_bytes: int,
    ) -> None:
        await self.ensure_space_account(tenant_id=tenant_id, space_id=space_id)
        account_id = await self.repository.try_add_usage(
            tenant_id=tenant_id,
            owner_type="space",
            owner_id=space_id,
            delta_bytes=size_bytes,
        )
        if account_id is None:
            raise quota_exceeded_error()
        await self.repository.add_ledger(
            tenant_id=tenant_id,
            account_id=account_id,
            account_type="space",
            delta_bytes=size_bytes,
            reason="file_version_created",
            ref_type="file_version",
            ref_id=version_id,
        )


def quota_exceeded_error() -> ApiError:
    return ApiError("QUOTA_EXCEEDED", "容量不足", status_code=422)
