from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.modules.audit.models import AuditLog, OutboxEvent
from app.modules.file.models import FileBlob, FileVersion, Node
from app.modules.upload.models import UploadSession
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


@pytest.mark.asyncio
async def test_init_multipart_upload_status_and_presign(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="upload-space")

    init_response = await client.post(
        "/api/v1/uploads/init",
        headers={"Authorization": f"Bearer {token}", "X-Request-ID": "req_upload_init"},
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "file_name": "  需求说明.pdf  ",
            "size_bytes": settings.upload_part_size_bytes + 1,
            "content_hash": "a" * 64,
            "hash_algo": "sha256",
            "mime_type": "application/pdf",
        },
    )

    assert init_response.status_code == 201
    init_payload = init_response.json()
    assert init_payload["mode"] == "multipart"
    assert init_payload["part_size_bytes"] == settings.upload_part_size_bytes
    assert init_payload["total_parts"] == 2

    status_response = await client.get(
        f"/api/v1/uploads/{init_payload['session_id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    presign_response = await client.post(
        f"/api/v1/uploads/{init_payload['session_id']}/parts/1/presign",
        headers={"Authorization": f"Bearer {token}"},
    )
    status_after_presign = await client.get(
        f"/api/v1/uploads/{init_payload['session_id']}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert status_response.status_code == 200
    assert status_response.json()["status"] == "initiated"
    assert status_response.json()["uploaded_parts"] == []
    assert presign_response.status_code == 200
    assert presign_response.json()["part_no"] == 1
    assert "upload_id=" in presign_response.json()["upload_url"]
    assert status_after_presign.status_code == 200
    assert status_after_presign.json()["status"] == "uploading"

    async with session_factory() as session:
        upload_session = (await session.execute(select(UploadSession))).scalar_one()
        audit = (
            await session.execute(select(AuditLog).where(AuditLog.action == "upload.initialized"))
        ).scalar_one()
        outbox_event = (
            await session.execute(
                select(OutboxEvent).where(OutboxEvent.event_type == "audit.upload.initialized")
            )
        ).scalar_one()

    assert upload_session.file_name == "需求说明.pdf"
    assert upload_session.status == "uploading"
    assert audit.request_id == "req_upload_init"
    assert outbox_event.aggregate_type == "audit_log"


@pytest.mark.asyncio
async def test_init_upload_uses_instant_upload_when_blob_exists(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="instant-upload-space")
    tenant_id = UUID(str(space["tenant_id"]))
    blob_id: UUID

    async with session_factory() as session:
        blob = FileBlob(
            tenant_id=tenant_id,
            hash_algo="sha256",
            content_hash="b" * 64,
            size_bytes=1024,
            storage_key="objects/test/bb",
            mime_type="text/plain",
            ref_count=0,
        )
        session.add(blob)
        await session.commit()
        blob_id = blob.id

    response = await client.post(
        "/api/v1/uploads/init",
        headers={"Authorization": f"Bearer {token}", "X-Request-ID": "req_upload_instant"},
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "file_name": "秒传.txt",
            "size_bytes": 1024,
            "content_hash": "b" * 64,
            "hash_algo": "sha256",
            "mime_type": "text/plain",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["mode"] == "instant"
    assert payload["blob_id"] == str(blob_id)

    async with session_factory() as session:
        blob = (await session.execute(select(FileBlob).where(FileBlob.id == blob_id))).scalar_one()
        node = (
            await session.execute(select(Node).where(Node.id == UUID(payload["node_id"])))
        ).scalar_one()
        version = (
            await session.execute(
                select(FileVersion).where(FileVersion.id == UUID(payload["version_id"]))
            )
        ).scalar_one()
        audit = (
            await session.execute(select(AuditLog).where(AuditLog.action == "upload.instant"))
        ).scalar_one()
        outbox_event = (
            await session.execute(
                select(OutboxEvent).where(OutboxEvent.event_type == "audit.upload.instant")
            )
        ).scalar_one()

    assert blob.ref_count == 1
    assert node.name == "秒传.txt"
    assert node.current_version_id == version.id
    assert version.blob_id == blob_id
    assert audit.request_id == "req_upload_instant"
    assert outbox_event.aggregate_type == "audit_log"


@pytest.mark.asyncio
async def test_init_upload_rejects_name_conflict_and_invalid_part(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="upload-conflict-space")
    await create_folder(
        client,
        token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        name="同名",
    )

    conflict_response = await client.post(
        "/api/v1/uploads/init",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "file_name": "同名",
            "size_bytes": 1024,
            "content_hash": "c" * 64,
            "hash_algo": "sha256",
        },
    )
    init_response = await client.post(
        "/api/v1/uploads/init",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "file_name": "分片.bin",
            "size_bytes": 1024,
            "content_hash": "d" * 64,
            "hash_algo": "sha256",
        },
    )
    invalid_part_response = await client.post(
        f"/api/v1/uploads/{init_response.json()['session_id']}/parts/2/presign",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert conflict_response.status_code == 409
    assert conflict_response.json()["code"] == "NODE_NAME_EXISTS"
    assert init_response.status_code == 201
    assert invalid_part_response.status_code == 422
    assert invalid_part_response.json()["code"] == "UPLOAD_PART_INVALID"
