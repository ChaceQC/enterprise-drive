from __future__ import annotations

from typing import NoReturn
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.api.errors import ApiError
from app.core.config import Settings
from app.core.pagination import decode_page_cursor, encode_page_cursor
from app.modules.admin.quota_schemas import (
    AdminQuotaAccountListResponse,
    AdminQuotaAccountResponse,
    AdminQuotaPolicyCreateRequest,
    AdminQuotaPolicyListResponse,
    AdminQuotaPolicyResponse,
    AdminQuotaPolicyUpdateRequest,
    ManageableQuotaOwnerType,
    QuotaOwnerType,
)
from app.modules.audit.schemas import AuditContext, AuditEvent
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.quota.models import QuotaAccount, QuotaPolicy
from app.modules.quota.repository import QuotaRepository


class AdminQuotaService:
    def __init__(
        self,
        *,
        repository: QuotaRepository,
        audit_service: AuditService,
        settings: Settings,
    ) -> None:
        self.repository = repository
        self.audit_service = audit_service
        self.settings = settings

    async def list_accounts(
        self,
        *,
        current_user: User,
        owner_type: QuotaOwnerType | None,
        owner_id: UUID | None,
        cursor: str | None,
        page_size: int,
        audit_context: AuditContext | None,
    ) -> AdminQuotaAccountListResponse:
        await self._require_super_admin(
            current_user=current_user,
            action="admin.quota_accounts.queried",
            resource_type="quota_account",
            resource_id=owner_id,
            audit_context=audit_context,
        )
        decoded_cursor = decode_page_cursor(self.settings, cursor)
        accounts = await self.repository.list_accounts(
            tenant_id=current_user.tenant_id,
            owner_type=owner_type,
            owner_id=owner_id,
            limit=page_size + 1,
            cursor=decoded_cursor,
        )
        page_accounts = accounts[:page_size]
        next_cursor = None
        if len(accounts) > page_size and page_accounts:
            last = page_accounts[-1]
            next_cursor = encode_page_cursor(
                self.settings,
                created_at=last.created_at,
                item_id=last.id,
            )
        await self._record(
            current_user=current_user,
            action="admin.quota_accounts.queried",
            resource_type="quota_account",
            resource_id=owner_id,
            result="allowed",
            audit_context=audit_context,
            metadata={
                "owner_type": owner_type,
                "owner_id": str(owner_id) if owner_id else None,
                "returned_count": len(page_accounts),
                "has_next": next_cursor is not None,
            },
        )
        await self.repository.commit()
        return AdminQuotaAccountListResponse(
            items=[_account_response(account) for account in page_accounts],
            next_cursor=next_cursor,
        )

    async def upsert_account(
        self,
        *,
        current_user: User,
        owner_type: ManageableQuotaOwnerType,
        owner_id: UUID,
        limit_bytes: int,
        expected_limit_bytes: int | None,
        audit_context: AuditContext | None,
    ) -> AdminQuotaAccountResponse:
        action = "admin.quota_account.updated"
        await self._require_super_admin(
            current_user=current_user,
            action=action,
            resource_type="quota_account",
            resource_id=owner_id,
            audit_context=audit_context,
        )
        if not await self.repository.owner_exists(
            tenant_id=current_user.tenant_id,
            owner_type=owner_type,
            owner_id=owner_id,
        ):
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="quota_account",
                resource_id=owner_id,
                code="QUOTA_OWNER_NOT_FOUND",
                message="配额账户主体不存在",
                status_code=404,
                audit_context=audit_context,
                metadata={"owner_type": owner_type, "reason": "owner_not_found"},
            )

        account = await self.repository.get_account_by_owner_for_update(
            tenant_id=current_user.tenant_id,
            owner_type=owner_type,
            owner_id=owner_id,
        )
        if account is None:
            created = True
            if expected_limit_bytes is not None:
                await self._account_changed(
                    current_user=current_user,
                    action=action,
                    owner_type=owner_type,
                    owner_id=owner_id,
                    expected_limit_bytes=expected_limit_bytes,
                    current_limit_bytes=None,
                    audit_context=audit_context,
                )
            await self.repository.ensure_account(
                tenant_id=current_user.tenant_id,
                owner_type=owner_type,
                owner_id=owner_id,
                limit_bytes=limit_bytes,
            )
            account = await self.repository.get_account_by_owner_for_update(
                tenant_id=current_user.tenant_id,
                owner_type=owner_type,
                owner_id=owner_id,
            )
            if account is None:
                raise ApiError("QUOTA_ACCOUNT_UPDATE_FAILED", "配额账户更新失败", status_code=500)
        else:
            created = False
            if expected_limit_bytes is None:
                await self._deny(
                    current_user=current_user,
                    action=action,
                    resource_type="quota_account",
                    resource_id=account.id,
                    code="QUOTA_ACCOUNT_PRECONDITION_REQUIRED",
                    message="更新现有配额账户必须提供当前额度",
                    status_code=428,
                    audit_context=audit_context,
                    metadata={
                        "owner_type": owner_type,
                        "owner_id": str(owner_id),
                        "reason": "expected_limit_required",
                    },
                )
            if account.limit_bytes != expected_limit_bytes:
                await self._account_changed(
                    current_user=current_user,
                    action=action,
                    owner_type=owner_type,
                    owner_id=owner_id,
                    expected_limit_bytes=expected_limit_bytes,
                    current_limit_bytes=account.limit_bytes,
                    audit_context=audit_context,
                )

        if limit_bytes < account.used_bytes:
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="quota_account",
                resource_id=account.id,
                code="QUOTA_LIMIT_BELOW_USAGE",
                message="新额度不能低于当前已用容量",
                status_code=409,
                audit_context=audit_context,
                metadata={
                    "owner_type": owner_type,
                    "owner_id": str(owner_id),
                    "used_bytes": account.used_bytes,
                    "requested_limit_bytes": limit_bytes,
                    "reason": "limit_below_usage",
                },
            )
        previous_limit = account.limit_bytes
        account.limit_bytes = limit_bytes
        action = "admin.quota_account.created" if created else action
        await self._record(
            current_user=current_user,
            action=action,
            resource_type="quota_account",
            resource_id=account.id,
            result="allowed",
            audit_context=audit_context,
            metadata={
                "owner_type": owner_type,
                "owner_id": str(owner_id),
                "previous_limit_bytes": None if created else previous_limit,
                "limit_bytes": limit_bytes,
                "used_bytes": account.used_bytes,
            },
        )
        await self.repository.commit()
        return _account_response(account)

    async def list_policies(
        self,
        *,
        current_user: User,
        is_active: bool | None,
        name: str | None,
        cursor: str | None,
        page_size: int,
        audit_context: AuditContext | None,
    ) -> AdminQuotaPolicyListResponse:
        await self._require_super_admin(
            current_user=current_user,
            action="admin.quota_policies.queried",
            resource_type="quota_policy",
            resource_id=None,
            audit_context=audit_context,
        )
        decoded_cursor = decode_page_cursor(self.settings, cursor)
        policies = await self.repository.list_policies(
            tenant_id=current_user.tenant_id,
            is_active=is_active,
            name=name,
            limit=page_size + 1,
            cursor=decoded_cursor,
        )
        page_policies = policies[:page_size]
        next_cursor = None
        if len(policies) > page_size and page_policies:
            last = page_policies[-1]
            next_cursor = encode_page_cursor(
                self.settings,
                created_at=last.created_at,
                item_id=last.id,
            )
        responses = [await self._policy_response(policy) for policy in page_policies]
        await self._record(
            current_user=current_user,
            action="admin.quota_policies.queried",
            resource_type="quota_policy",
            resource_id=None,
            result="allowed",
            audit_context=audit_context,
            metadata={
                "is_active": is_active,
                "name": name,
                "returned_count": len(responses),
                "has_next": next_cursor is not None,
            },
        )
        await self.repository.commit()
        return AdminQuotaPolicyListResponse(items=responses, next_cursor=next_cursor)

    async def create_policy(
        self,
        *,
        current_user: User,
        request: AdminQuotaPolicyCreateRequest,
        audit_context: AuditContext | None,
    ) -> AdminQuotaPolicyResponse:
        action = "admin.quota_policy.created"
        await self._require_super_admin(
            current_user=current_user,
            action=action,
            resource_type="quota_policy",
            resource_id=None,
            audit_context=audit_context,
        )
        extensions, mime_prefixes = _normalize_selectors(
            extensions=request.extensions,
            mime_prefixes=request.mime_prefixes,
        )
        try:
            policy = await self.repository.create_policy(
                tenant_id=current_user.tenant_id,
                name=request.name.strip(),
                priority=request.priority,
                limit_bytes=request.limit_bytes,
                max_file_size_bytes=request.max_file_size_bytes,
                extensions=extensions,
                mime_prefixes=mime_prefixes,
                is_active=request.is_active,
            )
            await self.repository.ensure_account(
                tenant_id=current_user.tenant_id,
                owner_type="policy",
                owner_id=policy.id,
                limit_bytes=policy.limit_bytes,
            )
            await self._record(
                current_user=current_user,
                action=action,
                resource_type="quota_policy",
                resource_id=policy.id,
                result="allowed",
                audit_context=audit_context,
                metadata=_policy_metadata(policy),
            )
            await self.repository.commit()
        except IntegrityError:
            await self.repository.rollback()
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="quota_policy",
                resource_id=None,
                code="QUOTA_POLICY_NAME_EXISTS",
                message="配额策略名称已存在",
                status_code=409,
                audit_context=audit_context,
                metadata={"name": request.name.strip(), "reason": "name_conflict"},
            )
        return await self._policy_response(policy)

    async def update_policy(
        self,
        *,
        current_user: User,
        policy_id: UUID,
        request: AdminQuotaPolicyUpdateRequest,
        audit_context: AuditContext | None,
    ) -> AdminQuotaPolicyResponse:
        action = "admin.quota_policy.updated"
        await self._require_super_admin(
            current_user=current_user,
            action=action,
            resource_type="quota_policy",
            resource_id=policy_id,
            audit_context=audit_context,
        )
        policy = await self._get_policy_or_deny(
            current_user=current_user,
            policy_id=policy_id,
            action=action,
            audit_context=audit_context,
        )
        if policy.limit_bytes != request.expected_limit_bytes:
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="quota_policy",
                resource_id=policy.id,
                code="QUOTA_POLICY_CHANGED",
                message="配额策略已被其他请求修改",
                status_code=409,
                audit_context=audit_context,
                metadata={
                    "expected_limit_bytes": request.expected_limit_bytes,
                    "current_limit_bytes": policy.limit_bytes,
                    "reason": "stale_precondition",
                },
            )

        extensions = (
            _normalize_extensions(request.extensions)
            if request.extensions is not None
            else list(policy.extensions)
        )
        mime_prefixes = (
            _normalize_mime_prefixes(request.mime_prefixes)
            if request.mime_prefixes is not None
            else list(policy.mime_prefixes)
        )
        _ensure_selectors_present(extensions=extensions, mime_prefixes=mime_prefixes)

        new_limit = request.limit_bytes or policy.limit_bytes
        account = await self.repository.get_account_by_owner_for_update(
            tenant_id=current_user.tenant_id,
            owner_type="policy",
            owner_id=policy.id,
        )
        if account is None:
            account = await self.repository.ensure_account(
                tenant_id=current_user.tenant_id,
                owner_type="policy",
                owner_id=policy.id,
                limit_bytes=policy.limit_bytes,
            )
        if new_limit < account.used_bytes:
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="quota_policy",
                resource_id=policy.id,
                code="QUOTA_LIMIT_BELOW_USAGE",
                message="新额度不能低于当前已用容量",
                status_code=409,
                audit_context=audit_context,
                metadata={
                    "used_bytes": account.used_bytes,
                    "requested_limit_bytes": new_limit,
                    "reason": "limit_below_usage",
                },
            )

        changed_fields: list[str] = []
        for field_name, value in (
            ("name", request.name.strip() if request.name is not None else None),
            ("priority", request.priority),
            ("limit_bytes", request.limit_bytes),
            ("is_active", request.is_active),
        ):
            if value is not None and getattr(policy, field_name) != value:
                setattr(policy, field_name, value)
                changed_fields.append(field_name)
        if request.clear_max_file_size and policy.max_file_size_bytes is not None:
            policy.max_file_size_bytes = None
            changed_fields.append("max_file_size_bytes")
        elif (
            request.max_file_size_bytes is not None
            and policy.max_file_size_bytes != request.max_file_size_bytes
        ):
            policy.max_file_size_bytes = request.max_file_size_bytes
            changed_fields.append("max_file_size_bytes")
        if extensions != list(policy.extensions):
            policy.extensions = extensions
            changed_fields.append("extensions")
        if mime_prefixes != list(policy.mime_prefixes):
            policy.mime_prefixes = mime_prefixes
            changed_fields.append("mime_prefixes")
        account.limit_bytes = new_limit

        try:
            await self._record(
                current_user=current_user,
                action=action,
                resource_type="quota_policy",
                resource_id=policy.id,
                result="allowed",
                audit_context=audit_context,
                metadata={
                    **_policy_metadata(policy),
                    "changed_fields": changed_fields,
                    "used_bytes": account.used_bytes,
                },
            )
            await self.repository.commit()
        except IntegrityError:
            await self.repository.rollback()
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="quota_policy",
                resource_id=policy.id,
                code="QUOTA_POLICY_NAME_EXISTS",
                message="配额策略名称已存在",
                status_code=409,
                audit_context=audit_context,
                metadata={"reason": "name_conflict"},
            )
        return await self._policy_response(policy)

    async def deactivate_policy(
        self,
        *,
        current_user: User,
        policy_id: UUID,
        expected_limit_bytes: int,
        audit_context: AuditContext | None,
    ) -> AdminQuotaPolicyResponse:
        action = "admin.quota_policy.deactivated"
        await self._require_super_admin(
            current_user=current_user,
            action=action,
            resource_type="quota_policy",
            resource_id=policy_id,
            audit_context=audit_context,
        )
        policy = await self._get_policy_or_deny(
            current_user=current_user,
            policy_id=policy_id,
            action=action,
            audit_context=audit_context,
        )
        if policy.limit_bytes != expected_limit_bytes:
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="quota_policy",
                resource_id=policy.id,
                code="QUOTA_POLICY_CHANGED",
                message="配额策略已被其他请求修改",
                status_code=409,
                audit_context=audit_context,
                metadata={
                    "expected_limit_bytes": expected_limit_bytes,
                    "current_limit_bytes": policy.limit_bytes,
                    "reason": "stale_precondition",
                },
            )
        policy.is_active = False
        await self._record(
            current_user=current_user,
            action=action,
            resource_type="quota_policy",
            resource_id=policy.id,
            result="allowed",
            audit_context=audit_context,
            metadata=_policy_metadata(policy),
        )
        await self.repository.commit()
        return await self._policy_response(policy)

    async def _get_policy_or_deny(
        self,
        *,
        current_user: User,
        policy_id: UUID,
        action: str,
        audit_context: AuditContext | None,
    ) -> QuotaPolicy:
        policy = await self.repository.get_policy_for_update(
            tenant_id=current_user.tenant_id,
            policy_id=policy_id,
        )
        if policy is None:
            await self._deny(
                current_user=current_user,
                action=action,
                resource_type="quota_policy",
                resource_id=policy_id,
                code="QUOTA_POLICY_NOT_FOUND",
                message="配额策略不存在",
                status_code=404,
                audit_context=audit_context,
                metadata={"reason": "policy_not_found"},
            )
        return policy

    async def _policy_response(self, policy: QuotaPolicy) -> AdminQuotaPolicyResponse:
        account = await self.repository.get_account(
            tenant_id=policy.tenant_id,
            owner_type="policy",
            owner_id=policy.id,
        )
        return AdminQuotaPolicyResponse(
            id=policy.id,
            tenant_id=policy.tenant_id,
            name=policy.name,
            priority=policy.priority,
            limit_bytes=policy.limit_bytes,
            used_bytes=account.used_bytes if account is not None else 0,
            max_file_size_bytes=policy.max_file_size_bytes,
            extensions=list(policy.extensions),
            mime_prefixes=list(policy.mime_prefixes),
            is_active=policy.is_active,
            created_at=policy.created_at,
            updated_at=policy.updated_at,
        )

    async def _account_changed(
        self,
        *,
        current_user: User,
        action: str,
        owner_type: str,
        owner_id: UUID,
        expected_limit_bytes: int,
        current_limit_bytes: int | None,
        audit_context: AuditContext | None,
    ) -> NoReturn:
        await self._deny(
            current_user=current_user,
            action=action,
            resource_type="quota_account",
            resource_id=owner_id,
            code="QUOTA_ACCOUNT_CHANGED",
            message="配额账户已被其他请求修改",
            status_code=409,
            audit_context=audit_context,
            metadata={
                "owner_type": owner_type,
                "owner_id": str(owner_id),
                "expected_limit_bytes": expected_limit_bytes,
                "current_limit_bytes": current_limit_bytes,
                "reason": "stale_precondition",
            },
        )

    async def _require_super_admin(
        self,
        *,
        current_user: User,
        action: str,
        resource_type: str,
        resource_id: UUID | None,
        audit_context: AuditContext | None,
    ) -> None:
        if current_user.is_super_admin:
            return
        await self._deny(
            current_user=current_user,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            code="ADMIN_REQUIRED",
            message="需要系统管理员权限",
            status_code=403,
            audit_context=audit_context,
            metadata={"reason": "super_admin_required"},
        )

    async def _deny(
        self,
        *,
        current_user: User,
        action: str,
        resource_type: str,
        resource_id: UUID | None,
        code: str,
        message: str,
        status_code: int,
        audit_context: AuditContext | None,
        metadata: dict[str, object],
    ) -> NoReturn:
        await self._record(
            current_user=current_user,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            result="denied",
            audit_context=audit_context,
            metadata=metadata,
        )
        await self.repository.commit()
        raise ApiError(code, message, status_code=status_code)

    async def _record(
        self,
        *,
        current_user: User,
        action: str,
        resource_type: str,
        resource_id: UUID | None,
        result: str,
        audit_context: AuditContext | None,
        metadata: dict[str, object],
    ) -> None:
        await self.audit_service.record(
            event=AuditEvent(
                tenant_id=current_user.tenant_id,
                actor_id=current_user.id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                result=result,
                risk_level="medium",
                metadata=metadata,
            ),
            context=audit_context or AuditContext(),
        )


def _account_response(account: QuotaAccount) -> AdminQuotaAccountResponse:
    return AdminQuotaAccountResponse(
        id=account.id,
        tenant_id=account.tenant_id,
        owner_type=account.owner_type,  # type: ignore[arg-type]
        owner_id=account.owner_id,
        limit_bytes=account.limit_bytes,
        used_bytes=account.used_bytes,
        remaining_bytes=max(account.limit_bytes - account.used_bytes, 0),
        created_at=account.created_at,
        updated_at=account.updated_at,
    )


def _policy_metadata(policy: QuotaPolicy) -> dict[str, object]:
    return {
        "name": policy.name,
        "priority": policy.priority,
        "limit_bytes": policy.limit_bytes,
        "max_file_size_bytes": policy.max_file_size_bytes,
        "extensions": list(policy.extensions),
        "mime_prefixes": list(policy.mime_prefixes),
        "is_active": policy.is_active,
    }


def _normalize_selectors(
    *,
    extensions: list[str],
    mime_prefixes: list[str],
) -> tuple[list[str], list[str]]:
    normalized_extensions = _normalize_extensions(extensions)
    normalized_mime_prefixes = _normalize_mime_prefixes(mime_prefixes)
    _ensure_selectors_present(
        extensions=normalized_extensions,
        mime_prefixes=normalized_mime_prefixes,
    )
    return normalized_extensions, normalized_mime_prefixes


def _normalize_extensions(values: list[str]) -> list[str]:
    normalized: set[str] = set()
    for value in values:
        item = value.strip().casefold()
        if not item or "/" in item or "\\" in item or len(item) > 32:
            raise ApiError(
                "QUOTA_POLICY_SELECTOR_INVALID",
                "文件扩展名选择器不合法",
                status_code=422,
            )
        normalized.add(f".{item.lstrip('.')}")
    return sorted(normalized)


def _normalize_mime_prefixes(values: list[str]) -> list[str]:
    normalized: set[str] = set()
    for value in values:
        item = value.strip().casefold()
        if not item or "/" not in item or len(item) > 128:
            raise ApiError(
                "QUOTA_POLICY_SELECTOR_INVALID",
                "MIME 前缀选择器不合法",
                status_code=422,
            )
        normalized.add(item)
    return sorted(normalized)


def _ensure_selectors_present(*, extensions: list[str], mime_prefixes: list[str]) -> None:
    if extensions or mime_prefixes:
        return
    raise ApiError(
        "QUOTA_POLICY_SELECTOR_REQUIRED",
        "配额策略至少需要一个匹配条件",
        status_code=422,
    )
