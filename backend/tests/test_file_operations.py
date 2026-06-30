from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.modules.audit.models import AuditLog
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
async def test_rename_folder_updates_node_and_audit(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="rename-space")
    folder = await create_folder(
        client,
        token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        name="旧名称",
    )

    response = await client.patch(
        f"/api/v1/files/{folder['id']}",
        headers={"Authorization": f"Bearer {token}", "X-Request-ID": "req_rename"},
        json={"name": " 新名称 "},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "新名称"

    async with session_factory() as session:
        audit = (
            await session.execute(select(AuditLog).where(AuditLog.action == "file.renamed"))
        ).scalar_one()
    assert audit.request_id == "req_rename"
    assert audit.metadata_json["old_name"] == "旧名称"
    assert audit.metadata_json["new_name"] == "新名称"


@pytest.mark.asyncio
async def test_move_folder_to_new_parent_with_new_name(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="move-space")
    source = await create_folder(
        client,
        token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        name="待移动",
    )
    target = await create_folder(
        client,
        token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        name="目标目录",
    )

    response = await client.post(
        f"/api/v1/files/{source['id']}/move",
        headers={"Authorization": f"Bearer {token}"},
        json={"target_parent_id": target["id"], "new_name": "移动后"},
    )

    assert response.status_code == 200
    assert response.json()["parent_id"] == target["id"]
    assert response.json()["name"] == "移动后"

    old_parent_response = await client.get(
        "/api/v1/files",
        headers={"Authorization": f"Bearer {token}"},
        params={"space_id": space["id"], "parent_id": space["root_node_id"]},
    )
    target_response = await client.get(
        "/api/v1/files",
        headers={"Authorization": f"Bearer {token}"},
        params={"space_id": space["id"], "parent_id": target["id"]},
    )

    assert {item["name"] for item in old_parent_response.json()["items"]} == {"目标目录"}
    assert [item["name"] for item in target_response.json()["items"]] == ["移动后"]


@pytest.mark.asyncio
async def test_move_folder_to_own_descendant_is_rejected(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="move-invalid-space")
    parent = await create_folder(
        client,
        token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        name="父目录",
    )
    child = await create_folder(
        client,
        token,
        space_id=str(space["id"]),
        parent_id=str(parent["id"]),
        name="子目录",
    )

    response = await client.post(
        f"/api/v1/files/{parent['id']}/move",
        headers={"Authorization": f"Bearer {token}"},
        json={"target_parent_id": child["id"]},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "NODE_MOVE_INVALID"


@pytest.mark.asyncio
async def test_delete_and_restore_folder_subtree(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="trash-space")
    parent = await create_folder(
        client,
        token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        name="父目录",
    )
    child = await create_folder(
        client,
        token,
        space_id=str(space["id"]),
        parent_id=str(parent["id"]),
        name="子目录",
    )

    delete_response = await client.delete(
        f"/api/v1/files/{parent['id']}",
        headers={"Authorization": f"Bearer {token}", "X-Request-ID": "req_delete"},
    )
    root_after_delete = await client.get(
        "/api/v1/files",
        headers={"Authorization": f"Bearer {token}"},
        params={"space_id": space["id"], "parent_id": space["root_node_id"]},
    )
    deleted_parent_list = await client.get(
        "/api/v1/files",
        headers={"Authorization": f"Bearer {token}"},
        params={"space_id": space["id"], "parent_id": parent["id"]},
    )
    restore_response = await client.post(
        f"/api/v1/files/{parent['id']}/restore",
        headers={"Authorization": f"Bearer {token}", "X-Request-ID": "req_restore"},
        json={},
    )
    restored_children = await client.get(
        "/api/v1/files",
        headers={"Authorization": f"Bearer {token}"},
        params={"space_id": space["id"], "parent_id": parent["id"]},
    )

    assert delete_response.status_code == 200
    assert delete_response.json() == {"node_id": parent["id"], "deleted_count": 2}
    assert root_after_delete.json()["items"] == []
    assert deleted_parent_list.status_code == 404
    assert deleted_parent_list.json()["code"] == "PARENT_NOT_FOUND"
    assert restore_response.status_code == 200
    assert restore_response.json()["id"] == parent["id"]
    assert [item["id"] for item in restored_children.json()["items"]] == [child["id"]]

    async with session_factory() as session:
        audits = (
            (
                await session.execute(
                    select(AuditLog)
                    .where(AuditLog.action.in_(["file.deleted", "file.restored"]))
                    .order_by(AuditLog.action)
                )
            )
            .scalars()
            .all()
        )
    assert {audit.request_id for audit in audits} == {"req_delete", "req_restore"}


@pytest.mark.asyncio
async def test_restore_rejects_sibling_name_conflict(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="restore-conflict-space")
    deleted_folder = await create_folder(
        client,
        token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        name="同名目录",
    )
    delete_response = await client.delete(
        f"/api/v1/files/{deleted_folder['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert delete_response.status_code == 200
    await create_folder(
        client,
        token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        name="同名目录",
    )

    conflict_response = await client.post(
        f"/api/v1/files/{deleted_folder['id']}/restore",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )
    renamed_response = await client.post(
        f"/api/v1/files/{deleted_folder['id']}/restore",
        headers={"Authorization": f"Bearer {token}"},
        json={"new_name": "恢复后的目录"},
    )

    assert conflict_response.status_code == 409
    assert conflict_response.json()["code"] == "NODE_NAME_EXISTS"
    assert renamed_response.status_code == 200
    assert renamed_response.json()["name"] == "恢复后的目录"


@pytest.mark.asyncio
async def test_root_folder_is_immutable(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="root-immutable-space")

    delete_response = await client.delete(
        f"/api/v1/files/{space['root_node_id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    rename_response = await client.patch(
        f"/api/v1/files/{space['root_node_id']}",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "new-root"},
    )

    assert delete_response.status_code == 400
    assert delete_response.json()["code"] == "NODE_ROOT_IMMUTABLE"
    assert rename_response.status_code == 400
    assert rename_response.json()["code"] == "NODE_ROOT_IMMUTABLE"
