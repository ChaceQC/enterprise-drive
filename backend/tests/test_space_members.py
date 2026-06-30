from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.modules.audit.models import AuditLog
from app.modules.space.models import Space
from tests.helpers import (
    client as client,
)
from tests.helpers import (
    create_folder,
    create_second_user,
    create_space,
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
async def test_owner_can_manage_member_lifecycle_and_permissions_follow_role(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    admin_token = await login(client)
    space = await create_space(client, admin_token, slug="member-lifecycle")
    member_id = await create_second_user(session_factory)

    add_response = await client.post(
        f"/api/v1/spaces/{space['id']}/members",
        headers={"X-CSRF-Token": admin_token, "X-Request-ID": "req_member_add"},
        json={"user_id": str(member_id), "role": "viewer"},
    )
    duplicate_response = await client.post(
        f"/api/v1/spaces/{space['id']}/members",
        headers={"X-CSRF-Token": admin_token},
        json={"user_id": str(member_id), "role": "viewer"},
    )
    list_response = await client.get(
        f"/api/v1/spaces/{space['id']}/members",
        headers={"X-CSRF-Token": admin_token},
    )

    assert add_response.status_code == 201
    assert add_response.json()["role"] == "viewer"
    assert duplicate_response.status_code == 409
    assert duplicate_response.json()["code"] == "SPACE_MEMBER_EXISTS"
    assert list_response.status_code == 200
    assert {item["role"] for item in list_response.json()["items"]} == {"owner", "viewer"}

    member_token = await login(client, username="member", password="member-password")
    denied_write_response = await client.post(
        "/api/v1/files/folders",
        headers={"X-CSRF-Token": member_token},
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "name": "viewer-denied",
        },
    )
    assert denied_write_response.status_code == 404
    assert denied_write_response.json()["code"] == "SPACE_NOT_FOUND"

    admin_token = await login(client)
    update_response = await client.patch(
        f"/api/v1/spaces/{space['id']}/members/{member_id}",
        headers={"X-CSRF-Token": admin_token, "X-Request-ID": "req_member_update"},
        json={"role": "editor"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["role"] == "editor"

    member_token = await login(client, username="member", password="member-password")
    folder = await create_folder(
        client,
        member_token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        name="editor-write-allowed",
    )
    assert folder["name"] == "editor-write-allowed"

    admin_token = await login(client)
    remove_response = await client.delete(
        f"/api/v1/spaces/{space['id']}/members/{member_id}",
        headers={"X-CSRF-Token": admin_token, "X-Request-ID": "req_member_remove"},
    )
    assert remove_response.status_code == 200
    assert remove_response.json() == {"user_id": str(member_id), "removed": True}

    member_token = await login(client, username="member", password="member-password")
    list_spaces_response = await client.get(
        "/api/v1/spaces",
        headers={"X-CSRF-Token": member_token},
    )
    list_files_response = await client.get(
        "/api/v1/files",
        headers={"X-CSRF-Token": member_token},
        params={"space_id": space["id"]},
    )
    assert list_spaces_response.status_code == 200
    assert list_spaces_response.json()["items"] == []
    assert list_files_response.status_code == 404
    assert list_files_response.json()["code"] == "SPACE_NOT_FOUND"

    async with session_factory() as session:
        refreshed_space = (await session.execute(select(Space))).scalar_one()
        audit_actions = list((await session.execute(select(AuditLog.action))).scalars().all())

    assert refreshed_space.permission_version == 4
    assert "permission.space_member.added" in audit_actions
    assert "permission.space_member.updated" in audit_actions
    assert "permission.space_member.removed" in audit_actions


@pytest.mark.asyncio
async def test_admin_can_list_members_but_viewer_cannot_manage_members(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    owner_token = await login(client)
    space = await create_space(client, owner_token, slug="member-management")
    member_id = await create_second_user(session_factory)

    add_response = await client.post(
        f"/api/v1/spaces/{space['id']}/members",
        headers={"X-CSRF-Token": owner_token},
        json={"user_id": str(member_id), "role": "admin"},
    )
    assert add_response.status_code == 201

    admin_member_token = await login(client, username="member", password="member-password")
    list_response = await client.get(
        f"/api/v1/spaces/{space['id']}/members",
        headers={"X-CSRF-Token": admin_member_token},
    )
    assert list_response.status_code == 200

    owner_token = await login(client)
    update_response = await client.patch(
        f"/api/v1/spaces/{space['id']}/members/{member_id}",
        headers={"X-CSRF-Token": owner_token},
        json={"role": "viewer"},
    )
    assert update_response.status_code == 200

    viewer_token = await login(client, username="member", password="member-password")
    denied_list_response = await client.get(
        f"/api/v1/spaces/{space['id']}/members",
        headers={"X-CSRF-Token": viewer_token, "X-Request-ID": "req_member_denied"},
    )
    denied_update_response = await client.patch(
        f"/api/v1/spaces/{space['id']}/members/{member_id}",
        headers={"X-CSRF-Token": viewer_token},
        json={"role": "editor"},
    )

    assert denied_list_response.status_code == 404
    assert denied_list_response.json()["code"] == "SPACE_NOT_FOUND"
    assert denied_update_response.status_code == 404
    assert denied_update_response.json()["code"] == "SPACE_NOT_FOUND"

    async with session_factory() as session:
        denied_audit = (
            await session.execute(
                select(AuditLog).where(AuditLog.action == "permission.space_member.list.denied")
            )
        ).scalar_one()
    assert denied_audit.result == "denied"
    assert denied_audit.request_id == "req_member_denied"


@pytest.mark.asyncio
async def test_last_owner_cannot_be_demoted_or_removed(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    owner_token = await login(client)
    space = await create_space(client, owner_token, slug="last-owner")

    demote_response = await client.patch(
        f"/api/v1/spaces/{space['id']}/members/{space['owner_id']}",
        headers={"X-CSRF-Token": owner_token},
        json={"role": "admin"},
    )
    remove_response = await client.delete(
        f"/api/v1/spaces/{space['id']}/members/{space['owner_id']}",
        headers={"X-CSRF-Token": owner_token},
    )

    assert demote_response.status_code == 409
    assert demote_response.json()["code"] == "LAST_SPACE_OWNER"
    assert remove_response.status_code == 409
    assert remove_response.json()["code"] == "LAST_SPACE_OWNER"
