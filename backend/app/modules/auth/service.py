from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from app.api.errors import ApiError
from app.core.config import Settings
from app.core.metrics import record_auth_security_event
from app.core.security import (
    create_csrf_token,
    create_session_token,
    ensure_utc,
    hash_password,
    hash_token,
    utc_now,
    verify_password,
)
from app.infrastructure.captcha.base import (
    CaptchaContext,
    CaptchaVerifier,
    DisabledCaptchaVerifier,
)
from app.modules.audit.schemas import AuditContext, AuditEvent
from app.modules.audit.service import AuditService
from app.modules.auth.models import AuthSession, User
from app.modules.auth.repository import AuthRepository
from app.modules.auth.schemas import (
    BrowserSessionListResponse,
    BrowserSessionResponse,
    BrowserSessionRevokeResponse,
    PasswordChangeResponse,
    PasswordPolicyResponse,
    SessionResponse,
    UserProfileResponse,
)

_DUMMY_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$rgPem9k9R8j+41iADiuEdA$"
    "zRcQ86zm5XX5ebdXHXZ0+dVP/M0dXrKkElHiWtzWiuQ"
)


@dataclass(frozen=True)
class SeedAdminResult:
    tenant_created: bool
    user_created: bool
    username: str
    tenant_slug: str


@dataclass(frozen=True)
class IssuedSession:
    session_token: str
    csrf_token: str
    response: SessionResponse


class AuthService:
    def __init__(
        self,
        *,
        repository: AuthRepository,
        settings: Settings,
        audit_service: AuditService | None = None,
        captcha_verifier: CaptchaVerifier | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings
        self.audit_service = audit_service
        self.captcha_verifier = captcha_verifier or DisabledCaptchaVerifier()

    async def login(
        self,
        *,
        tenant_slug: str,
        username: str,
        password: str,
        captcha_token: str | None = None,
        audit_context: AuditContext | None = None,
    ) -> IssuedSession:
        user = await self.authenticate_password(
            tenant_slug=tenant_slug,
            username=username,
            password=password,
            audit_action="auth.login",
            captcha_token=captcha_token,
            allow_password_change_required=True,
            audit_context=audit_context,
        )
        issued_session = await self._issue_session(
            user=user,
            family_id=uuid4(),
            audit_context=audit_context,
            auth_method="local",
        )
        await self._record_auth_event(
            AuditEvent(
                tenant_id=user.tenant_id,
                actor_id=user.id,
                action="auth.login",
                resource_type="user",
                resource_id=user.id,
                result="allowed",
                metadata={"username": user.username},
            ),
            audit_context=audit_context,
        )
        record_auth_security_event(event="login", outcome="allowed")
        await self.repository.commit()
        return issued_session

    async def authenticate_password(
        self,
        *,
        tenant_slug: str,
        username: str,
        password: str,
        audit_action: str,
        captcha_token: str | None = None,
        allow_password_change_required: bool = False,
        audit_context: AuditContext | None = None,
    ) -> User:
        tenant = await self.repository.get_tenant_by_slug(tenant_slug)
        if tenant is None:
            verify_password(password, _DUMMY_PASSWORD_HASH)
            await self._apply_login_delay(1)
            record_auth_security_event(event="login", outcome="invalid_credentials")
            raise self._invalid_credentials()

        user = await self.repository.get_user_by_login(
            tenant_id=tenant.id,
            login=username,
            for_update=True,
        )
        if user is None or not user.is_active:
            verify_password(
                password,
                user.password_hash if user is not None else _DUMMY_PASSWORD_HASH,
            )
            await self._record_auth_event(
                AuditEvent(
                    tenant_id=tenant.id,
                    actor_id=user.id if user else None,
                    action=audit_action,
                    resource_type="user",
                    resource_id=user.id if user else None,
                    result="denied",
                    risk_level="medium",
                    metadata={"reason": "user_missing_or_inactive", "username": username},
                ),
                audit_context=audit_context,
            )
            await self.repository.commit()
            await self._apply_login_delay(1)
            record_auth_security_event(event="login", outcome="invalid_credentials")
            raise self._invalid_credentials()

        now = utc_now()
        self._expire_login_security_state(user=user, now=now)
        if user.locked_until is not None and ensure_utc(user.locked_until) > now:
            password_matches = user.local_password_enabled and verify_password(
                password,
                user.password_hash,
            )
            await self._record_auth_event(
                AuditEvent(
                    tenant_id=tenant.id,
                    actor_id=user.id,
                    action=audit_action,
                    resource_type="user",
                    resource_id=user.id,
                    result="denied",
                    risk_level="high",
                    metadata={
                        "reason": (
                            "account_locked" if password_matches else "bad_password_while_locked"
                        ),
                        "username": username,
                        "locked_until": ensure_utc(user.locked_until).isoformat(),
                    },
                ),
                audit_context=audit_context,
            )
            await self.repository.commit()
            if not password_matches:
                await self._apply_login_delay(user.failed_login_attempts)
                record_auth_security_event(event="login", outcome="invalid_credentials")
                raise self._invalid_credentials()
            record_auth_security_event(event="login", outcome="locked")
            raise self._account_locked(user=user, now=now)

        if not user.local_password_enabled:
            verify_password(password, user.password_hash)
            await self._record_auth_event(
                AuditEvent(
                    tenant_id=tenant.id,
                    actor_id=user.id,
                    action=audit_action,
                    resource_type="user",
                    resource_id=user.id,
                    result="denied",
                    risk_level="medium",
                    metadata={"reason": "local_password_disabled", "username": username},
                ),
                audit_context=audit_context,
            )
            await self.repository.commit()
            await self._apply_login_delay(1)
            record_auth_security_event(event="login", outcome="local_password_disabled")
            raise self._invalid_credentials()

        await self._ensure_login_captcha(
            user=user,
            captcha_token=captcha_token,
            audit_action=audit_action,
            audit_context=audit_context,
        )

        if not verify_password(password, user.password_hash):
            attempts = self._record_failed_login(user=user, now=now)
            locked = user.locked_until is not None
            await self._record_auth_event(
                AuditEvent(
                    tenant_id=tenant.id,
                    actor_id=user.id,
                    action=audit_action,
                    resource_type="user",
                    resource_id=user.id,
                    result="denied",
                    risk_level="medium",
                    metadata={
                        "reason": "bad_password",
                        "username": username,
                        "failed_login_attempts": attempts,
                        "locked": locked,
                    },
                ),
                audit_context=audit_context,
            )
            if locked:
                await self._record_auth_event(
                    AuditEvent(
                        tenant_id=tenant.id,
                        actor_id=user.id,
                        action="auth.account.locked",
                        resource_type="user",
                        resource_id=user.id,
                        result="allowed",
                        risk_level="high",
                        metadata={
                            "reason": user.lock_reason or "failed_login_threshold",
                            "failed_login_attempts": attempts,
                            "locked_until": (
                                ensure_utc(user.locked_until).isoformat()
                                if user.locked_until is not None
                                else None
                            ),
                        },
                    ),
                    audit_context=audit_context,
                )
            await self.repository.commit()
            await self._apply_login_delay(attempts)
            if locked:
                record_auth_security_event(event="account_lock", outcome="created")
                raise self._account_locked(user=user, now=now)
            record_auth_security_event(event="login", outcome="invalid_credentials")
            raise self._invalid_credentials()

        self._reset_login_security_state(user)
        if user.must_change_password and not allow_password_change_required:
            await self._record_auth_event(
                AuditEvent(
                    tenant_id=tenant.id,
                    actor_id=user.id,
                    action=audit_action,
                    resource_type="user",
                    resource_id=user.id,
                    result="denied",
                    risk_level="medium",
                    metadata={"reason": "password_change_required"},
                ),
                audit_context=audit_context,
            )
            await self.repository.commit()
            record_auth_security_event(event="login", outcome="password_change_required")
            raise ApiError(
                "PASSWORD_CHANGE_REQUIRED",
                "请先修改初始密码",
                status_code=403,
            )
        return user

    async def rotate_session(
        self,
        *,
        session_token: str,
        csrf_token: str | None,
        audit_context: AuditContext | None = None,
    ) -> IssuedSession:
        stored_token = await self._get_session_token(session_token)
        now = utc_now()

        if stored_token is None:
            raise ApiError("SESSION_INVALID", "登录会话无效", status_code=401)
        self._ensure_csrf_token(stored_token=stored_token, csrf_token=csrf_token)

        if stored_token.revoked_at is not None or stored_token.replaced_by_id is not None:
            await self.repository.revoke_auth_session_family(
                family_id=stored_token.family_id,
                revoked_at=now,
                reason="reuse_detected",
            )
            await self._record_auth_event(
                AuditEvent(
                    tenant_id=stored_token.tenant_id,
                    actor_id=stored_token.user_id,
                    action="auth.session.reused",
                    resource_type="auth_session",
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
            raise ApiError("SESSION_REUSED", "登录会话已失效", status_code=401)

        if ensure_utc(stored_token.expires_at) <= now:
            await self.repository.revoke_auth_session_family(
                family_id=stored_token.family_id,
                revoked_at=now,
                reason="expired",
            )
            await self._record_auth_event(
                AuditEvent(
                    tenant_id=stored_token.tenant_id,
                    actor_id=stored_token.user_id,
                    action="auth.session.rotated",
                    resource_type="auth_session",
                    resource_id=stored_token.id,
                    result="denied",
                    risk_level="medium",
                    metadata={"family_id": str(stored_token.family_id), "reason": "expired"},
                ),
                audit_context=audit_context,
            )
            await self.repository.commit()
            raise ApiError("SESSION_EXPIRED", "登录会话已过期", status_code=401)

        user = await self.repository.get_user_by_id(
            tenant_id=stored_token.tenant_id,
            user_id=stored_token.user_id,
        )
        if user is None or not user.is_active:
            await self.repository.revoke_auth_session_family(
                family_id=stored_token.family_id,
                revoked_at=now,
                reason="user_inactive",
            )
            await self._record_auth_event(
                AuditEvent(
                    tenant_id=stored_token.tenant_id,
                    actor_id=stored_token.user_id,
                    action="auth.session.rotated",
                    resource_type="auth_session",
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

        issued_session = await self._issue_session(
            user=user,
            family_id=stored_token.family_id,
            audit_context=audit_context,
            auth_method=stored_token.auth_method,
            oidc_provider_id=stored_token.oidc_provider_id,
            ip=stored_token.ip,
            user_agent=stored_token.user_agent,
        )
        new_stored_session = await self.repository.get_auth_session_by_token_hash(
            hash_token(issued_session.session_token)
        )
        if new_stored_session is None:
            raise ApiError("SESSION_INVALID", "登录会话创建失败", status_code=500)

        await self.repository.mark_auth_session_rotated(
            old_session_id=stored_token.id,
            new_session_id=new_stored_session.id,
            used_at=now,
        )
        await self._record_auth_event(
            AuditEvent(
                tenant_id=stored_token.tenant_id,
                actor_id=stored_token.user_id,
                action="auth.session.rotated",
                resource_type="auth_session",
                resource_id=stored_token.id,
                result="allowed",
                metadata={"family_id": str(stored_token.family_id)},
            ),
            audit_context=audit_context,
        )
        await self.repository.commit()
        return issued_session

    async def authenticate_session(
        self,
        *,
        session_token: str,
        csrf_token: str | None = None,
        require_csrf: bool = False,
    ) -> User:
        stored_token = await self._get_session_token(session_token)
        if stored_token is None:
            raise ApiError("AUTH_REQUIRED", "请先登录", status_code=401)
        if require_csrf:
            self._ensure_csrf_token(stored_token=stored_token, csrf_token=csrf_token)
        if (
            stored_token.revoked_at is not None
            or stored_token.replaced_by_id is not None
            or ensure_utc(stored_token.expires_at) <= utc_now()
        ):
            raise ApiError("AUTH_REQUIRED", "认证已失效", status_code=401)

        user = await self.repository.get_user_by_id(
            tenant_id=stored_token.tenant_id,
            user_id=stored_token.user_id,
        )
        if user is None or not user.is_active:
            raise ApiError("AUTH_REQUIRED", "认证已失效", status_code=401)
        return user

    async def get_active_user(self, *, tenant_id: UUID, user_id: UUID) -> User | None:
        user = await self.repository.get_user_by_id(tenant_id=tenant_id, user_id=user_id)
        if user is None or not user.is_active:
            return None
        return user

    async def get_tenant_id_by_slug(self, tenant_slug: str) -> UUID | None:
        tenant = await self.repository.get_tenant_by_slug(tenant_slug)
        return tenant.id if tenant is not None else None

    def get_password_policy(self) -> PasswordPolicyResponse:
        return password_policy_response(self.settings)

    async def change_password(
        self,
        *,
        current_user: User,
        session_token: str,
        current_password: str,
        new_password: str,
        audit_context: AuditContext | None = None,
    ) -> PasswordChangeResponse:
        stored_session = await self._get_session_token(session_token)
        if (
            stored_session is None
            or stored_session.user_id != current_user.id
            or stored_session.tenant_id != current_user.tenant_id
            or stored_session.revoked_at is not None
            or stored_session.replaced_by_id is not None
            or ensure_utc(stored_session.expires_at) <= utc_now()
        ):
            raise ApiError("AUTH_REQUIRED", "认证已失效", status_code=401)

        user = await self.repository.get_user_by_id(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            for_update=True,
        )
        if user is None or not user.is_active:
            raise ApiError("AUTH_REQUIRED", "认证已失效", status_code=401)
        if not user.local_password_enabled or not verify_password(
            current_password,
            user.password_hash,
        ):
            await self._record_auth_event(
                AuditEvent(
                    tenant_id=current_user.tenant_id,
                    actor_id=current_user.id,
                    action="auth.password.changed",
                    resource_type="user",
                    resource_id=current_user.id,
                    result="denied",
                    risk_level="medium",
                    metadata={"reason": "current_password_invalid"},
                ),
                audit_context=audit_context,
            )
            await self.repository.commit()
            record_auth_security_event(event="password_change", outcome="denied")
            raise ApiError(
                "CURRENT_PASSWORD_INVALID",
                "当前密码不正确",
                status_code=400,
            )

        ensure_password_policy(settings=self.settings, password=new_password)
        if verify_password(new_password, user.password_hash):
            raise ApiError(
                "PASSWORD_REUSE_NOT_ALLOWED",
                "新密码不能与当前密码相同",
                status_code=422,
            )

        now = utc_now()
        user.password_hash = hash_password(new_password)
        user.password_changed_at = now
        user.local_password_enabled = True
        user.must_change_password = False
        user.version += 1
        user.updated_at = now
        self._reset_login_security_state(user)
        await self.repository.revoke_all_user_sessions(
            tenant_id=user.tenant_id,
            user_id=user.id,
            revoked_at=now,
            reason="password_changed",
        )
        await self._record_auth_event(
            AuditEvent(
                tenant_id=user.tenant_id,
                actor_id=user.id,
                action="auth.password.changed",
                resource_type="user",
                resource_id=user.id,
                result="allowed",
                risk_level="high",
                metadata={"all_sessions_revoked": True},
            ),
            audit_context=audit_context,
        )
        await self.repository.commit()
        record_auth_security_event(event="password_change", outcome="allowed")
        return PasswordChangeResponse()

    async def list_browser_sessions(
        self,
        *,
        current_user: User,
        session_token: str,
    ) -> BrowserSessionListResponse:
        current_session = await self._get_session_token(session_token)
        if (
            current_session is None
            or current_session.tenant_id != current_user.tenant_id
            or current_session.user_id != current_user.id
        ):
            raise ApiError("AUTH_REQUIRED", "认证已失效", status_code=401)
        sessions = await self.repository.list_active_auth_sessions(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            now=utc_now(),
        )
        return BrowserSessionListResponse(
            items=[
                BrowserSessionResponse(
                    id=item.id,
                    family_id=item.family_id,
                    auth_method=item.auth_method,
                    oidc_provider_id=item.oidc_provider_id,
                    ip=item.ip,
                    user_agent=item.user_agent,
                    current=item.id == current_session.id,
                    created_at=item.created_at,
                    last_seen_at=item.last_seen_at,
                    expires_at=item.expires_at,
                )
                for item in sessions
            ]
        )

    async def revoke_browser_session(
        self,
        *,
        current_user: User,
        current_session_token: str,
        session_id: UUID,
        audit_context: AuditContext | None = None,
    ) -> BrowserSessionRevokeResponse:
        current_session = await self._get_session_token(current_session_token)
        if (
            current_session is None
            or current_session.tenant_id != current_user.tenant_id
            or current_session.user_id != current_user.id
        ):
            raise ApiError("AUTH_REQUIRED", "认证已失效", status_code=401)
        target = await self.repository.get_owned_auth_session(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            session_id=session_id,
        )
        now = utc_now()
        if target is None or target.revoked_at is not None or ensure_utc(target.expires_at) <= now:
            raise ApiError("AUTH_SESSION_NOT_FOUND", "登录会话不存在", status_code=404)

        current_revoked = current_session.family_id == target.family_id
        await self.repository.revoke_auth_session_family(
            family_id=target.family_id,
            revoked_at=now,
            reason="user_revoked",
        )
        await self._record_auth_event(
            AuditEvent(
                tenant_id=current_user.tenant_id,
                actor_id=current_user.id,
                action="auth.session.revoked",
                resource_type="auth_session",
                resource_id=target.id,
                result="allowed",
                risk_level="medium",
                metadata={
                    "family_id": str(target.family_id),
                    "current_session_revoked": current_revoked,
                },
            ),
            audit_context=audit_context,
        )
        await self.repository.commit()
        record_auth_security_event(event="session_revoke", outcome="allowed")
        return BrowserSessionRevokeResponse(
            revoked_session_id=target.id,
            current_session_revoked=current_revoked,
        )

    async def logout(
        self,
        *,
        session_token: str,
        csrf_token: str | None,
        audit_context: AuditContext | None = None,
    ) -> None:
        stored_token = await self._get_session_token(session_token)
        if stored_token is None:
            return
        self._ensure_csrf_token(stored_token=stored_token, csrf_token=csrf_token)
        now = utc_now()
        if stored_token.revoked_at is None:
            await self.repository.revoke_auth_session_family(
                family_id=stored_token.family_id,
                revoked_at=now,
                reason="logout",
            )
        await self._record_auth_event(
            AuditEvent(
                tenant_id=stored_token.tenant_id,
                actor_id=stored_token.user_id,
                action="auth.logout",
                resource_type="auth_session",
                resource_id=stored_token.id,
                result="allowed",
                metadata={"family_id": str(stored_token.family_id)},
            ),
            audit_context=audit_context,
        )
        await self.repository.commit()

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

    async def _issue_session(
        self,
        *,
        user: User,
        family_id: UUID,
        audit_context: AuditContext | None,
        auth_method: str,
        oidc_provider_id: UUID | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> IssuedSession:
        raw_session_token = create_session_token()
        raw_csrf_token = create_csrf_token()
        now = utc_now()
        expires_at = now + timedelta(days=self.settings.session_days)
        await self.repository.create_auth_session(
            tenant_id=user.tenant_id,
            user_id=user.id,
            family_id=family_id,
            token_hash=hash_token(raw_session_token),
            csrf_token_hash=hash_token(raw_csrf_token),
            expires_at=expires_at,
            ip=ip if ip is not None else (audit_context.ip if audit_context else None),
            user_agent=(
                user_agent
                if user_agent is not None
                else (audit_context.user_agent if audit_context else None)
            ),
            auth_method=auth_method,
            oidc_provider_id=oidc_provider_id,
            last_seen_at=now,
        )
        return IssuedSession(
            session_token=raw_session_token,
            csrf_token=raw_csrf_token,
            response=SessionResponse(
                expires_at=expires_at,
                user=self._profile_response(user),
            ),
        )

    async def _get_session_token(self, raw_token: str) -> AuthSession | None:
        return await self.repository.get_auth_session_by_token_hash(hash_token(raw_token))

    async def issue_external_session(
        self,
        *,
        user: User,
        auth_method: str,
        audit_context: AuditContext | None,
        oidc_provider_id: UUID | None = None,
    ) -> IssuedSession:
        return await self._issue_session(
            user=user,
            family_id=uuid4(),
            audit_context=audit_context,
            auth_method=auth_method,
            oidc_provider_id=oidc_provider_id,
        )

    async def _ensure_login_captcha(
        self,
        *,
        user: User,
        captcha_token: str | None,
        audit_action: str,
        audit_context: AuditContext | None,
    ) -> None:
        threshold = self.settings.login_captcha_after_failures
        if (
            not self.captcha_verifier.enabled
            or threshold <= 0
            or user.failed_login_attempts < threshold
        ):
            return

        try:
            verified = await self.captcha_verifier.verify(
                token=captcha_token,
                context=CaptchaContext(
                    action=audit_action,
                    client_ip=audit_context.ip if audit_context else None,
                ),
            )
        except Exception as exc:
            await self._record_auth_event(
                AuditEvent(
                    tenant_id=user.tenant_id,
                    actor_id=user.id,
                    action=audit_action,
                    resource_type="user",
                    resource_id=user.id,
                    result="denied",
                    risk_level="medium",
                    metadata={"reason": "captcha_unavailable"},
                ),
                audit_context=audit_context,
            )
            await self.repository.commit()
            record_auth_security_event(event="captcha", outcome="unavailable")
            raise ApiError(
                "CAPTCHA_UNAVAILABLE",
                "验证码服务暂不可用",
                status_code=503,
            ) from exc

        if verified:
            return
        await self._record_auth_event(
            AuditEvent(
                tenant_id=user.tenant_id,
                actor_id=user.id,
                action=audit_action,
                resource_type="user",
                resource_id=user.id,
                result="denied",
                risk_level="medium",
                metadata={
                    "reason": "captcha_required",
                    "failed_login_attempts": user.failed_login_attempts,
                },
            ),
            audit_context=audit_context,
        )
        await self.repository.commit()
        record_auth_security_event(event="captcha", outcome="required")
        raise ApiError(
            "CAPTCHA_REQUIRED",
            "请完成验证码校验",
            status_code=403,
            details={"required": True},
        )

    def _record_failed_login(self, *, user: User, now: datetime) -> int:
        current_time = now
        user.failed_login_attempts += 1
        user.last_failed_login_at = current_time
        if user.failed_login_attempts >= self.settings.login_failure_lock_threshold:
            user.locked_until = current_time + timedelta(seconds=self.settings.login_lock_seconds)
            user.lock_reason = "failed_login_threshold"
        return user.failed_login_attempts

    def _expire_login_security_state(self, *, user: User, now: datetime) -> None:
        current_time = now
        if user.locked_until is not None and ensure_utc(user.locked_until) <= current_time:
            self._reset_login_security_state(user)
            return
        if user.last_failed_login_at is None:
            return
        elapsed = current_time - ensure_utc(user.last_failed_login_at)
        if elapsed > timedelta(seconds=self.settings.login_failure_window_seconds):
            user.failed_login_attempts = 0
            user.last_failed_login_at = None

    @staticmethod
    def _reset_login_security_state(user: User) -> None:
        user.failed_login_attempts = 0
        user.last_failed_login_at = None
        user.locked_until = None
        user.lock_reason = None

    async def _apply_login_delay(self, attempts: int) -> None:
        base_delay = self.settings.login_delay_base_seconds
        maximum_delay = self.settings.login_delay_max_seconds
        if base_delay <= 0 or maximum_delay <= 0:
            return
        exponent = max(min(attempts - 1, 16), 0)
        delay = min(base_delay * (2**exponent), maximum_delay)
        if delay > 0:
            await asyncio.sleep(delay)

    @staticmethod
    def _account_locked(*, user: User, now: datetime) -> ApiError:
        current_time = now
        locked_until = (
            ensure_utc(user.locked_until) if user.locked_until is not None else current_time
        )
        retry_after = max(int((locked_until - current_time).total_seconds()) + 1, 1)
        return ApiError(
            "ACCOUNT_LOCKED",
            "账号已临时锁定，请稍后重试",
            status_code=423,
            details={
                "locked_until": locked_until.isoformat(),
                "retry_after_seconds": retry_after,
            },
            headers={"Retry-After": str(retry_after)},
        )

    @staticmethod
    def _ensure_csrf_token(
        *,
        stored_token: AuthSession,
        csrf_token: str | None,
    ) -> None:
        if csrf_token is None or stored_token.csrf_token_hash is None:
            raise ApiError("CSRF_TOKEN_INVALID", "CSRF 校验失败", status_code=403)
        if hash_token(csrf_token) != stored_token.csrf_token_hash:
            raise ApiError("CSRF_TOKEN_INVALID", "CSRF 校验失败", status_code=403)

    @staticmethod
    def _profile_response(user: User) -> UserProfileResponse:
        return UserProfileResponse(
            id=user.id,
            tenant_id=user.tenant_id,
            username=user.username,
            email=user.email,
            display_name=user.display_name,
            is_super_admin=user.is_super_admin,
            must_change_password=user.must_change_password,
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


def password_policy_response(settings: Settings) -> PasswordPolicyResponse:
    return PasswordPolicyResponse(
        min_length=settings.password_min_length,
        require_uppercase=settings.password_require_uppercase,
        require_lowercase=settings.password_require_lowercase,
        require_digit=settings.password_require_digit,
        require_special=settings.password_require_special,
    )


def ensure_password_policy(*, settings: Settings, password: str) -> None:
    violations: list[str] = []
    if len(password) < settings.password_min_length:
        violations.append("min_length")
    if settings.password_require_uppercase and not any(char.isupper() for char in password):
        violations.append("uppercase")
    if settings.password_require_lowercase and not any(char.islower() for char in password):
        violations.append("lowercase")
    if settings.password_require_digit and not any(char.isdigit() for char in password):
        violations.append("digit")
    if settings.password_require_special and not any(
        not char.isalnum() and not char.isspace() for char in password
    ):
        violations.append("special")
    if not violations:
        return
    raise ApiError(
        "PASSWORD_POLICY_VIOLATION",
        "新密码不符合密码策略",
        status_code=422,
        details={"violations": violations},
    )
