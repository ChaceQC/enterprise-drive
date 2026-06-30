from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_db_session
from app.main import create_app
from app.modules.auth.repository import AuthRepository
from app.modules.auth.service import AuthService


@pytest.fixture
def settings() -> Settings:
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
async def client(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> AsyncIterator[AsyncClient]:
    app = create_app(settings)

    async def override_get_db_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as db_session:
            yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_settings] = lambda: settings

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
    return str(response.json()["access_token"])


async def create_second_user(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    password: str = "member-password",
) -> None:
    async with session_factory() as session:
        repository = AuthRepository(session)
        tenant = await repository.get_tenant_by_slug("default")
        assert tenant is not None
        await repository.create_user(
            tenant_id=tenant.id,
            username="member",
            email="member@example.com",
            display_name="普通成员",
            password_hash=hash_password(password),
        )
        await repository.commit()


async def create_space(
    client: AsyncClient,
    token: str,
    *,
    slug: str,
    name: str = "测试空间",
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/spaces",
        headers={"Authorization": f"Bearer {token}"},
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
        headers={"Authorization": f"Bearer {token}"},
        json={"space_id": space_id, "parent_id": parent_id, "name": name},
    )
    assert response.status_code == 201
    return dict(response.json())
