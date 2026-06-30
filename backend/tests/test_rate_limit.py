from __future__ import annotations

import hashlib
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.infrastructure.storage.testing import InMemoryStorageAdapter
from app.modules.audit.models import AuditLog
from app.modules.upload.models import UploadSession
from tests.helpers import (
    client as client,
)
from tests.helpers import (
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
        headers={"X-CSRF-Token": token},
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
        headers={"X-CSRF-Token": token},
        json={"parts": [{"part_no": 1, "etag": "etag-1", "size_bytes": 1024}]},
    )
    assert complete_response.status_code == 200
    return dict(complete_response.json())


@pytest.mark.asyncio
async def test_upload_init_rate_limit_blocks_second_request(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    settings.rate_limit_enabled = True
    settings.upload_init_rate_limit_count = 1
    settings.upload_init_rate_limit_window_seconds = 60
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="rate-upload-init-space")

    first_response = await client.post(
        "/api/v1/uploads/init",
        headers={"X-CSRF-Token": token},
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "file_name": "first.bin",
            "size_bytes": 1024,
            "content_hash": "1" * 64,
            "hash_algo": "sha256",
        },
    )
    second_response = await client.post(
        "/api/v1/uploads/init",
        headers={"X-CSRF-Token": token},
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "file_name": "second.bin",
            "size_bytes": 1024,
            "content_hash": "2" * 64,
            "hash_algo": "sha256",
        },
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 429
    assert second_response.json()["code"] == "RATE_LIMITED"
    assert second_response.json()["details"]["action"] == "upload.init"

    async with session_factory() as session:
        sessions = (await session.execute(select(UploadSession))).scalars().all()

    assert len(sessions) == 1
    assert sessions[0].file_name == "first.bin"


@pytest.mark.asyncio
async def test_upload_part_presign_rate_limit_blocks_second_request(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    settings.rate_limit_enabled = True
    settings.upload_part_presign_rate_limit_count = 1
    settings.upload_part_presign_rate_limit_window_seconds = 60
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="rate-part-presign-space")
    init_response = await client.post(
        "/api/v1/uploads/init",
        headers={"X-CSRF-Token": token},
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "file_name": "part.bin",
            "size_bytes": 1024,
            "content_hash": "3" * 64,
            "hash_algo": "sha256",
        },
    )
    session_id = init_response.json()["session_id"]

    first_response = await client.post(
        f"/api/v1/uploads/{session_id}/parts/1/presign",
        headers={"X-CSRF-Token": token},
    )
    second_response = await client.post(
        f"/api/v1/uploads/{session_id}/parts/1/presign",
        headers={"X-CSRF-Token": token},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 429
    assert second_response.json()["code"] == "RATE_LIMITED"
    assert second_response.json()["details"]["action"] == "upload.part_presign"

    async with session_factory() as session:
        upload_session = (
            await session.execute(select(UploadSession).where(UploadSession.id == UUID(session_id)))
        ).scalar_one()

    assert upload_session.status == "uploading"


@pytest.mark.asyncio
async def test_upload_part_presign_rate_limit_is_scoped_by_session(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    settings.rate_limit_enabled = True
    settings.upload_part_presign_rate_limit_count = 1
    settings.upload_part_presign_rate_limit_window_seconds = 60
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="rate-part-session-scope")

    session_ids: list[str] = []
    for index in range(2):
        init_response = await client.post(
            "/api/v1/uploads/init",
            headers={"X-CSRF-Token": token},
            json={
                "space_id": space["id"],
                "parent_id": space["root_node_id"],
                "file_name": f"part-{index}.bin",
                "size_bytes": 1024,
                "content_hash": f"{index + 4}" * 64,
                "hash_algo": "sha256",
            },
        )
        assert init_response.status_code == 201
        session_ids.append(str(init_response.json()["session_id"]))

    responses = [
        await client.post(
            f"/api/v1/uploads/{session_id}/parts/1/presign",
            headers={"X-CSRF-Token": token},
        )
        for session_id in session_ids
    ]

    assert [response.status_code for response in responses] == [200, 200]


@pytest.mark.asyncio
async def test_download_presign_rate_limit_blocks_second_request(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    storage_adapter: InMemoryStorageAdapter,
) -> None:
    settings.rate_limit_enabled = True
    settings.download_presign_rate_limit_count = 1
    settings.download_presign_rate_limit_window_seconds = 60
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="rate-download-space")
    completed = await complete_small_file(
        client,
        token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        file_name="download.bin",
    )

    first_response = await client.get(
        f"/api/v1/files/{completed['node_id']}/download",
        headers={"X-CSRF-Token": token},
    )
    second_response = await client.get(
        f"/api/v1/files/{completed['node_id']}/download",
        headers={"X-CSRF-Token": token},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 429
    assert second_response.json()["code"] == "RATE_LIMITED"
    assert second_response.json()["details"]["action"] == "file.download_presign"
    assert len(storage_adapter.presigned_downloads) == 1

    async with session_factory() as session:
        download_audits = (
            (await session.execute(select(AuditLog).where(AuditLog.action == "file.downloaded")))
            .scalars()
            .all()
        )

    assert len(download_audits) == 1
