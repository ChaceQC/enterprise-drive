from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.deps import get_rate_limiter, get_search_index_adapter, get_storage_adapter
from app.core.config import Settings, get_settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_db_session
from app.infrastructure.rate_limit.testing import InMemoryFixedWindowRateLimiter
from app.infrastructure.search.testing import InMemorySearchIndexAdapter
from app.infrastructure.storage.testing import InMemoryStorageAdapter
from app.main import create_app
from app.modules.auth.models import User
from app.modules.auth.repository import AuthRepository
from app.modules.auth.service import AuthService
from app.modules.permission.constants import SPACE_ROLE_VIEWER
from app.modules.permission.models import SpaceMember


@pytest.fixture
def settings() -> Settings:
    return Settings(
        environment="test",
        secret_key="test-secret",
        trusted_hosts=["testserver"],
        cors_origins=[],
        database_url="sqlite+aiosqlite:///:memory:",
        admin_password="admin-password",
        session_days=30,
        rate_limit_enabled=False,
    )


@pytest.fixture
def storage_adapter() -> InMemoryStorageAdapter:
    return InMemoryStorageAdapter()


@pytest.fixture
def search_index_adapter() -> InMemorySearchIndexAdapter:
    return InMemorySearchIndexAdapter()


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
async def client(
    request: pytest.FixtureRequest,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    storage_adapter: InMemoryStorageAdapter,
) -> AsyncIterator[AsyncClient]:
    app = create_app(settings)
    rate_limiter = InMemoryFixedWindowRateLimiter()
    search_adapter = (
        request.getfixturevalue("search_index_adapter")
        if "search_index_adapter" in request.fixturenames
        else InMemorySearchIndexAdapter()
    )

    async def override_get_db_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as db_session:
            yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_storage_adapter] = lambda: storage_adapter
    app.dependency_overrides[get_search_index_adapter] = lambda: search_adapter
    app.dependency_overrides[get_rate_limiter] = lambda: rate_limiter
    app.state.storage_adapter = storage_adapter
    app.state.search_index_adapter = search_adapter
    app.state.rate_limiter = rate_limiter

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client


async def seed_admin(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    async with session_factory() as session:
        await AuthService(repository=AuthRepository(session), settings=settings).seed_admin()


async def login(
    client: AsyncClient,
    *,
    username: str = "admin",
    password: str = "admin-password",
) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"tenant_slug": "default", "username": username, "password": password},
    )
    assert response.status_code == 200
    csrf_token = response.cookies.get("drive_csrf")
    assert csrf_token is not None
    return csrf_token


async def create_second_user(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    password: str = "member-password",
) -> UUID:
    async with session_factory() as session:
        repository = AuthRepository(session)
        tenant = await repository.get_tenant_by_slug("default")
        assert tenant is not None
        user = await repository.create_user(
            tenant_id=tenant.id,
            username="member",
            email="member@example.com",
            display_name="普通成员",
            password_hash=hash_password(password),
        )
        await repository.commit()
        return user.id


async def add_space_member(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: str,
    space_id: str,
    username: str = "member",
    role: str = SPACE_ROLE_VIEWER,
) -> None:
    async with session_factory() as session:
        user = (
            await session.execute(
                select(User).where(
                    User.tenant_id == UUID(tenant_id),
                    User.username == username,
                )
            )
        ).scalar_one()
        session.add(
            SpaceMember(
                tenant_id=user.tenant_id,
                space_id=UUID(space_id),
                user_id=user.id,
                role=role,
                created_by=None,
            )
        )
        await session.commit()


async def create_space(
    client: AsyncClient,
    token: str,
    *,
    slug: str,
    name: str = "测试空间",
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/spaces",
        headers={"X-CSRF-Token": token},
        json={"slug": slug, "name": name, "space_type": "team"},
    )
    assert response.status_code == 201
    return dict(response.json())


async def create_folder(
    client: AsyncClient,
    token: str,
    *,
    space_id: str,
    parent_id: str,
    name: str,
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/files/folders",
        headers={"X-CSRF-Token": token},
        json={"space_id": space_id, "parent_id": parent_id, "name": name},
    )
    assert response.status_code == 201
    return dict(response.json())
