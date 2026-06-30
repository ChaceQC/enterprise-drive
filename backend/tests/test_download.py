from __future__ import annotations

import hashlib
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.modules.audit.models import AuditLog, OutboxEvent
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


def zero_bytes_sha256(size_bytes: int) -> str:
    return hashlib.sha256(b"\x00" * size_bytes).hexdigest()


async def complete_small_file(
    client: AsyncClient,
    token: str,
    *,
    space_id: str,
    parent_id: str,
    file_name: str,
) -> dict[str, str]:
    init_response = await client.post(
        "/api/v1/uploads/init",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "space_id": space_id,
            "parent_id": parent_id,
            "file_name": file_name,
            "size_bytes": 1024,
            "content_hash": zero_bytes_sha256(1024),
            "hash_algo": "sha256",
            "mime_type": "text/plain",
        },
    )
    assert init_response.status_code == 201
    complete_response = await client.post(
        f"/api/v1/uploads/{init_response.json()['session_id']}/complete",
        headers={"Authorization": f"Bearer {token}"},
        json={"parts": [{"part_no": 1, "etag": "etag-1", "size_bytes": 1024}]},
    )
    assert complete_response.status_code == 200
    return dict(complete_response.json())


@pytest.mark.asyncio
async def test_create_download_url_records_audit(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="download-space")
    completed = await complete_small_file(
        client,
        token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        file_name="下载文件.txt",
    )

    response = await client.get(
        f"/api/v1/files/{completed['node_id']}/download",
        headers={"Authorization": f"Bearer {token}", "X-Request-ID": "req_download"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["node_id"] == completed["node_id"]
    assert payload["version_id"] == completed["version_id"]
    assert payload["file_name"] == "下载文件.txt"
    assert payload["size_bytes"] == 1024
    assert payload["mime_type"] == "text/plain"
    assert payload["download_url"].startswith("https://storage.test/")
    assert "download=下载文件.txt" in payload["download_url"]

    async with session_factory() as session:
        audit = (
            await session.execute(select(AuditLog).where(AuditLog.action == "file.downloaded"))
        ).scalar_one()
        outbox_event = (
            await session.execute(
                select(OutboxEvent).where(OutboxEvent.event_type == "audit.file.downloaded")
            )
        ).scalar_one()

    assert audit.request_id == "req_download"
    assert audit.resource_id == UUID(completed["node_id"])
    assert audit.metadata_json["version_id"] == completed["version_id"]
    assert audit.metadata_json["blob_id"] == completed["blob_id"]
    assert outbox_event.aggregate_type == "audit_log"


@pytest.mark.asyncio
async def test_download_rejects_folder(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="download-folder-space")
    folder = await create_folder(
        client,
        token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        name="目录",
    )

    response = await client.get(
        f"/api/v1/files/{folder['id']}/download",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "NODE_NOT_FILE"

    async with session_factory() as session:
        audit = (
            await session.execute(select(AuditLog).where(AuditLog.action == "file.downloaded"))
        ).scalar_one()

    assert audit.result == "denied"
    assert audit.resource_id == UUID(folder["id"])
    assert audit.metadata_json["reason"] == "node_not_file"


@pytest.mark.asyncio
async def test_download_uses_owner_boundary_until_permission_module(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    admin_token = await login(client)
    space = await create_space(client, admin_token, slug="download-private-space")
    completed = await complete_small_file(
        client,
        admin_token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        file_name="private.txt",
    )
    await create_second_user(session_factory)
    member_token = await login(client, username="member", password="member-password")

    response = await client.get(
        f"/api/v1/files/{completed['node_id']}/download",
        headers={"Authorization": f"Bearer {member_token}"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "NODE_NOT_FOUND"

    async with session_factory() as session:
        audit = (
            await session.execute(select(AuditLog).where(AuditLog.action == "file.downloaded"))
        ).scalar_one()

    assert audit.result == "denied"
    assert audit.resource_id == UUID(completed["node_id"])
    assert audit.metadata_json["reason"] == "space_owner_required"
