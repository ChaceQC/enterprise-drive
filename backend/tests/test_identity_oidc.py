from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.errors import ApiError
from app.core.config import Settings
from app.core.security import hash_password
from app.db.base import Base
from app.infrastructure.identity.base import (
    OidcIdentity,
    OidcProviderConfig,
    OidcProviderMetadata,
)
from app.infrastructure.identity.secrets import EnvironmentSecretResolver
from app.modules.auth.models import AuthSession
from app.modules.auth.repository import AuthRepository
from app.modules.auth.service import AuthService
from app.modules.identity.oidc_service import OidcIdentityService
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.schemas import OidcProviderCreateRequest


class FakeSecretResolver:
    def resolve(self, secret_ref: str | None) -> str | None:
        return "oidc-client-secret" if secret_ref else None


class FakeOidcAdapter:
    def __init__(self) -> None:
        self.nonce = ""
        self.code_verifier = ""
        self.state = ""
        self.code_challenge = ""
        self.identity = OidcIdentity(
            issuer="https://issuer.example",
            subject="subject-1",
            nonce="",
            email="user@example.com",
            email_verified=True,
            display_name="OIDC User",
            preferred_username="oidc-user",
        )

    async def test_connection(self, config: OidcProviderConfig) -> OidcProviderMetadata:
        return OidcProviderMetadata(
            issuer=config.issuer_url,
            authorization_endpoint=f"{config.issuer_url}/authorize",
            token_endpoint=f"{config.issuer_url}/token",
            jwks_uri=f"{config.issuer_url}/jwks",
            end_session_endpoint=f"{config.issuer_url}/logout",
        )

    async def build_authorization_url(
        self,
        *,
        config: OidcProviderConfig,
        redirect_uri: str,
        state: str,
        nonce: str,
        code_challenge: str,
    ) -> str:
        self.state = state
        self.nonce = nonce
        self.code_verifier = code_challenge
        self.code_challenge = code_challenge
        return f"https://issuer.example/authorize?state={state}&code_challenge={code_challenge}"

    async def exchange_code(
        self,
        *,
        config: OidcProviderConfig,
        redirect_uri: str,
        code: str,
        code_verifier: str,
    ) -> OidcIdentity:
        return self.identity.__class__(
            issuer=self.identity.issuer,
            subject=self.identity.subject,
            nonce=self.nonce,
            email=self.identity.email,
            email_verified=self.identity.email_verified,
            display_name=self.identity.display_name,
            preferred_username=self.identity.preferred_username,
        )

    async def build_logout_url(
        self,
        *,
        config: OidcProviderConfig,
        post_logout_redirect_uri: str,
        state: str,
    ) -> str | None:
        return f"{config.issuer_url}/logout?state={state}"


def test_environment_secret_resolver_rejects_blank_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = EnvironmentSecretResolver()
    monkeypatch.setenv("EMPTY_IDENTITY_SECRET", "   ")
    with pytest.raises(ApiError, match="身份源凭据不可用"):
        resolver.resolve("env:EMPTY_IDENTITY_SECRET")

    monkeypatch.setenv("EMPTY_IDENTITY_SECRET", "resolved-secret")
    assert resolver.resolve("env:EMPTY_IDENTITY_SECRET") == "resolved-secret"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        environment="test",
        secret_key="test-secret",
        trusted_hosts=["testserver"],
        cors_origins=[],
        database_url="sqlite+aiosqlite:///:memory:",
        session_days=30,
        rate_limit_enabled=False,
    )


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _seed_user(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    username: str,
    is_super_admin: bool = False,
) -> tuple[UUID, UUID]:
    async with session_factory() as session:
        repository = AuthRepository(session)
        tenant = await repository.create_tenant(slug="default", name="Default")
        user = await repository.create_user(
            tenant_id=tenant.id,
            username=username,
            email=f"{username}@example.com",
            display_name=username,
            password_hash=hash_password("local-password"),
            is_super_admin=is_super_admin,
        )
        await repository.commit()
        return tenant.id, user.id


async def _service(
    session: AsyncSession,
    settings: Settings,
    adapter: FakeOidcAdapter,
) -> OidcIdentityService:
    repository = IdentityRepository(session)
    return OidcIdentityService(
        repository=repository,
        auth_service=AuthService(repository=AuthRepository(session), settings=settings),
        provider_adapter=adapter,
        secret_resolver=FakeSecretResolver(),
        settings=settings,
        audit_service=None,
    )


@pytest.mark.asyncio
async def test_oidc_binding_then_login_is_one_time_and_uses_opaque_session(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    tenant_id, user_id = await _seed_user(session_factory, username="alice", is_super_admin=True)
    adapter = FakeOidcAdapter()
    async with session_factory() as session:
        service = await _service(session, settings, adapter)
        provider = await service.create_provider(
            current_user=(
                await IdentityRepository(session).get_user(
                    tenant_id=tenant_id,
                    user_id=user_id,
                )
            ),
            request=OidcProviderCreateRequest(
                slug="corp",
                name="Corp",
                issuer_url="https://issuer.example",
                client_id="client",
                client_secret_ref="env:OIDC_SECRET",
            ),
            audit_context=None,
        )
        start = await service.start_binding(
            current_user=(
                await IdentityRepository(session).get_user(
                    tenant_id=tenant_id,
                    user_id=user_id,
                )
            ),
            provider_slug=provider.slug,
            redirect_uri="https://drive.example/api/v1/auth/oidc/corp/callback",
            redirect_path="/account",
            audit_context=None,
        )
        assert "state=" in start.authorization_url
        bound = await service.handle_callback(
            provider_slug="corp",
            state=adapter.state,
            code="code-1",
            audit_context=None,
        )
        assert bound.linked is True

        start_login = await service.start_login(
            tenant_slug="default",
            provider_slug="corp",
            redirect_uri="https://drive.example/api/v1/auth/oidc/corp/callback",
            redirect_path="/",
            audit_context=None,
        )
        logged_in = await service.handle_callback(
            provider_slug="corp",
            state=adapter.state,
            code="code-2",
            audit_context=None,
        )
        assert logged_in.issued_session is not None
        assert logged_in.redirect_path == "/"
        assert start_login.authorization_url

        sessions = list(
            (
                await session.execute(
                    select(AuthSession).where(
                        AuthSession.tenant_id == tenant_id,
                        AuthSession.user_id == user_id,
                    )
                )
            ).scalars()
        )
        assert len(sessions) == 1
        assert sessions[0].auth_method == "oidc"

        with pytest.raises(ApiError, match="OIDC 登录状态已失效"):
            await service.handle_callback(
                provider_slug="corp",
                state=adapter.state,
                code="code-replay",
                audit_context=None,
            )


@pytest.mark.asyncio
async def test_oidc_subject_cannot_be_bound_to_two_users(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    tenant_id, first_user_id = await _seed_user(
        session_factory,
        username="first",
        is_super_admin=True,
    )
    async with session_factory() as session:
        repository = AuthRepository(session)
        first_user = await repository.get_user_by_id(tenant_id=tenant_id, user_id=first_user_id)
        assert first_user is not None
        second_user = await repository.create_user(
            tenant_id=tenant_id,
            username="second",
            email="second@example.com",
            display_name="second",
            password_hash=hash_password("local-password"),
        )
        await repository.commit()
        adapter = FakeOidcAdapter()
        service = await _service(session, settings, adapter)
        provider = await service.create_provider(
            current_user=first_user,
            request=OidcProviderCreateRequest(
                slug="corp",
                name="Corp",
                issuer_url="https://issuer.example",
                client_id="client",
            ),
            audit_context=None,
        )
        await service.start_binding(
            current_user=first_user,
            provider_slug=provider.slug,
            redirect_uri="https://drive.example/callback",
            redirect_path="/account",
            audit_context=None,
        )
        await service.handle_callback(
            provider_slug=provider.slug,
            state=adapter.state,
            code="first",
            audit_context=None,
        )
        await service.start_binding(
            current_user=second_user,
            provider_slug=provider.slug,
            redirect_uri="https://drive.example/callback",
            redirect_path="/account",
            audit_context=None,
        )
        with pytest.raises(ApiError, match="该 OIDC 身份已绑定其他账号"):
            await service.handle_callback(
                provider_slug=provider.slug,
                state=adapter.state,
                code="second",
                audit_context=None,
            )


@pytest.mark.asyncio
async def test_oidc_redirect_path_is_allowlisted(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    tenant_id, user_id = await _seed_user(session_factory, username="admin", is_super_admin=True)
    async with session_factory() as session:
        service = await _service(session, settings, FakeOidcAdapter())
        provider = await service.create_provider(
            current_user=(
                await IdentityRepository(session).get_user(
                    tenant_id=tenant_id,
                    user_id=user_id,
                )
            ),
            request=OidcProviderCreateRequest(
                slug="corp",
                name="Corp",
                issuer_url="https://issuer.example",
                client_id="client",
            ),
            audit_context=None,
        )
        user = await IdentityRepository(session).get_user(tenant_id=tenant_id, user_id=user_id)
        assert user is not None
        with pytest.raises(ApiError, match="身份登录返回路径"):
            await service.start_binding(
                current_user=user,
                provider_slug=provider.slug,
                redirect_uri="https://drive.example/callback",
                redirect_path="https://evil.example",
                audit_context=None,
            )
