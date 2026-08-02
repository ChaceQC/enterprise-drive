from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.modules.audit.repository import AuditRepository
from app.modules.audit.service import AuditService
from app.modules.file.models import FileBlob, FileTreeOperation, Node
from app.modules.file.repository import FileRepository
from app.modules.file.tree_operations import FileTreeOperationProcessor
from app.modules.quota.models import QuotaAccount
from app.modules.quota.repository import QuotaRepository
from app.modules.quota.service import QuotaService
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


async def _process_operation(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    operation_id: str,
    *,
    max_batches: int | None = None,
) -> str:
    async with session_factory() as session:
        return await FileTreeOperationProcessor(
            repository=FileRepository(session),
            quota_service=QuotaService(
                repository=QuotaRepository(session),
                default_space_limit_bytes=settings.default_space_quota_bytes,
                default_user_limit_bytes=settings.default_user_quota_bytes,
                default_tenant_limit_bytes=settings.default_tenant_quota_bytes,
                policy_enabled=settings.quota_policy_enabled,
            ),
            batch_size=1,
            audit_service=AuditService(repository=AuditRepository(session)),
        ).process_operation(
            operation_id=UUID(operation_id),
            max_batches=max_batches,
        )


@pytest.mark.asyncio
async def test_large_tree_delete_restore_and_purge_are_resumable(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    settings.file_tree_async_threshold = 2
    settings.file_tree_operation_batch_size = 1
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space = await create_space(client, csrf_token, slug="large-tree-operations")
    root = await create_folder(
        client,
        csrf_token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        name="大目录",
    )
    child = await create_folder(
        client,
        csrf_token,
        space_id=str(space["id"]),
        parent_id=str(root["id"]),
        name="子目录",
    )
    file_payload = await create_instant_file(
        client,
        session_factory,
        csrf_token,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
        parent_id=str(child["id"]),
        file_name="大目录文件.txt",
        content_hash="f" * 64,
        size_bytes=512,
    )
    node_ids = [root["id"], child["id"], file_payload["node_id"]]

    delete_response = await client.delete(
        f"/api/v1/files/{root['id']}",
        headers={"X-CSRF-Token": csrf_token, "X-Request-ID": "large-delete"},
    )
    assert delete_response.status_code == 202
    delete_operation_id = delete_response.json()["operation_id"]
    assert delete_response.json()["processed_count"] == 1
    assert delete_response.json()["total_count"] == 3

    first_batch_status = await _process_operation(
        session_factory,
        settings,
        delete_operation_id,
        max_batches=1,
    )
    assert first_batch_status == "running"
    running_response = await client.get(
        f"/api/v1/files/operations/{delete_operation_id}",
    )
    assert running_response.status_code == 200
    assert running_response.json()["status"] == "running"
    assert running_response.json()["processed_count"] == 2

    assert await _process_operation(session_factory, settings, delete_operation_id) == "completed"
    async with session_factory() as session:
        deleted_nodes = (
            (
                await session.execute(
                    select(Node).where(Node.id.in_([UUID(node_id) for node_id in node_ids]))
                )
            )
            .scalars()
            .all()
        )
    assert all(node.is_deleted for node in deleted_nodes)
    assert {node.deleted_root_id for node in deleted_nodes} == {UUID(str(root["id"]))}

    restore_response = await client.post(
        f"/api/v1/files/{root['id']}/restore",
        headers={"X-CSRF-Token": csrf_token, "X-Request-ID": "large-restore"},
        json={},
    )
    assert restore_response.status_code == 202
    restore_operation_id = restore_response.json()["operation_id"]
    assert await _process_operation(session_factory, settings, restore_operation_id) == "completed"
    async with session_factory() as session:
        restored_nodes = (
            (
                await session.execute(
                    select(Node).where(Node.id.in_([UUID(node_id) for node_id in node_ids]))
                )
            )
            .scalars()
            .all()
        )
    assert all(not node.is_deleted for node in restored_nodes)
    assert all(node.deleted_root_id is None for node in restored_nodes)

    second_delete = await client.delete(
        f"/api/v1/files/{root['id']}",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert second_delete.status_code == 202
    assert (
        await _process_operation(
            session_factory,
            settings,
            second_delete.json()["operation_id"],
        )
        == "completed"
    )

    purge_response = await client.delete(
        f"/api/v1/files/{root['id']}/purge",
        headers={"X-CSRF-Token": csrf_token, "X-Request-ID": "large-purge"},
    )
    assert purge_response.status_code == 202
    purge_operation_id = purge_response.json()["operation_id"]
    assert await _process_operation(session_factory, settings, purge_operation_id) == "completed"

    operation_response = await client.get(
        f"/api/v1/files/operations/{purge_operation_id}",
    )
    assert operation_response.status_code == 200
    assert operation_response.json()["status"] == "completed"
    assert operation_response.json()["processed_count"] == 3
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
        quota_account = (await session.execute(select(QuotaAccount))).scalar_one()
        blob = (
            await session.execute(
                select(FileBlob).where(FileBlob.id == UUID(str(file_payload["blob_id"])))
            )
        ).scalar_one()
    assert remaining_nodes == []
    assert quota_account.used_bytes == 0
    assert blob.ref_count == 0


@pytest.mark.asyncio
async def test_failed_tree_operation_can_be_retried(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    settings.file_tree_async_threshold = 2
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space = await create_space(client, csrf_token, slug="large-tree-retry")
    root = await create_folder(
        client,
        csrf_token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        name="待重试",
    )
    child = await create_folder(
        client,
        csrf_token,
        space_id=str(space["id"]),
        parent_id=str(root["id"]),
        name="子目录",
    )
    await create_folder(
        client,
        csrf_token,
        space_id=str(space["id"]),
        parent_id=str(child["id"]),
        name="孙目录",
    )
    delete_response = await client.delete(
        f"/api/v1/files/{root['id']}",
        headers={"X-CSRF-Token": csrf_token},
    )
    operation_id = UUID(delete_response.json()["operation_id"])

    async with session_factory() as session:
        operation = (
            await session.execute(
                select(FileTreeOperation).where(FileTreeOperation.id == operation_id)
            )
        ).scalar_one()
        operation.status = "failed"
        operation.error_code = "TEST_FAILURE"
        await session.commit()

    retry_response = await client.post(
        f"/api/v1/files/operations/{operation_id}/retry",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert retry_response.status_code == 200
    assert retry_response.json()["status"] == "pending"
    assert retry_response.json()["error_code"] is None
