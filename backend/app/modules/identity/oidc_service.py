from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.api.errors import ApiError
from app.core.config import Settings
from app.core.metrics import record_identity_provider_operation
from app.core.security import hash_token, utc_now
from app.infrastructure.identity.base import (
    OidcIdentity,
    OidcProviderAdapter,
    OidcProviderConfig,
    SecretResolver,
)
from app.infrastructure.identity.oidc import create_pkce_challenge
from app.modules.audit.schemas import AuditContext, AuditEvent
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.auth.service import AuthService, IssuedSession
from app.modules.identity.models import OidcFlow, OidcIdentityLink, OidcProvider
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.schemas import (
    OidcIdentityLinkListResponse,
    OidcIdentityLinkResponse,
    OidcIdentityUnlinkResponse,
    OidcLogoutResponse,
    OidcProviderCreateRequest,
    OidcProviderListResponse,
    OidcProviderResponse,
    OidcProviderTestResponse,
    OidcProviderUpdateRequest,
    OidcStartResponse,
    PublicOidcProviderListResponse,
    PublicOidcProviderResponse,
)


@dataclass(frozen=True, slots=True)
class OidcCallbackResult:
    redirect_path: str
    issued_session: IssuedSession | None
    linked: bool


class OidcIdentityService:
    def __init__(
        self,
        *,
        repository: IdentityRepository,
        auth_service: AuthService,
        provider_adapter: OidcProviderAdapter,
        secret_resolver: SecretResolver,
        settings: Settings,
        audit_service: AuditService | None = None,
    ) -> None:
        self.repository = repository
        self.auth_service = auth_service
        self.provider_adapter = provider_adapter
        self.secret_resolver = secret_resolver
        self.settings = settings
        self.audit_service = audit_service

    async def list_public_providers(
        self,
        *,
        tenant_slug: str,
    ) -> PublicOidcProviderListResponse:
        tenant = await self.repository.get_tenant_by_slug(tenant_slug.strip())
        if tenant is None:
            return PublicOidcProviderListResponse(items=[])
        providers = await self.repository.list_public_oidc_providers(tenant_id=tenant.id)
        return PublicOidcProviderListResponse(
            items=[
                PublicOidcProviderResponse(slug=provider.slug, name=provider.name)
                for provider in providers
            ]
        )

    async def list_providers(
        self,
        *,
        current_user: User,
        audit_context: AuditContext | None,
    ) -> OidcProviderListResponse:
        await self._require_admin(
            current_user=current_user,
            action="identity.oidc.provider.list",
            resource_id=None,
            audit_context=audit_context,
        )
        providers = await self.repository.list_oidc_providers(tenant_id=current_user.tenant_id)
        return OidcProviderListResponse(
            items=[_provider_response(provider) for provider in providers]
        )

    async def create_provider(
        self,
        *,
        current_user: User,
        request: OidcProviderCreateRequest,
        audit_context: AuditContext | None,
    ) -> OidcProviderResponse:
        await self._require_admin(
            current_user=current_user,
            action="identity.oidc.provider.created",
            resource_id=None,
            audit_context=audit_context,
        )
        provider = OidcProvider(
            tenant_id=current_user.tenant_id,
            slug=request.slug.strip().lower(),
            name=request.name.strip(),
            issuer_url=request.issuer_url.strip().rstrip("/"),
            client_id=request.client_id.strip(),
            client_secret_ref=_normalize_optional(request.client_secret_ref),
            scopes=_normalize_scopes(request.scopes),
            enabled=request.enabled,
        )
        try:
            await self.repository.create_oidc_provider(provider)
            await self._record(
                AuditEvent(
                    tenant_id=current_user.tenant_id,
                    actor_id=current_user.id,
                    action="identity.oidc.provider.created",
                    resource_type="oidc_provider",
                    resource_id=provider.id,
                    result="allowed",
                    metadata={
                        "slug": provider.slug,
                        "issuer_url": provider.issuer_url,
                        "client_secret_configured": provider.client_secret_ref is not None,
                    },
                ),
                audit_context=audit_context,
            )
            await self.repository.commit()
        except IntegrityError as exc:
            await self.repository.rollback()
            raise ApiError(
                "OIDC_PROVIDER_CONFLICT",
                "OIDC provider 标识已存在",
                status_code=409,
            ) from exc
        return _provider_response(provider)

    async def update_provider(
        self,
        *,
        current_user: User,
        provider_id: UUID,
        request: OidcProviderUpdateRequest,
        audit_context: AuditContext | None,
    ) -> OidcProviderResponse:
        await self._require_admin(
            current_user=current_user,
            action="identity.oidc.provider.updated",
            resource_id=provider_id,
            audit_context=audit_context,
        )
        provider = await self.repository.get_oidc_provider(
            tenant_id=current_user.tenant_id,
            provider_id=provider_id,
            for_update=True,
        )
        if provider is None:
            raise ApiError("OIDC_PROVIDER_NOT_FOUND", "OIDC provider 不存在", status_code=404)
        if provider.version != request.expected_version:
            raise ApiError(
                "RESOURCE_VERSION_CONFLICT",
                "OIDC provider 已被其他请求修改",
                status_code=409,
                details={"current_version": provider.version},
            )

        changed_fields: list[str] = []
        for field_name, value in (
            ("name", request.name.strip() if request.name is not None else None),
            (
                "issuer_url",
                request.issuer_url.strip().rstrip("/") if request.issuer_url is not None else None,
            ),
            ("client_id", request.client_id.strip() if request.client_id is not None else None),
            ("enabled", request.enabled),
        ):
            if value is not None and getattr(provider, field_name) != value:
                setattr(provider, field_name, value)
                changed_fields.append(field_name)
        if request.scopes is not None:
            scopes = _normalize_scopes(request.scopes)
            if provider.scopes != scopes:
                provider.scopes = scopes
                changed_fields.append("scopes")
        if request.clear_client_secret_ref and provider.client_secret_ref is not None:
            provider.client_secret_ref = None
            changed_fields.append("client_secret_ref")
        elif request.client_secret_ref is not None:
            secret_ref = request.client_secret_ref.strip()
            if provider.client_secret_ref != secret_ref:
                provider.client_secret_ref = secret_ref
                changed_fields.append("client_secret_ref")

        if changed_fields:
            provider.version += 1
            provider.updated_at = utc_now()
        await self._record(
            AuditEvent(
                tenant_id=current_user.tenant_id,
                actor_id=current_user.id,
                action="identity.oidc.provider.updated",
                resource_type="oidc_provider",
                resource_id=provider.id,
                result="allowed",
                metadata={"changed_fields": changed_fields},
            ),
            audit_context=audit_context,
        )
        await self.repository.commit()
        return _provider_response(provider)

    async def test_provider(
        self,
        *,
        current_user: User,
        provider_id: UUID,
        audit_context: AuditContext | None,
    ) -> OidcProviderTestResponse:
        await self._require_admin(
            current_user=current_user,
            action="identity.oidc.provider.tested",
            resource_id=provider_id,
            audit_context=audit_context,
        )
        provider = await self.repository.get_oidc_provider(
            tenant_id=current_user.tenant_id,
            provider_id=provider_id,
        )
        if provider is None:
            raise ApiError("OIDC_PROVIDER_NOT_FOUND", "OIDC provider 不存在", status_code=404)
        provider_config = self._provider_config(provider)
        # End the read transaction before contacting the remote provider.
        await self.repository.commit()
        try:
            metadata = await self.provider_adapter.test_connection(provider_config)
        except Exception:
            record_identity_provider_operation(
                provider_type="oidc",
                operation="connection_test",
                outcome="failure",
            )
            await self._record(
                AuditEvent(
                    tenant_id=current_user.tenant_id,
                    actor_id=current_user.id,
                    action="identity.oidc.provider.tested",
                    resource_type="oidc_provider",
                    resource_id=provider.id,
                    result="denied",
                    risk_level="medium",
                    metadata={"connected": False},
                ),
                audit_context=audit_context,
            )
            await self.repository.commit()
            raise
        record_identity_provider_operation(
            provider_type="oidc",
            operation="connection_test",
            outcome="success",
        )
        await self._record(
            AuditEvent(
                tenant_id=current_user.tenant_id,
                actor_id=current_user.id,
                action="identity.oidc.provider.tested",
                resource_type="oidc_provider",
                resource_id=provider.id,
                result="allowed",
                metadata={"connected": True},
            ),
            audit_context=audit_context,
        )
        await self.repository.commit()
        return OidcProviderTestResponse(
            issuer=metadata.issuer,
            supports_logout=metadata.end_session_endpoint is not None,
        )

    async def start_login(
        self,
        *,
        tenant_slug: str,
        provider_slug: str,
        redirect_uri: str,
        redirect_path: str,
        audit_context: AuditContext | None,
    ) -> OidcStartResponse:
        tenant = await self.repository.get_tenant_by_slug(tenant_slug.strip())
        if tenant is None:
            raise ApiError("OIDC_PROVIDER_NOT_FOUND", "OIDC provider 不存在", status_code=404)
        provider = await self.repository.get_oidc_provider_by_slug(
            tenant_id=tenant.id,
            slug=provider_slug,
            enabled_only=True,
        )
        if provider is None:
            raise ApiError("OIDC_PROVIDER_NOT_FOUND", "OIDC provider 不存在", status_code=404)
        return await self._start_flow(
            provider=provider,
            purpose="login",
            user_id=None,
            redirect_uri=redirect_uri,
            redirect_path=redirect_path,
            audit_context=audit_context,
        )

    async def start_binding(
        self,
        *,
        current_user: User,
        provider_slug: str,
        redirect_uri: str,
        redirect_path: str,
        audit_context: AuditContext | None,
    ) -> OidcStartResponse:
        provider = await self.repository.get_oidc_provider_by_slug(
            tenant_id=current_user.tenant_id,
            slug=provider_slug,
            enabled_only=True,
        )
        if provider is None:
            raise ApiError("OIDC_PROVIDER_NOT_FOUND", "OIDC provider 不存在", status_code=404)
        return await self._start_flow(
            provider=provider,
            purpose="bind",
            user_id=current_user.id,
            redirect_uri=redirect_uri,
            redirect_path=redirect_path,
            audit_context=audit_context,
        )

    async def handle_callback(
        self,
        *,
        provider_slug: str,
        state: str,
        code: str,
        audit_context: AuditContext | None,
    ) -> OidcCallbackResult:
        now = utc_now()
        flow = await self.repository.consume_oidc_flow(
            state_hash=hash_token(state),
            now=now,
        )
        if flow is None:
            raise ApiError(
                "OIDC_STATE_INVALID",
                "OIDC 登录状态已失效",
                status_code=400,
            )
        provider = await self.repository.get_oidc_provider(
            tenant_id=flow.tenant_id,
            provider_id=flow.provider_id,
        )
        if provider is None or not provider.enabled or provider.slug != provider_slug:
            await self.repository.commit()
            raise ApiError(
                "OIDC_PROVIDER_NOT_FOUND",
                "OIDC provider 不存在",
                status_code=404,
            )

        # Consume and commit the one-time state before the remote token
        # exchange, so network latency never holds the database transaction.
        await self.repository.commit()
        try:
            identity = await self.provider_adapter.exchange_code(
                config=self._provider_config(provider),
                redirect_uri=flow.redirect_uri,
                code=code,
                code_verifier=flow.code_verifier,
            )
        except Exception:
            record_identity_provider_operation(
                provider_type="oidc",
                operation="token_exchange",
                outcome="failure",
            )
            raise
        if hash_token(identity.nonce) != flow.nonce_hash:
            record_identity_provider_operation(
                provider_type="oidc",
                operation="token_exchange",
                outcome="failure",
            )
            await self.repository.commit()
            raise ApiError(
                "OIDC_NONCE_INVALID",
                "OIDC 登录状态校验失败",
                status_code=400,
            )
        record_identity_provider_operation(
            provider_type="oidc",
            operation="token_exchange",
            outcome="success",
        )

        if flow.purpose == "bind":
            result = await self._complete_binding(
                flow=flow,
                provider=provider,
                identity=identity,
                audit_context=audit_context,
            )
            return OidcCallbackResult(
                redirect_path=flow.redirect_path,
                issued_session=None,
                linked=result,
            )
        issued_session = await self._complete_login(
            flow=flow,
            provider=provider,
            identity=identity,
            audit_context=audit_context,
        )
        return OidcCallbackResult(
            redirect_path=flow.redirect_path,
            issued_session=issued_session,
            linked=False,
        )

    async def list_links(self, *, current_user: User) -> OidcIdentityLinkListResponse:
        rows = await self.repository.list_oidc_links_for_user(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
        )
        return OidcIdentityLinkListResponse(
            items=[
                OidcIdentityLinkResponse(
                    id=link.id,
                    provider_id=provider.id,
                    provider_slug=provider.slug,
                    provider_name=provider.name,
                    issuer=link.issuer,
                    subject=link.subject,
                    email=link.email,
                    display_name=link.display_name,
                    created_at=link.created_at,
                    last_login_at=link.last_login_at,
                )
                for link, provider in rows
            ]
        )

    async def unlink(
        self,
        *,
        current_user: User,
        link_id: UUID,
        audit_context: AuditContext | None,
    ) -> OidcIdentityUnlinkResponse:
        link = await self.repository.get_owned_oidc_link(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            link_id=link_id,
        )
        if link is None:
            raise ApiError("OIDC_LINK_NOT_FOUND", "OIDC 账号绑定不存在", status_code=404)
        links = await self.repository.list_oidc_links_for_user(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
        )
        local_password_enabled = bool(getattr(current_user, "local_password_enabled", True))
        if not local_password_enabled and len(links) <= 1:
            raise ApiError(
                "OIDC_LAST_LOGIN_METHOD",
                "至少保留一种可用登录方式",
                status_code=409,
            )
        await self.repository.delete_oidc_link(link)
        await self._record(
            AuditEvent(
                tenant_id=current_user.tenant_id,
                actor_id=current_user.id,
                action="identity.oidc.account.unlinked",
                resource_type="oidc_identity_link",
                resource_id=link.id,
                result="allowed",
                risk_level="medium",
                metadata={"provider_id": str(link.provider_id)},
            ),
            audit_context=audit_context,
        )
        await self.repository.commit()
        record_identity_provider_operation(
            provider_type="oidc",
            operation="unlink",
            outcome="success",
        )
        return OidcIdentityUnlinkResponse(removed_link_id=link.id)

    async def build_logout(
        self,
        *,
        current_user: User,
        provider_slug: str,
        post_logout_redirect_uri: str,
        audit_context: AuditContext | None,
    ) -> OidcLogoutResponse:
        provider = await self.repository.get_oidc_provider_by_slug(
            tenant_id=current_user.tenant_id,
            slug=provider_slug,
            enabled_only=True,
        )
        if provider is None:
            raise ApiError("OIDC_PROVIDER_NOT_FOUND", "OIDC provider 不存在", status_code=404)
        link = await self.repository.get_oidc_link_for_user_provider(
            tenant_id=current_user.tenant_id,
            provider_id=provider.id,
            user_id=current_user.id,
        )
        if link is None:
            raise ApiError("OIDC_LINK_NOT_FOUND", "OIDC 账号绑定不存在", status_code=404)
        provider_config = self._provider_config(provider)
        await self.repository.commit()
        try:
            logout_url = await self.provider_adapter.build_logout_url(
                config=provider_config,
                post_logout_redirect_uri=post_logout_redirect_uri,
                state=secrets.token_urlsafe(32),
            )
        except Exception:
            record_identity_provider_operation(
                provider_type="oidc",
                operation="logout",
                outcome="failure",
            )
            raise
        record_identity_provider_operation(
            provider_type="oidc",
            operation="logout",
            outcome="success" if logout_url is not None else "unsupported",
        )
        await self._record(
            AuditEvent(
                tenant_id=current_user.tenant_id,
                actor_id=current_user.id,
                action="identity.oidc.logout.started",
                resource_type="oidc_provider",
                resource_id=provider.id,
                result="allowed",
                metadata={"provider_logout_supported": logout_url is not None},
            ),
            audit_context=audit_context,
        )
        await self.repository.commit()
        return OidcLogoutResponse(logout_url=logout_url)

    async def _start_flow(
        self,
        *,
        provider: OidcProvider,
        purpose: str,
        user_id: UUID | None,
        redirect_uri: str,
        redirect_path: str,
        audit_context: AuditContext | None,
    ) -> OidcStartResponse:
        safe_redirect_path = _validate_redirect_path(
            redirect_path,
            allowed_paths=_allowed_redirect_paths(self.settings),
        )
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)
        ttl_seconds = int(getattr(self.settings, "oidc_state_ttl_seconds", 600))
        provider_config = self._provider_config(provider)
        await self.repository.commit()
        flow = OidcFlow(
            tenant_id=provider.tenant_id,
            provider_id=provider.id,
            purpose=purpose,
            user_id=user_id,
            state_hash=hash_token(state),
            nonce_hash=hash_token(nonce),
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
            redirect_path=safe_redirect_path,
            expires_at=utc_now() + timedelta(seconds=ttl_seconds),
        )
        try:
            authorization_url = await self.provider_adapter.build_authorization_url(
                config=provider_config,
                redirect_uri=redirect_uri,
                state=state,
                nonce=nonce,
                code_challenge=create_pkce_challenge(code_verifier),
            )
        except Exception:
            record_identity_provider_operation(
                provider_type="oidc",
                operation="authorization",
                outcome="failure",
            )
            raise
        record_identity_provider_operation(
            provider_type="oidc",
            operation="authorization",
            outcome="success",
        )
        await self.repository.create_oidc_flow(flow)
        await self._record(
            AuditEvent(
                tenant_id=provider.tenant_id,
                actor_id=user_id,
                action=f"identity.oidc.{purpose}.started",
                resource_type="oidc_provider",
                resource_id=provider.id,
                result="allowed",
                metadata={"purpose": purpose},
            ),
            audit_context=audit_context,
        )
        await self.repository.commit()
        return OidcStartResponse(authorization_url=authorization_url)

    async def _complete_binding(
        self,
        *,
        flow: OidcFlow,
        provider: OidcProvider,
        identity: OidcIdentity,
        audit_context: AuditContext | None,
    ) -> bool:
        if flow.user_id is None:
            raise ApiError("OIDC_BINDING_INVALID", "OIDC 账号绑定状态无效", status_code=400)
        user = await self.repository.get_user(
            tenant_id=flow.tenant_id,
            user_id=flow.user_id,
        )
        if user is None or not user.is_active:
            raise ApiError("AUTH_REQUIRED", "认证已失效", status_code=401)
        existing_subject = await self.repository.get_oidc_link_by_subject(
            tenant_id=flow.tenant_id,
            issuer=identity.issuer,
            subject=identity.subject,
        )
        if existing_subject is not None and existing_subject.user_id != user.id:
            await self.repository.commit()
            raise ApiError(
                "OIDC_SUBJECT_ALREADY_BOUND",
                "该 OIDC 身份已绑定其他账号",
                status_code=409,
            )
        existing_provider = await self.repository.get_oidc_link_for_user_provider(
            tenant_id=flow.tenant_id,
            provider_id=provider.id,
            user_id=user.id,
        )
        if existing_provider is not None:
            if (
                existing_provider.issuer == identity.issuer
                and existing_provider.subject == identity.subject
            ):
                await self.repository.commit()
                return False
            await self.repository.commit()
            raise ApiError(
                "OIDC_PROVIDER_ALREADY_BOUND",
                "当前账号已绑定该 OIDC provider",
                status_code=409,
            )

        link = OidcIdentityLink(
            tenant_id=flow.tenant_id,
            provider_id=provider.id,
            user_id=user.id,
            issuer=identity.issuer,
            subject=identity.subject,
            email=identity.email,
            display_name=identity.display_name,
        )
        try:
            await self.repository.create_oidc_link(link)
            await self._record(
                AuditEvent(
                    tenant_id=flow.tenant_id,
                    actor_id=user.id,
                    action="identity.oidc.account.bound",
                    resource_type="oidc_identity_link",
                    resource_id=link.id,
                    result="allowed",
                    risk_level="medium",
                    metadata={"provider_id": str(provider.id)},
                ),
                audit_context=audit_context,
            )
            await self.repository.commit()
        except IntegrityError as exc:
            await self.repository.rollback()
            raise ApiError(
                "OIDC_BINDING_CONFLICT",
                "OIDC 账号绑定冲突",
                status_code=409,
            ) from exc
        record_identity_provider_operation(
            provider_type="oidc",
            operation="bind",
            outcome="success",
        )
        return True

    async def _complete_login(
        self,
        *,
        flow: OidcFlow,
        provider: OidcProvider,
        identity: OidcIdentity,
        audit_context: AuditContext | None,
    ) -> IssuedSession:
        link = await self.repository.get_oidc_link_by_subject(
            tenant_id=flow.tenant_id,
            issuer=identity.issuer,
            subject=identity.subject,
        )
        if link is None or link.provider_id != provider.id:
            await self.repository.commit()
            raise ApiError(
                "OIDC_ACCOUNT_NOT_LINKED",
                "OIDC 身份尚未绑定本地账号",
                status_code=403,
            )
        user = await self.repository.get_user(
            tenant_id=flow.tenant_id,
            user_id=link.user_id,
        )
        if user is None or not user.is_active:
            await self.repository.commit()
            raise ApiError("AUTH_REQUIRED", "认证已失效", status_code=401)
        issued_session = await self.auth_service.issue_external_session(
            user=user,
            audit_context=audit_context,
            auth_method="oidc",
            oidc_provider_id=provider.id,
        )
        link.last_login_at = utc_now()
        link.email = identity.email
        link.display_name = identity.display_name
        await self._record(
            AuditEvent(
                tenant_id=flow.tenant_id,
                actor_id=user.id,
                action="identity.oidc.login",
                resource_type="oidc_provider",
                resource_id=provider.id,
                result="allowed",
                metadata={"link_id": str(link.id)},
            ),
            audit_context=audit_context,
        )
        await self.repository.commit()
        record_identity_provider_operation(
            provider_type="oidc",
            operation="login",
            outcome="success",
        )
        return issued_session

    def _provider_config(self, provider: OidcProvider) -> OidcProviderConfig:
        return OidcProviderConfig(
            id=provider.id,
            issuer_url=provider.issuer_url,
            client_id=provider.client_id,
            client_secret=self.secret_resolver.resolve(provider.client_secret_ref),
            scopes=tuple(provider.scopes),
        )

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
        await self._record(
            AuditEvent(
                tenant_id=current_user.tenant_id,
                actor_id=current_user.id,
                action=action,
                resource_type="identity",
                resource_id=resource_id,
                result="denied",
                risk_level="medium",
                metadata={"reason": "super_admin_required"},
            ),
            audit_context=audit_context,
        )
        await self.repository.commit()
        raise ApiError("ADMIN_REQUIRED", "需要系统管理员权限", status_code=403)

    async def _record(
        self,
        event: AuditEvent,
        *,
        audit_context: AuditContext | None,
    ) -> None:
        if self.audit_service is None:
            return
        await self.audit_service.record(
            event=event,
            context=audit_context or AuditContext(),
        )


def _provider_response(provider: OidcProvider) -> OidcProviderResponse:
    return OidcProviderResponse(
        id=provider.id,
        tenant_id=provider.tenant_id,
        slug=provider.slug,
        name=provider.name,
        issuer_url=provider.issuer_url,
        client_id=provider.client_id,
        client_secret_configured=provider.client_secret_ref is not None,
        scopes=list(provider.scopes),
        enabled=provider.enabled,
        version=provider.version,
        created_at=provider.created_at,
        updated_at=provider.updated_at,
    )


def _normalize_scopes(scopes: list[str]) -> list[str]:
    normalized = list(dict.fromkeys(scope.strip() for scope in scopes if scope.strip()))
    if "openid" not in normalized:
        normalized.insert(0, "openid")
    return normalized


def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _allowed_redirect_paths(settings: Settings) -> list[str]:
    configured = getattr(
        settings,
        "identity_allowed_redirect_paths",
        ["/", "/account", "/auth/oidc/callback", "/admin/identity"],
    )
    return [str(item) for item in configured]


def _validate_redirect_path(value: str, *, allowed_paths: list[str]) -> str:
    parsed = urlsplit(value.strip())
    if (
        not parsed.path.startswith("/")
        or parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
    ):
        raise ApiError(
            "IDENTITY_REDIRECT_INVALID",
            "身份登录返回路径不合法",
            status_code=422,
        )
    if parsed.path not in allowed_paths:
        raise ApiError(
            "IDENTITY_REDIRECT_INVALID",
            "身份登录返回路径未获允许",
            status_code=422,
        )
    return parsed.path
