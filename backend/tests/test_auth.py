from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.errors import ApiError
from app.core.config import Settings, get_settings
from app.core.security import hash_token
from app.db.base import Base
from app.db.session import get_db_session
from app.main import create_app
from app.modules.auth.models import RefreshToken
from app.modules.auth.repository import AuthRepository
from app.modules.auth.service import AuthService


@pytest.fixture
def auth_settings() -> Settings:
    return Settings(
        environment="test",
        secret_key="test-secret",
        trusted_hosts=["testserver"],
        cors_origins=[],
        database_url="sqlite+aiosqlite:///:memory:",
        admin_password="admin-password",
        access_token_minutes=15,
        refresh_token_days=30,
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


@pytest_asyncio.fixture
async def session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as db_session:
        yield db_session


@pytest_asyncio.fixture
async def auth_service(session: AsyncSession, auth_settings: Settings) -> AuthService:
    return AuthService(repository=AuthRepository(session), settings=auth_settings)


@pytest_asyncio.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
    auth_settings: Settings,
) -> AsyncIterator[AsyncClient]:
    app = create_app(auth_settings)

    async def override_get_db_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as db_session:
            yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_settings] = lambda: auth_settings

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client


@pytest.mark.asyncio
async def test_seed_admin_is_idempotent(auth_service: AuthService) -> None:
    first_result = await auth_service.seed_admin()
    second_result = await auth_service.seed_admin()

    assert first_result.tenant_created is True
    assert first_result.user_created is True
    assert second_result.tenant_created is False
    assert second_result.user_created is False


@pytest.mark.asyncio
async def test_login_and_refresh_rotate_token(auth_service: AuthService) -> None:
    await auth_service.seed_admin()
    login_response = await auth_service.login(
        tenant_slug="default",
        username="admin",
        password="admin-password",
    )

    refresh_response = await auth_service.refresh(refresh_token=login_response.refresh_token)

    assert login_response.access_token
    assert refresh_response.access_token
    assert refresh_response.refresh_token != login_response.refresh_token


@pytest.mark.asyncio
async def test_reusing_rotated_refresh_token_revokes_family(
    auth_service: AuthService,
    session: AsyncSession,
) -> None:
    await auth_service.seed_admin()
    login_response = await auth_service.login(
        tenant_slug="default",
        username="admin",
        password="admin-password",
    )
    refresh_response = await auth_service.refresh(refresh_token=login_response.refresh_token)

    with pytest.raises(ApiError) as exc_info:
        await auth_service.refresh(refresh_token=login_response.refresh_token)

    assert exc_info.value.code == "REFRESH_TOKEN_REUSED"

    new_token_hash = hash_token(refresh_response.refresh_token)
    stored_new_token = await AuthRepository(session).get_refresh_token_by_hash(new_token_hash)
    assert isinstance(stored_new_token, RefreshToken)
    assert stored_new_token.revoked_reason == "reuse_detected"


@pytest.mark.asyncio
async def test_auth_api_login_refresh_and_me(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    auth_settings: Settings,
) -> None:
    async with session_factory() as seed_session:
        service = AuthService(
            repository=AuthRepository(seed_session),
            settings=auth_settings,
        )
        await service.seed_admin()

    login_response = await client.post(
        "/api/v1/auth/login",
        json={
            "tenant_slug": "default",
            "username": "admin",
            "password": "admin-password",
        },
    )
    assert login_response.status_code == 200
    login_payload = login_response.json()

    me_response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {login_payload['access_token']}"},
    )
    assert me_response.status_code == 200
    assert me_response.json()["username"] == "admin"

    refresh_response = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": login_payload["refresh_token"]},
    )
    assert refresh_response.status_code == 200
    assert refresh_response.json()["refresh_token"] != login_payload["refresh_token"]
