from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_db_session
from app.main import create_app
from app.modules.audit.models import AuditLog, OutboxEvent
from app.modules.auth.repository import AuthRepository
from app.modules.auth.service import AuthService
from app.modules.file.models import Node
from app.modules.space.models import Space


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


@pytest.mark.asyncio
async def test_create_space_creates_root_node_and_audit(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)

    response = await client.post(
        "/api/v1/spaces",
        headers={"Authorization": f"Bearer {token}", "X-Request-ID": "req_space_create"},
        json={"slug": "team-docs", "name": "团队资料", "space_type": "team"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["slug"] == "team-docs"
    assert payload["name"] == "团队资料"
    assert payload["root_node_id"]

    async with session_factory() as session:
        space = (await session.execute(select(Space))).scalar_one()
        root_node = (await session.execute(select(Node))).scalar_one()
        audit_logs = (
            (await session.execute(select(AuditLog).order_by(AuditLog.created_at, AuditLog.action)))
            .scalars()
            .all()
        )
        outbox_events = (await session.execute(select(OutboxEvent))).scalars().all()

    assert root_node.space_id == space.id
    assert root_node.parent_id is None
    assert root_node.node_type == "folder"
    assert root_node.name == "root"
    assert [log.action for log in audit_logs] == ["auth.login", "space.created"]
    assert audit_logs[-1].request_id == "req_space_create"
    assert "audit.space.created" in {event.event_type for event in outbox_events}


@pytest.mark.asyncio
async def test_duplicate_space_slug_returns_conflict(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    request_payload = {"slug": "team-docs", "name": "团队资料", "space_type": "team"}

    first_response = await client.post(
        "/api/v1/spaces",
        headers={"Authorization": f"Bearer {token}"},
        json=request_payload,
    )
    second_response = await client.post(
        "/api/v1/spaces",
        headers={"Authorization": f"Bearer {token}"},
        json=request_payload,
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 409
    assert second_response.json()["code"] == "SPACE_SLUG_EXISTS"


@pytest.mark.asyncio
async def test_create_folder_and_list_children(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space_response = await client.post(
        "/api/v1/spaces",
        headers={"Authorization": f"Bearer {token}"},
        json={"slug": "product", "name": "产品文档", "space_type": "team"},
    )
    space_payload = space_response.json()

    folder_response = await client.post(
        "/api/v1/files/folders",
        headers={"Authorization": f"Bearer {token}", "X-Request-ID": "req_folder_create"},
        json={
            "space_id": space_payload["id"],
            "parent_id": space_payload["root_node_id"],
            "name": "  需求文档  ",
        },
    )
    list_response = await client.get(
        "/api/v1/files",
        headers={"Authorization": f"Bearer {token}"},
        params={"space_id": space_payload["id"], "parent_id": space_payload["root_node_id"]},
    )

    assert folder_response.status_code == 201
    folder_payload = folder_response.json()
    assert folder_payload["name"] == "需求文档"
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()["items"]] == [folder_payload["id"]]

    async with session_factory() as session:
        folder_audit = (
            await session.execute(select(AuditLog).where(AuditLog.action == "file.folder.created"))
        ).scalar_one()
    assert folder_audit.request_id == "req_folder_create"


@pytest.mark.asyncio
async def test_duplicate_folder_name_returns_conflict(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space_response = await client.post(
        "/api/v1/spaces",
        headers={"Authorization": f"Bearer {token}"},
        json={"slug": "design", "name": "设计文档", "space_type": "team"},
    )
    space_payload = space_response.json()
    request_payload = {
        "space_id": space_payload["id"],
        "parent_id": space_payload["root_node_id"],
        "name": "原型",
    }

    first_response = await client.post(
        "/api/v1/files/folders",
        headers={"Authorization": f"Bearer {token}"},
        json=request_payload,
    )
    second_response = await client.post(
        "/api/v1/files/folders",
        headers={"Authorization": f"Bearer {token}"},
        json=request_payload,
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 409
    assert second_response.json()["code"] == "NODE_NAME_EXISTS"


@pytest.mark.asyncio
async def test_invalid_folder_name_is_rejected(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space_response = await client.post(
        "/api/v1/spaces",
        headers={"Authorization": f"Bearer {token}"},
        json={"slug": "security", "name": "安全文档", "space_type": "team"},
    )
    space_payload = space_response.json()

    response = await client.post(
        "/api/v1/files/folders",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "space_id": space_payload["id"],
            "parent_id": space_payload["root_node_id"],
            "name": "../secret",
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "NODE_NAME_INVALID"


@pytest.mark.asyncio
async def test_file_list_uses_owner_boundary_until_permission_module(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    admin_token = await login(client)
    space_response = await client.post(
        "/api/v1/spaces",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"slug": "private", "name": "私有空间", "space_type": "team"},
    )
    await create_second_user(session_factory)
    member_token = await login(client, username="member", password="member-password")

    response = await client.get(
        "/api/v1/files",
        headers={"Authorization": f"Bearer {member_token}"},
        params={"space_id": space_response.json()["id"]},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "SPACE_NOT_FOUND"
