from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from app.api.errors import ApiError
from app.core.config import Settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    ensure_utc,
    hash_password,
    hash_token,
    utc_now,
    verify_password,
)
from app.modules.audit.schemas import AuditContext, AuditEvent
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.auth.repository import AuthRepository
from app.modules.auth.schemas import TokenResponse


@dataclass(frozen=True)
class SeedAdminResult:
    tenant_created: bool
    user_created: bool
    username: str
    tenant_slug: str


class AuthService:
    def __init__(
        self,
        *,
        repository: AuthRepository,
        settings: Settings,
        audit_service: AuditService | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings
        self.audit_service = audit_service

    async def login(
        self,
        *,
        tenant_slug: str,
        username: str,
        password: str,
        audit_context: AuditContext | None = None,
    ) -> TokenResponse:
        tenant = await self.repository.get_tenant_by_slug(tenant_slug)
        if tenant is None:
            raise self._invalid_credentials()

        user = await self.repository.get_user_by_login(tenant_id=tenant.id, login=username)
        if user is None or not user.is_active:
            await self._record_auth_event(
                AuditEvent(
                    tenant_id=tenant.id,
                    actor_id=user.id if user else None,
                    action="auth.login",
                    resource_type="user",
                    resource_id=user.id if user else None,
                    result="denied",
                    risk_level="medium",
                    metadata={"reason": "user_missing_or_inactive", "username": username},
                ),
                audit_context=audit_context,
            )
            await self.repository.commit()
            raise self._invalid_credentials()

        if not verify_password(password, user.password_hash):
            await self._record_auth_event(
                AuditEvent(
                    tenant_id=tenant.id,
                    actor_id=user.id,
                    action="auth.login",
                    resource_type="user",
                    resource_id=user.id,
                    result="denied",
                    risk_level="medium",
                    metadata={"reason": "bad_password", "username": username},
                ),
                audit_context=audit_context,
            )
            await self.repository.commit()
            raise self._invalid_credentials()

        token_response = await self._issue_token_pair(user=user, family_id=uuid4())
        await self._record_auth_event(
            AuditEvent(
                tenant_id=tenant.id,
                actor_id=user.id,
                action="auth.login",
                resource_type="user",
                resource_id=user.id,
                result="allowed",
                metadata={"username": user.username},
            ),
            audit_context=audit_context,
        )
        await self.repository.commit()
        return token_response

    async def refresh(
        self,
        *,
        refresh_token: str,
        audit_context: AuditContext | None = None,
    ) -> TokenResponse:
        token_hash = hash_token(refresh_token)
        stored_token = await self.repository.get_refresh_token_by_hash(token_hash)
        now = utc_now()

        if stored_token is None:
            raise ApiError("TOKEN_INVALID", "刷新令牌无效", status_code=401)

        if stored_token.revoked_at is not None or stored_token.replaced_by_id is not None:
            await self.repository.revoke_refresh_family(
                family_id=stored_token.family_id,
                revoked_at=now,
                reason="reuse_detected",
            )
            await self._record_auth_event(
                AuditEvent(
                    tenant_id=stored_token.tenant_id,
                    actor_id=stored_token.user_id,
                    action="auth.refresh.reused",
                    resource_type="refresh_token",
                    resource_id=stored_token.id,
                    result="denied",
                    risk_level="high",
                    metadata={
                        "family_id": str(stored_token.family_id),
                        "reason": "reuse_detected",
                    },
                ),
                audit_context=audit_context,
            )
            await self.repository.commit()
            raise ApiError("REFRESH_TOKEN_REUSED", "刷新令牌已失效", status_code=401)

        if ensure_utc(stored_token.expires_at) <= now:
            await self.repository.revoke_refresh_family(
                family_id=stored_token.family_id,
                revoked_at=now,
                reason="expired",
            )
            await self._record_auth_event(
                AuditEvent(
                    tenant_id=stored_token.tenant_id,
                    actor_id=stored_token.user_id,
                    action="auth.refresh",
                    resource_type="refresh_token",
                    resource_id=stored_token.id,
                    result="denied",
                    risk_level="medium",
                    metadata={"family_id": str(stored_token.family_id), "reason": "expired"},
                ),
                audit_context=audit_context,
            )
            await self.repository.commit()
            raise ApiError("TOKEN_EXPIRED", "刷新令牌已过期", status_code=401)

        user = await self.repository.get_user_by_id(
            tenant_id=stored_token.tenant_id,
            user_id=stored_token.user_id,
        )
        if user is None or not user.is_active:
            await self.repository.revoke_refresh_family(
                family_id=stored_token.family_id,
                revoked_at=now,
                reason="user_inactive",
            )
            await self._record_auth_event(
                AuditEvent(
                    tenant_id=stored_token.tenant_id,
                    actor_id=stored_token.user_id,
                    action="auth.refresh",
                    resource_type="refresh_token",
                    resource_id=stored_token.id,
                    result="denied",
                    risk_level="medium",
                    metadata={
                        "family_id": str(stored_token.family_id),
                        "reason": "user_missing_or_inactive",
                    },
                ),
                audit_context=audit_context,
            )
            await self.repository.commit()
            raise ApiError("AUTH_REQUIRED", "认证已失效", status_code=401)

        token_response = await self._issue_token_pair(user=user, family_id=stored_token.family_id)
        new_stored_token = await self.repository.get_refresh_token_by_hash(
            hash_token(token_response.refresh_token)
        )
        if new_stored_token is None:
            raise ApiError("TOKEN_INVALID", "刷新令牌创建失败", status_code=500)

        await self.repository.mark_refresh_token_rotated(
            old_token_id=stored_token.id,
            new_token_id=new_stored_token.id,
            used_at=now,
        )
        await self._record_auth_event(
            AuditEvent(
                tenant_id=stored_token.tenant_id,
                actor_id=stored_token.user_id,
                action="auth.refresh",
                resource_type="refresh_token",
                resource_id=stored_token.id,
                result="allowed",
                metadata={"family_id": str(stored_token.family_id)},
            ),
            audit_context=audit_context,
        )
        await self.repository.commit()
        return token_response

    async def seed_admin(self) -> SeedAdminResult:
        tenant = await self.repository.get_tenant_by_slug(self.settings.admin_tenant_slug)
        tenant_created = tenant is None
        if tenant is None:
            tenant = await self.repository.create_tenant(
                slug=self.settings.admin_tenant_slug,
                name=self.settings.admin_tenant_name,
            )

        user = await self.repository.get_user_by_login(
            tenant_id=tenant.id,
            login=self.settings.admin_username,
        )
        user_created = user is None
        if user is None:
            await self.repository.create_user(
                tenant_id=tenant.id,
                username=self.settings.admin_username,
                email=self.settings.admin_email,
                display_name="系统管理员",
                password_hash=hash_password(self.settings.admin_password),
                is_super_admin=True,
                must_change_password=True,
            )

        await self.repository.commit()
        return SeedAdminResult(
            tenant_created=tenant_created,
            user_created=user_created,
            username=self.settings.admin_username,
            tenant_slug=self.settings.admin_tenant_slug,
        )

    async def _issue_token_pair(self, *, user: User, family_id: UUID) -> TokenResponse:
        access_token, access_expires_at = create_access_token(
            settings=self.settings,
            user_id=user.id,
            tenant_id=user.tenant_id,
            username=user.username,
            is_super_admin=user.is_super_admin,
        )
        raw_refresh_token = create_refresh_token()
        refresh_expires_at = utc_now() + timedelta(days=self.settings.refresh_token_days)
        await self.repository.create_refresh_token(
            tenant_id=user.tenant_id,
            user_id=user.id,
            family_id=family_id,
            token_hash=hash_token(raw_refresh_token),
            expires_at=refresh_expires_at,
        )
        expires_in = max(int((access_expires_at - utc_now()).total_seconds()), 0)
        return TokenResponse(
            access_token=access_token,
            refresh_token=raw_refresh_token,
            expires_in=expires_in,
            refresh_expires_at=refresh_expires_at,
        )

    @staticmethod
    def _invalid_credentials() -> ApiError:
        return ApiError("AUTH_INVALID_CREDENTIALS", "用户名或密码错误", status_code=401)

    async def _record_auth_event(
        self,
        event: AuditEvent,
        *,
        audit_context: AuditContext | None,
    ) -> None:
        if self.audit_service is None:
            return
        await self.audit_service.record(event=event, context=audit_context or AuditContext())
