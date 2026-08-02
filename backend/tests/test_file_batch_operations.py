from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.modules.file.models import FileBatchOperation, Node
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
from tests.test_file_operations import create_instant_file


@pytest.mark.asyncio
async def test_trash_listing_and_batch_delete_restore(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space = await create_space(client, csrf_token, slug="batch-trash-space")
    first = await create_folder(
        client,
        csrf_token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        name="批量一",
    )
    second = await create_folder(
        client,
        csrf_token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        name="批量二",
    )

    delete_response = await client.post(
        "/api/v1/files/batch-delete",
        headers={"X-CSRF-Token": csrf_token, "Idempotency-Key": "trash-delete-1"},
        json={"node_ids": [first["id"], second["id"]], "mode": "trash"},
    )

    assert delete_response.status_code == 200
    assert [item["status"] for item in delete_response.json()["results"]] == [
        "success",
        "success",
    ]

    first_page = await client.get(
        "/api/v1/files/trash",
        params={"space_id": space["id"], "page_size": 1},
    )
    assert first_page.status_code == 200
    assert len(first_page.json()["items"]) == 1
    assert first_page.json()["next_cursor"]

    second_page = await client.get(
        "/api/v1/files/trash",
        params={
            "space_id": space["id"],
            "page_size": 1,
            "cursor": first_page.json()["next_cursor"],
        },
    )
    assert second_page.status_code == 200
    assert {item["id"] for item in first_page.json()["items"] + second_page.json()["items"]} == {
        first["id"],
        second["id"],
    }

    restore_response = await client.post(
        "/api/v1/files/batch-restore",
        headers={"X-CSRF-Token": csrf_token, "Idempotency-Key": "trash-restore-1"},
        json={"node_ids": [first["id"], second["id"]]},
    )
    assert restore_response.status_code == 200
    assert [item["status"] for item in restore_response.json()["results"]] == [
        "success",
        "success",
    ]

    empty_trash = await client.get(
        "/api/v1/files/trash",
        params={"space_id": space["id"]},
    )
    assert empty_trash.status_code == 200
    assert empty_trash.json()["items"] == []


@pytest.mark.asyncio
async def test_batch_move_returns_per_item_partial_results(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space = await create_space(client, csrf_token, slug="batch-move-space")
    target = await create_folder(
        client,
        csrf_token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        name="目标",
    )
    source = await create_folder(
        client,
        csrf_token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        name="来源",
    )

    response = await client.post(
        "/api/v1/files/batch-move",
        headers={"X-CSRF-Token": csrf_token, "Idempotency-Key": "batch-move-1"},
        json={
            "node_ids": [source["id"], str(uuid4())],
            "target_parent_id": target["id"],
        },
    )

    assert response.status_code == 200
    results = response.json()["results"]
    assert results[0]["node_id"] == source["id"]
    assert results[0]["status"] == "success"
    assert results[1]["status"] == "failed"
    assert results[1]["code"] == "NODE_NOT_FOUND"
    target_listing = await client.get(
        "/api/v1/files",
        params={"space_id": space["id"], "parent_id": target["id"]},
    )
    assert [item["id"] for item in target_listing.json()["items"]] == [source["id"]]


@pytest.mark.asyncio
async def test_batch_purge_is_persistently_idempotent(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space = await create_space(client, csrf_token, slug="batch-purge-space")
    first = await create_instant_file(
        client,
        session_factory,
        csrf_token,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        file_name="批量清理一.txt",
        content_hash="d" * 64,
        size_bytes=128,
    )
    second = await create_instant_file(
        client,
        session_factory,
        csrf_token,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        file_name="批量清理二.txt",
        content_hash="e" * 64,
        size_bytes=256,
    )
    node_ids = [first["node_id"], second["node_id"]]
    for node_id in node_ids:
        delete_response = await client.delete(
            f"/api/v1/files/{node_id}",
            headers={"X-CSRF-Token": csrf_token},
        )
        assert delete_response.status_code == 200

    request = {"node_ids": node_ids}
    first_response = await client.post(
        "/api/v1/files/batch-purge",
        headers={"X-CSRF-Token": csrf_token, "Idempotency-Key": "batch-purge-1"},
        json=request,
    )
    replay_response = await client.post(
        "/api/v1/files/batch-purge",
        headers={"X-CSRF-Token": csrf_token, "Idempotency-Key": "batch-purge-1"},
        json=request,
    )
    conflict_response = await client.post(
        "/api/v1/files/batch-purge",
        headers={"X-CSRF-Token": csrf_token, "Idempotency-Key": "batch-purge-1"},
        json={"node_ids": [node_ids[0]]},
    )

    assert first_response.status_code == 200
    assert replay_response.status_code == 200
    assert replay_response.json() == first_response.json()
    assert conflict_response.status_code == 409
    assert conflict_response.json()["code"] == "IDEMPOTENCY_KEY_REUSED"

    async with session_factory() as session:
        remaining_nodes = (
            (
                await session.execute(
                    select(Node).where(Node.id.in_([UUID(node_id) for node_id in node_ids]))
                )
            )
            .scalars()
            .all()
        )
        operation_count = await session.scalar(
            select(func.count(FileBatchOperation.id)).where(
                FileBatchOperation.operation == "purge",
            )
        )

    assert remaining_nodes == []
    assert operation_count == 1
