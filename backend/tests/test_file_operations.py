from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.modules.audit.models import AuditLog
from app.modules.file.models import FileBlob, FileVersion, Node
from app.modules.quota.models import QuotaAccount, QuotaLedger
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


async def create_instant_file(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    token: str,
    *,
    tenant_id: str,
    space_id: str,
    parent_id: str,
    file_name: str,
    content_hash: str,
    size_bytes: int,
) -> dict[str, object]:
    async with session_factory() as session:
        blob = FileBlob(
            tenant_id=UUID(tenant_id),
            hash_algo="sha256",
            content_hash=content_hash,
            size_bytes=size_bytes,
            storage_key=f"objects/test/{content_hash[:2]}/{content_hash}",
            mime_type="text/plain",
            ref_count=0,
        )
        session.add(blob)
        await session.commit()

    response = await client.post(
        "/api/v1/uploads/init",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "space_id": space_id,
            "parent_id": parent_id,
            "file_name": file_name,
            "size_bytes": size_bytes,
            "content_hash": content_hash,
            "hash_algo": "sha256",
            "mime_type": "text/plain",
        },
    )

    assert response.status_code == 201
    payload = dict(response.json())
    assert payload["mode"] == "instant"
    return payload


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
async def test_purge_deleted_file_releases_quota_and_removes_metadata(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="purge-file-space")
    size_bytes = 2048
    file_payload = await create_instant_file(
        client,
        session_factory,
        token,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        file_name="待彻底删除.txt",
        content_hash="a" * 64,
        size_bytes=size_bytes,
    )
    node_id = UUID(str(file_payload["node_id"]))
    version_id = UUID(str(file_payload["version_id"]))
    blob_id = UUID(str(file_payload["blob_id"]))

    delete_response = await client.delete(
        f"/api/v1/files/{node_id}",
        headers={"Authorization": f"Bearer {token}", "X-Request-ID": "req_delete_before_purge"},
    )

    assert delete_response.status_code == 200
    async with session_factory() as session:
        quota_account = (await session.execute(select(QuotaAccount))).scalar_one()
        ledgers = (await session.execute(select(QuotaLedger))).scalars().all()
        deleted_node = (await session.execute(select(Node).where(Node.id == node_id))).scalar_one()

    assert quota_account.used_bytes == size_bytes
    assert [ledger.delta_bytes for ledger in ledgers] == [size_bytes]
    assert deleted_node.is_deleted is True

    purge_response = await client.delete(
        f"/api/v1/files/{node_id}/purge",
        headers={"Authorization": f"Bearer {token}", "X-Request-ID": "req_purge_file"},
    )

    assert purge_response.status_code == 200
    assert purge_response.json() == {
        "node_id": str(node_id),
        "purged_count": 1,
        "released_bytes": size_bytes,
    }

    async with session_factory() as session:
        quota_account = (await session.execute(select(QuotaAccount))).scalar_one()
        ledgers = (
            (await session.execute(select(QuotaLedger).order_by(QuotaLedger.created_at)))
            .scalars()
            .all()
        )
        node = (await session.execute(select(Node).where(Node.id == node_id))).scalar_one_or_none()
        version = (
            await session.execute(select(FileVersion).where(FileVersion.id == version_id))
        ).scalar_one_or_none()
        blob = (await session.execute(select(FileBlob).where(FileBlob.id == blob_id))).scalar_one()
        audit = (
            await session.execute(select(AuditLog).where(AuditLog.action == "file.purged"))
        ).scalar_one()

    assert quota_account.used_bytes == 0
    assert [(ledger.delta_bytes, ledger.reason, ledger.ref_type) for ledger in ledgers] == [
        (size_bytes, "file_version_created", "file_version"),
        (-size_bytes, "file_purged", "node"),
    ]
    assert ledgers[1].ref_id == node_id
    assert node is None
    assert version is None
    assert blob.ref_count == 0
    assert audit.request_id == "req_purge_file"
    assert audit.resource_id == node_id
    assert audit.metadata_json["released_bytes"] == size_bytes


@pytest.mark.asyncio
async def test_purge_deleted_folder_releases_descendant_versions(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="purge-folder-space")
    folder = await create_folder(
        client,
        token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        name="待清空目录",
    )
    child_folder = await create_folder(
        client,
        token,
        space_id=str(space["id"]),
        parent_id=str(folder["id"]),
        name="子目录",
    )
    root_file = await create_instant_file(
        client,
        session_factory,
        token,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
        parent_id=str(folder["id"]),
        file_name="根文件.txt",
        content_hash="b" * 64,
        size_bytes=1024,
    )
    child_file = await create_instant_file(
        client,
        session_factory,
        token,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
        parent_id=str(child_folder["id"]),
        file_name="子文件.txt",
        content_hash="c" * 64,
        size_bytes=4096,
    )

    delete_response = await client.delete(
        f"/api/v1/files/{folder['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    purge_response = await client.delete(
        f"/api/v1/files/{folder['id']}/purge",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert delete_response.status_code == 200
    assert delete_response.json()["deleted_count"] == 4
    assert purge_response.status_code == 200
    assert purge_response.json() == {
        "node_id": folder["id"],
        "purged_count": 4,
        "released_bytes": 5120,
    }

    purged_node_ids = {
        UUID(str(folder["id"])),
        UUID(str(child_folder["id"])),
        UUID(str(root_file["node_id"])),
        UUID(str(child_file["node_id"])),
    }
    purged_version_ids = {
        UUID(str(root_file["version_id"])),
        UUID(str(child_file["version_id"])),
    }
    async with session_factory() as session:
        quota_account = (await session.execute(select(QuotaAccount))).scalar_one()
        remaining_nodes = (
            (await session.execute(select(Node).where(Node.id.in_(purged_node_ids))))
            .scalars()
            .all()
        )
        remaining_versions = (
            (
                await session.execute(
                    select(FileVersion).where(FileVersion.id.in_(purged_version_ids))
                )
            )
            .scalars()
            .all()
        )
        blob_ref_counts = (
            (
                await session.execute(
                    select(FileBlob.ref_count).where(
                        FileBlob.id.in_(
                            [
                                UUID(str(root_file["blob_id"])),
                                UUID(str(child_file["blob_id"])),
                            ]
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        release_ledger = (
            await session.execute(
                select(QuotaLedger).where(
                    QuotaLedger.reason == "file_purged",
                    QuotaLedger.ref_id == UUID(str(folder["id"])),
                )
            )
        ).scalar_one()

    assert quota_account.used_bytes == 0
    assert remaining_nodes == []
    assert remaining_versions == []
    assert blob_ref_counts == [0, 0]
    assert release_ledger.delta_bytes == -5120


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
    purge_response = await client.delete(
        f"/api/v1/files/{space['root_node_id']}/purge",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert delete_response.status_code == 400
    assert delete_response.json()["code"] == "NODE_ROOT_IMMUTABLE"
    assert rename_response.status_code == 400
    assert rename_response.json()["code"] == "NODE_ROOT_IMMUTABLE"
    assert purge_response.status_code == 400
    assert purge_response.json()["code"] == "NODE_ROOT_IMMUTABLE"


@pytest.mark.asyncio
async def test_purge_rejects_active_node(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="purge-active-space")
    folder = await create_folder(
        client,
        token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        name="仍然活跃",
    )

    response = await client.delete(
        f"/api/v1/files/{folder['id']}/purge",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "NODE_NOT_DELETED"
