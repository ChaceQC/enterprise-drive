from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.modules.audit.models import AuditLog, OutboxEvent
from app.modules.file.models import Node
from app.modules.quota.models import QuotaAccount
from app.modules.space.models import Space
from tests.helpers import (
    client as client,
)
from tests.helpers import (
    create_second_user,
    login,
    seed_admin,
)
from tests.helpers import (
    session_factory as session_factory,
)
from tests.helpers import (
    settings as settings,
)
from tests.helpers import (
    storage_adapter as storage_adapter,
)


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
        headers={"X-CSRF-Token": token, "X-Request-ID": "req_space_create"},
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
        quota_account = (await session.execute(select(QuotaAccount))).scalar_one()
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
    assert quota_account.tenant_id == space.tenant_id
    assert quota_account.owner_type == "space"
    assert quota_account.owner_id == space.id
    assert quota_account.limit_bytes == settings.default_space_quota_bytes
    assert quota_account.used_bytes == 0
    assert [log.action for log in audit_logs] == ["auth.login", "space.created"]
    assert audit_logs[-1].request_id == "req_space_create"
    assert "audit.space.created" in {event.event_type for event in outbox_events}


@pytest.mark.asyncio
async def test_space_mutation_requires_csrf_header(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    request_payload = {"slug": "csrf-check", "name": "CSRF 检查", "space_type": "team"}

    missing_csrf_response = await client.post("/api/v1/spaces", json=request_payload)

    assert missing_csrf_response.status_code == 403
    assert missing_csrf_response.json()["code"] == "CSRF_TOKEN_INVALID"

    success_response = await client.post(
        "/api/v1/spaces",
        headers={"X-CSRF-Token": token},
        json=request_payload,
    )

    assert success_response.status_code == 201


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
        headers={"X-CSRF-Token": token},
        json=request_payload,
    )
    second_response = await client.post(
        "/api/v1/spaces",
        headers={"X-CSRF-Token": token},
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
        headers={"X-CSRF-Token": token},
        json={"slug": "product", "name": "产品文档", "space_type": "team"},
    )
    space_payload = space_response.json()

    folder_response = await client.post(
        "/api/v1/files/folders",
        headers={"X-CSRF-Token": token, "X-Request-ID": "req_folder_create"},
        json={
            "space_id": space_payload["id"],
            "parent_id": space_payload["root_node_id"],
            "name": "  需求文档  ",
        },
    )
    list_response = await client.get(
        "/api/v1/files",
        headers={"X-CSRF-Token": token},
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
        headers={"X-CSRF-Token": token},
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
        headers={"X-CSRF-Token": token},
        json=request_payload,
    )
    second_response = await client.post(
        "/api/v1/files/folders",
        headers={"X-CSRF-Token": token},
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
        headers={"X-CSRF-Token": token},
        json={"slug": "security", "name": "安全文档", "space_type": "team"},
    )
    space_payload = space_response.json()

    response = await client.post(
        "/api/v1/files/folders",
        headers={"X-CSRF-Token": token},
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
        headers={"X-CSRF-Token": admin_token},
        json={"slug": "private", "name": "私有空间", "space_type": "team"},
    )
    await create_second_user(session_factory)
    member_token = await login(client, username="member", password="member-password")

    response = await client.get(
        "/api/v1/files",
        headers={"X-CSRF-Token": member_token},
        params={"space_id": space_response.json()["id"]},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "SPACE_NOT_FOUND"
