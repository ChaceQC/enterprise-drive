from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from app.api.errors import ApiError
from app.core.config import Settings
from app.core.security import (
    create_csrf_token,
    create_session_token,
    ensure_utc,
    hash_password,
    hash_token,
    utc_now,
    verify_password,
)
from app.modules.audit.schemas import AuditContext, AuditEvent
from app.modules.audit.service import AuditService
from app.modules.auth.models import AuthSession, User
from app.modules.auth.repository import AuthRepository
from app.modules.auth.schemas import SessionResponse, UserProfileResponse


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
    ) -> IssuedSession:
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

        issued_session = await self._issue_session(user=user, family_id=uuid4())
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
        return issued_session

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

        issued_session = await self._issue_session(user=user, family_id=stored_token.family_id)
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

    async def _issue_session(self, *, user: User, family_id: UUID) -> IssuedSession:
        raw_session_token = create_session_token()
        raw_csrf_token = create_csrf_token()
        expires_at = utc_now() + timedelta(days=self.settings.session_days)
        await self.repository.create_auth_session(
            tenant_id=user.tenant_id,
            user_id=user.id,
            family_id=family_id,
            token_hash=hash_token(raw_session_token),
            csrf_token_hash=hash_token(raw_csrf_token),
            expires_at=expires_at,
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
