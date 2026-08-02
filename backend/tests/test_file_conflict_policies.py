from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from tests.helpers import (
    client as client,
)
from tests.helpers import (
    create_folder,
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
async def test_create_folder_keep_both_and_replace(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space = await create_space(client, csrf_token, slug="folder-conflict-policy")
    original = await create_folder(
        client,
        csrf_token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        name="资料",
    )

    keep_both_response = await client.post(
        "/api/v1/files/folders",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "name": "资料",
            "conflict_policy": "keep_both",
        },
    )
    replace_response = await client.post(
        "/api/v1/files/folders",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "name": "资料",
            "conflict_policy": "replace",
        },
    )

    assert keep_both_response.status_code == 201
    assert keep_both_response.json()["name"] == "资料 (1)"
    assert replace_response.status_code == 201
    assert replace_response.json()["name"] == "资料"
    assert replace_response.json()["id"] != original["id"]

    active_listing = await client.get(
        "/api/v1/files",
        params={"space_id": space["id"], "parent_id": space["root_node_id"]},
    )
    trash_listing = await client.get(
        "/api/v1/files/trash",
        params={"space_id": space["id"]},
    )
    assert {item["name"] for item in active_listing.json()["items"]} == {"资料", "资料 (1)"}
    assert [item["id"] for item in trash_listing.json()["items"]] == [original["id"]]


@pytest.mark.asyncio
async def test_move_keep_both_and_replace(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space = await create_space(client, csrf_token, slug="move-conflict-policy")
    source_parent = await create_folder(
        client,
        csrf_token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        name="来源",
    )
    source_parent_two = await create_folder(
        client,
        csrf_token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        name="来源二",
    )
    target_parent = await create_folder(
        client,
        csrf_token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        name="目标",
    )
    existing = await create_folder(
        client,
        csrf_token,
        space_id=str(space["id"]),
        parent_id=str(target_parent["id"]),
        name="报告",
    )
    keep_source = await create_folder(
        client,
        csrf_token,
        space_id=str(space["id"]),
        parent_id=str(source_parent["id"]),
        name="报告",
    )
    replace_source = await create_folder(
        client,
        csrf_token,
        space_id=str(space["id"]),
        parent_id=str(source_parent_two["id"]),
        name="报告",
    )

    keep_response = await client.post(
        f"/api/v1/files/{keep_source['id']}/move",
        headers={"X-CSRF-Token": csrf_token},
        json={"target_parent_id": target_parent["id"], "conflict_policy": "keep_both"},
    )
    replace_response = await client.post(
        f"/api/v1/files/{replace_source['id']}/move",
        headers={"X-CSRF-Token": csrf_token},
        json={"target_parent_id": target_parent["id"], "conflict_policy": "replace"},
    )

    assert keep_response.status_code == 200
    assert keep_response.json()["name"] == "报告 (1)"
    assert replace_response.status_code == 200
    assert replace_response.json()["name"] == "报告"

    target_listing = await client.get(
        "/api/v1/files",
        params={"space_id": space["id"], "parent_id": target_parent["id"]},
    )
    trash_listing = await client.get(
        "/api/v1/files/trash",
        params={"space_id": space["id"]},
    )
    assert {item["id"] for item in target_listing.json()["items"]} == {
        keep_source["id"],
        replace_source["id"],
    }
    assert existing["id"] in {item["id"] for item in trash_listing.json()["items"]}


@pytest.mark.asyncio
async def test_restore_keep_both_and_replace(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space = await create_space(client, csrf_token, slug="restore-conflict-policy")
    keep_deleted = await create_folder(
        client,
        csrf_token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        name="恢复",
    )
    replace_deleted = await create_folder(
        client,
        csrf_token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        name="替换",
    )
    for node in (keep_deleted, replace_deleted):
        response = await client.delete(
            f"/api/v1/files/{node['id']}",
            headers={"X-CSRF-Token": csrf_token},
        )
        assert response.status_code == 200

    keep_existing = await create_folder(
        client,
        csrf_token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        name="恢复",
    )
    replace_existing = await create_folder(
        client,
        csrf_token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        name="替换",
    )

    keep_response = await client.post(
        f"/api/v1/files/{keep_deleted['id']}/restore",
        headers={"X-CSRF-Token": csrf_token},
        json={"conflict_policy": "keep_both"},
    )
    replace_response = await client.post(
        f"/api/v1/files/{replace_deleted['id']}/restore",
        headers={"X-CSRF-Token": csrf_token},
        json={"conflict_policy": "replace"},
    )

    assert keep_response.status_code == 200
    assert keep_response.json()["name"] == "恢复 (1)"
    assert replace_response.status_code == 200
    assert replace_response.json()["name"] == "替换"

    trash_listing = await client.get(
        "/api/v1/files/trash",
        params={"space_id": space["id"]},
    )
    trash_ids = {item["id"] for item in trash_listing.json()["items"]}
    assert keep_existing["id"] not in trash_ids
    assert replace_existing["id"] in trash_ids
