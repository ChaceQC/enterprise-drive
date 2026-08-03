from __future__ import annotations

from typing import NoReturn
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.api.errors import ApiError
from app.core.config import Settings
from app.core.pagination import decode_page_cursor, encode_page_cursor
from app.modules.admin.file_security_schemas import (
    AdminFileSecurityPolicyCreateRequest,
    AdminFileSecurityPolicyListResponse,
    AdminFileSecurityPolicyResponse,
    AdminFileSecurityPolicyUpdateRequest,
    FileClassification,
)
from app.modules.audit.schemas import AuditContext, AuditEvent
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.file_security.models import FileSecurityPolicy
from app.modules.file_security.repository import FileSecurityRepository


class AdminFileSecurityService:
    def __init__(
        self,
        *,
        repository: FileSecurityRepository,
        audit_service: AuditService,
        settings: Settings,
    ) -> None:
        self.repository = repository
        self.audit_service = audit_service
        self.settings = settings

    async def list_policies(
        self,
        *,
        current_user: User,
        is_active: bool | None,
        classification: FileClassification | None,
        name: str | None,
        cursor: str | None,
        page_size: int,
        audit_context: AuditContext | None,
    ) -> AdminFileSecurityPolicyListResponse:
        await self._require_admin(
            current_user=current_user,
            action="admin.file_security_policies.queried",
            resource_id=None,
            audit_context=audit_context,
        )
        decoded_cursor = decode_page_cursor(self.settings, cursor)
        policies = await self.repository.list_policies(
            tenant_id=current_user.tenant_id,
            is_active=is_active,
            classification=classification,
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
        await self._record(
            current_user=current_user,
            action="admin.file_security_policies.queried",
            resource_id=None,
            result="allowed",
            audit_context=audit_context,
            metadata={
                "is_active": is_active,
                "classification": classification,
                "name": name,
                "returned_count": len(page_policies),
                "has_next": next_cursor is not None,
            },
        )
        await self.repository.commit()
        return AdminFileSecurityPolicyListResponse(
            items=[_policy_response(policy) for policy in page_policies],
            next_cursor=next_cursor,
        )

    async def create_policy(
        self,
        *,
        current_user: User,
        request: AdminFileSecurityPolicyCreateRequest,
        audit_context: AuditContext | None,
    ) -> AdminFileSecurityPolicyResponse:
        action = "admin.file_security_policy.created"
        await self._require_admin(
            current_user=current_user,
            action=action,
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
                classification=request.classification,
                download_mode=request.download_mode,
                extensions=extensions,
                mime_prefixes=mime_prefixes,
                dlp_keywords=_normalize_keywords(request.dlp_keywords),
                dlp_action=request.dlp_action,
                fail_closed=request.fail_closed,
                watermark_text=_normalize_watermark_text(request.watermark_text),
                is_active=request.is_active,
            )
            await self._record(
                current_user=current_user,
                action=action,
                resource_id=policy.id,
                result="allowed",
                audit_context=audit_context,
                metadata=_policy_audit_metadata(policy),
            )
            await self.repository.commit()
        except IntegrityError:
            await self.repository.rollback()
            await self._deny(
                current_user=current_user,
                action=action,
                resource_id=None,
                code="FILE_SECURITY_POLICY_NAME_EXISTS",
                message="文件安全策略名称已存在",
                status_code=409,
                audit_context=audit_context,
                metadata={"name": request.name.strip(), "reason": "name_conflict"},
            )
        return _policy_response(policy)

    async def update_policy(
        self,
        *,
        current_user: User,
        policy_id: UUID,
        request: AdminFileSecurityPolicyUpdateRequest,
        audit_context: AuditContext | None,
    ) -> AdminFileSecurityPolicyResponse:
        action = "admin.file_security_policy.updated"
        await self._require_admin(
            current_user=current_user,
            action=action,
            resource_id=policy_id,
            audit_context=audit_context,
        )
        policy = await self._get_policy_or_deny(
            current_user=current_user,
            policy_id=policy_id,
            action=action,
            audit_context=audit_context,
        )
        await self._ensure_expected_version(
            current_user=current_user,
            policy=policy,
            expected_version=request.expected_version,
            action=action,
            audit_context=audit_context,
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

        changed_fields: list[str] = []
        for field_name, value in (
            ("name", request.name.strip() if request.name is not None else None),
            ("priority", request.priority),
            ("classification", request.classification),
            ("download_mode", request.download_mode),
            ("dlp_action", request.dlp_action),
            ("fail_closed", request.fail_closed),
            ("is_active", request.is_active),
        ):
            if value is not None and getattr(policy, field_name) != value:
                setattr(policy, field_name, value)
                changed_fields.append(field_name)
        if extensions != list(policy.extensions):
            policy.extensions = extensions
            changed_fields.append("extensions")
        if mime_prefixes != list(policy.mime_prefixes):
            policy.mime_prefixes = mime_prefixes
            changed_fields.append("mime_prefixes")
        if request.dlp_keywords is not None:
            keywords = _normalize_keywords(request.dlp_keywords)
            if keywords != list(policy.dlp_keywords):
                policy.dlp_keywords = keywords
                changed_fields.append("dlp_keywords")
        if request.clear_watermark_text and policy.watermark_text is not None:
            policy.watermark_text = None
            changed_fields.append("watermark_text")
        elif request.watermark_text is not None:
            watermark_text = _normalize_watermark_text(request.watermark_text)
            if policy.watermark_text != watermark_text:
                policy.watermark_text = watermark_text
                changed_fields.append("watermark_text")
        policy.version += 1

        try:
            await self._record(
                current_user=current_user,
                action=action,
                resource_id=policy.id,
                result="allowed",
                audit_context=audit_context,
                metadata={
                    **_policy_audit_metadata(policy),
                    "changed_fields": changed_fields,
                },
            )
            await self.repository.commit()
        except IntegrityError:
            await self.repository.rollback()
            await self._deny(
                current_user=current_user,
                action=action,
                resource_id=policy_id,
                code="FILE_SECURITY_POLICY_NAME_EXISTS",
                message="文件安全策略名称已存在",
                status_code=409,
                audit_context=audit_context,
                metadata={"reason": "name_conflict"},
            )
        return _policy_response(policy)

    async def deactivate_policy(
        self,
        *,
        current_user: User,
        policy_id: UUID,
        expected_version: int,
        audit_context: AuditContext | None,
    ) -> AdminFileSecurityPolicyResponse:
        action = "admin.file_security_policy.deactivated"
        await self._require_admin(
            current_user=current_user,
            action=action,
            resource_id=policy_id,
            audit_context=audit_context,
        )
        policy = await self._get_policy_or_deny(
            current_user=current_user,
            policy_id=policy_id,
            action=action,
            audit_context=audit_context,
        )
        await self._ensure_expected_version(
            current_user=current_user,
            policy=policy,
            expected_version=expected_version,
            action=action,
            audit_context=audit_context,
        )
        policy.is_active = False
        policy.version += 1
        await self._record(
            current_user=current_user,
            action=action,
            resource_id=policy.id,
            result="allowed",
            audit_context=audit_context,
            metadata=_policy_audit_metadata(policy),
        )
        await self.repository.commit()
        return _policy_response(policy)

    async def _ensure_expected_version(
        self,
        *,
        current_user: User,
        policy: FileSecurityPolicy,
        expected_version: int,
        action: str,
        audit_context: AuditContext | None,
    ) -> None:
        if policy.version == expected_version:
            return
        await self._deny(
            current_user=current_user,
            action=action,
            resource_id=policy.id,
            code="FILE_SECURITY_POLICY_CHANGED",
            message="文件安全策略已被其他请求修改",
            status_code=409,
            audit_context=audit_context,
            metadata={
                "expected_version": expected_version,
                "current_version": policy.version,
                "reason": "stale_precondition",
            },
        )

    async def _get_policy_or_deny(
        self,
        *,
        current_user: User,
        policy_id: UUID,
        action: str,
        audit_context: AuditContext | None,
    ) -> FileSecurityPolicy:
        policy = await self.repository.get_policy_for_update(
            tenant_id=current_user.tenant_id,
            policy_id=policy_id,
        )
        if policy is None:
            await self._deny(
                current_user=current_user,
                action=action,
                resource_id=policy_id,
                code="FILE_SECURITY_POLICY_NOT_FOUND",
                message="文件安全策略不存在",
                status_code=404,
                audit_context=audit_context,
                metadata={"reason": "policy_not_found"},
            )
        return policy

    async def _require_admin(
        self,
        *,
        current_user: User,
        action: str,
        resource_id: UUID | None,
        audit_context: AuditContext | None,
    ) -> None:
        if current_user.is_super_admin:
            return
        await self._deny(
            current_user=current_user,
            action=action,
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
                resource_type="file_security_policy",
                resource_id=resource_id,
                result=result,
                risk_level="high",
                metadata=metadata,
            ),
            context=audit_context or AuditContext(),
        )


def _policy_response(policy: FileSecurityPolicy) -> AdminFileSecurityPolicyResponse:
    return AdminFileSecurityPolicyResponse(
        id=policy.id,
        tenant_id=policy.tenant_id,
        name=policy.name,
        priority=policy.priority,
        classification=policy.classification,  # type: ignore[arg-type]
        download_mode=policy.download_mode,  # type: ignore[arg-type]
        extensions=list(policy.extensions),
        mime_prefixes=list(policy.mime_prefixes),
        dlp_keywords=list(policy.dlp_keywords),
        dlp_action=policy.dlp_action,  # type: ignore[arg-type]
        fail_closed=policy.fail_closed,
        watermark_text=policy.watermark_text,
        is_active=policy.is_active,
        version=policy.version,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )


def _policy_audit_metadata(policy: FileSecurityPolicy) -> dict[str, object]:
    return {
        "name": policy.name,
        "priority": policy.priority,
        "classification": policy.classification,
        "download_mode": policy.download_mode,
        "extensions": list(policy.extensions),
        "mime_prefixes": list(policy.mime_prefixes),
        "dlp_keyword_count": len(policy.dlp_keywords),
        "dlp_action": policy.dlp_action,
        "fail_closed": policy.fail_closed,
        "has_watermark_text": policy.watermark_text is not None,
        "is_active": policy.is_active,
        "version": policy.version,
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
                "FILE_SECURITY_SELECTOR_INVALID",
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
                "FILE_SECURITY_SELECTOR_INVALID",
                "MIME 前缀选择器不合法",
                status_code=422,
            )
        normalized.add(item)
    return sorted(normalized)


def _normalize_keywords(values: list[str]) -> list[str]:
    normalized: set[str] = set()
    for value in values:
        item = value.strip().casefold()
        if not item or len(item) > 128:
            raise ApiError(
                "FILE_SECURITY_DLP_KEYWORD_INVALID",
                "DLP 关键字不合法",
                status_code=422,
            )
        normalized.add(item)
    return sorted(normalized)


def _normalize_watermark_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _ensure_selectors_present(*, extensions: list[str], mime_prefixes: list[str]) -> None:
    if extensions or mime_prefixes:
        return
    raise ApiError(
        "FILE_SECURITY_SELECTOR_REQUIRED",
        "文件安全策略至少需要一个匹配条件",
        status_code=422,
    )
