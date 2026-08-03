from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from app.api.errors import ApiError
from app.modules.quota.models import QuotaAccount, QuotaPolicy
from app.modules.quota.repository import QuotaRepository


class QuotaService:
    def __init__(
        self,
        *,
        repository: QuotaRepository,
        default_space_limit_bytes: int,
        default_user_limit_bytes: int = 0,
        default_tenant_limit_bytes: int = 0,
        policy_enabled: bool = True,
    ) -> None:
        self.repository = repository
        self.default_space_limit_bytes = default_space_limit_bytes
        self.default_user_limit_bytes = default_user_limit_bytes
        self.default_tenant_limit_bytes = default_tenant_limit_bytes
        self.policy_enabled = policy_enabled

    async def ensure_space_account(self, *, tenant_id: UUID, space_id: UUID) -> QuotaAccount:
        account = await self.repository.get_account(
            tenant_id=tenant_id,
            owner_type="space",
            owner_id=space_id,
        )
        if account is not None:
            return account
        return await self.repository.ensure_account(
            tenant_id=tenant_id,
            owner_type="space",
            owner_id=space_id,
            limit_bytes=self.default_space_limit_bytes,
        )

    async def ensure_upload_capacity(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        size_bytes: int,
        user_id: UUID | None = None,
        file_name: str | None = None,
        mime_type: str | None = None,
    ) -> None:
        account = await self.ensure_space_account(tenant_id=tenant_id, space_id=space_id)
        if account.used_bytes + size_bytes > account.limit_bytes:
            raise quota_exceeded_error("space")

        policy = await self._matching_policy(
            tenant_id=tenant_id,
            file_name=file_name,
            mime_type=mime_type,
        )
        if policy is not None:
            self._ensure_policy_file_size(policy=policy, size_bytes=size_bytes)
            policy_account = await self.repository.get_account(
                tenant_id=tenant_id,
                owner_type="policy",
                owner_id=policy.id,
            )
            if policy_account is None:
                policy_account = await self.repository.ensure_account(
                    tenant_id=tenant_id,
                    owner_type="policy",
                    owner_id=policy.id,
                    limit_bytes=policy.limit_bytes,
                )
            if (
                policy_account is not None
                and policy_account.used_bytes + size_bytes > policy_account.limit_bytes
            ):
                raise quota_exceeded_error("policy")

        for owner_type, owner_id, limit_bytes in await self._enabled_dimensions(
            tenant_id=tenant_id,
            user_id=user_id,
        ):
            dimension_account = await self.repository.ensure_account(
                tenant_id=tenant_id,
                owner_type=owner_type,
                owner_id=owner_id,
                limit_bytes=limit_bytes,
            )
            if dimension_account.used_bytes + size_bytes > dimension_account.limit_bytes:
                raise quota_exceeded_error(owner_type)

    async def ensure_space_capacity(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        size_bytes: int,
    ) -> None:
        """兼容旧调用方的空间维度快速检查。"""

        await self.ensure_upload_capacity(
            tenant_id=tenant_id,
            space_id=space_id,
            size_bytes=size_bytes,
        )

    async def reserve_file_version(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        version_id: UUID,
        size_bytes: int,
        user_id: UUID | None = None,
        file_name: str | None = None,
        mime_type: str | None = None,
    ) -> None:
        policy = await self._matching_policy(
            tenant_id=tenant_id,
            file_name=file_name,
            mime_type=mime_type,
        )
        self._ensure_policy_file_size(policy=policy, size_bytes=size_bytes)
        dimensions = [
            (
                "space",
                space_id,
                self.default_space_limit_bytes,
            ),
            *(await self._enabled_dimensions(tenant_id=tenant_id, user_id=user_id)),
        ]
        if policy is not None:
            dimensions.append(("policy", policy.id, policy.limit_bytes))

        # 维度顺序固定，所有扣减使用数据库原子 UPDATE，避免并发超配额。
        for owner_type, owner_id, limit_bytes in dimensions:
            await self.repository.ensure_account(
                tenant_id=tenant_id,
                owner_type=owner_type,
                owner_id=owner_id,
                limit_bytes=limit_bytes,
            )
            reserved_account_id = await self.repository.try_add_usage(
                tenant_id=tenant_id,
                owner_type=owner_type,
                owner_id=owner_id,
                delta_bytes=size_bytes,
            )
            if reserved_account_id is None:
                raise quota_exceeded_error(owner_type)
            await self.repository.add_ledger(
                tenant_id=tenant_id,
                account_id=reserved_account_id,
                account_type=owner_type,
                delta_bytes=size_bytes,
                reason="file_version_created",
                ref_type="file_version",
                ref_id=version_id,
            )

    async def release_file_usage(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        ref_id: UUID,
        size_bytes: int,
        version_ids: list[UUID] | None = None,
    ) -> None:
        if size_bytes <= 0:
            return
        if version_ids:
            entries = await self.repository.list_ledger_entries_for_refs(
                tenant_id=tenant_id,
                ref_type="file_version",
                ref_ids=version_ids,
            )
            grouped: dict[UUID, int] = defaultdict(int)
            for entry in entries:
                grouped[entry.account_id] += entry.delta_bytes
            released_space = False
            for account_id, delta_bytes in grouped.items():
                if (
                    await self.repository.subtract_usage_by_account_id(
                        tenant_id=tenant_id,
                        account_id=account_id,
                        delta_bytes=delta_bytes,
                    )
                    is None
                ):
                    raise ApiError("QUOTA_RELEASE_FAILED", "容量释放失败", status_code=500)
                account = await self.repository.get_account_by_id_for_update(
                    tenant_id=tenant_id,
                    account_id=account_id,
                )
                if account is None:
                    raise ApiError("QUOTA_RELEASE_FAILED", "容量账户不存在", status_code=500)
                await self.repository.add_ledger(
                    tenant_id=tenant_id,
                    account_id=account_id,
                    account_type=account.owner_type,
                    delta_bytes=-delta_bytes,
                    reason="file_purged",
                    ref_type="node",
                    ref_id=ref_id,
                )
                released_space = released_space or account.owner_type == "space"
            if released_space:
                return
        await self.ensure_space_account(tenant_id=tenant_id, space_id=space_id)
        released_account_id = await self.repository.subtract_usage(
            tenant_id=tenant_id,
            owner_type="space",
            owner_id=space_id,
            delta_bytes=size_bytes,
        )
        if released_account_id is None:
            raise ApiError("QUOTA_RELEASE_FAILED", "容量释放失败", status_code=500)
        await self.repository.add_ledger(
            tenant_id=tenant_id,
            account_id=released_account_id,
            account_type="space",
            delta_bytes=-size_bytes,
            reason="file_purged",
            ref_type="node",
            ref_id=ref_id,
        )

    async def _enabled_dimensions(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID | None,
    ) -> list[tuple[str, UUID, int]]:
        dimensions: list[tuple[str, UUID, int]] = []
        tenant_account = await self.repository.get_account(
            tenant_id=tenant_id,
            owner_type="tenant",
            owner_id=tenant_id,
        )
        if tenant_account is not None:
            dimensions.append(("tenant", tenant_id, tenant_account.limit_bytes))
        elif self.default_tenant_limit_bytes > 0:
            dimensions.append(("tenant", tenant_id, self.default_tenant_limit_bytes))
        if user_id is not None:
            user_account = await self.repository.get_account(
                tenant_id=tenant_id,
                owner_type="user",
                owner_id=user_id,
            )
            if user_account is not None:
                dimensions.append(("user", user_id, user_account.limit_bytes))
            elif self.default_user_limit_bytes > 0:
                dimensions.append(("user", user_id, self.default_user_limit_bytes))
        return dimensions

    async def _matching_policy(
        self,
        *,
        tenant_id: UUID,
        file_name: str | None,
        mime_type: str | None,
    ) -> QuotaPolicy | None:
        if not self.policy_enabled:
            return None
        normalized_name = (file_name or "").casefold()
        extension = ""
        if "." in normalized_name.rsplit("/", 1)[-1]:
            extension = "." + normalized_name.rsplit(".", 1)[-1]
        normalized_mime = (mime_type or "").casefold()
        for policy in await self.repository.list_active_policies(tenant_id=tenant_id):
            extensions = {str(item).casefold() for item in (policy.extensions or [])}
            extensions |= {f".{item.casefold().lstrip('.')}" for item in extensions}
            mime_prefixes = {str(item).casefold() for item in (policy.mime_prefixes or [])}
            if (extensions and extension in extensions) or (
                mime_prefixes
                and any(normalized_mime.startswith(prefix) for prefix in mime_prefixes)
            ):
                return policy
        return None

    @staticmethod
    def _ensure_policy_file_size(*, policy: QuotaPolicy | None, size_bytes: int) -> None:
        if (
            policy is not None
            and policy.max_file_size_bytes is not None
            and size_bytes > policy.max_file_size_bytes
        ):
            raise ApiError(
                "QUOTA_POLICY_FILE_SIZE_EXCEEDED",
                "文件超过策略允许的单文件大小",
                status_code=422,
                details={"policy_id": str(policy.id)},
            )


def quota_exceeded_error(scope: str = "space") -> ApiError:
    return ApiError(
        "QUOTA_EXCEEDED",
        "容量不足",
        status_code=422,
        details={"scope": scope},
    )
