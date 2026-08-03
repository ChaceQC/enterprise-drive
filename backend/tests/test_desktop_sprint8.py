from __future__ import annotations

import hashlib
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.modules.file.models import FileBlob, FileVersion, Node
from app.modules.quota.models import QuotaAccount
from app.modules.upload.models import UploadSession
from tests.helpers import (
    client as client,
)
from tests.helpers import create_space, login, seed_admin
from tests.helpers import (
    session_factory as session_factory,
)
from tests.helpers import (
    settings as settings,
)
from tests.helpers import (
    storage_adapter as storage_adapter,
)


async def add_blob(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    content_hash: str,
    size_bytes: int,
) -> UUID:
    async with session_factory() as session:
        blob = FileBlob(
            tenant_id=tenant_id,
            hash_algo="sha256",
            content_hash=content_hash,
            size_bytes=size_bytes,
            storage_key=f"objects/test/{content_hash[:8]}",
            mime_type="application/octet-stream",
            ref_count=0,
        )
        session.add(blob)
        await session.commit()
        return blob.id


async def instant_upload(
    client: AsyncClient,
    *,
    csrf_token: str,
    space_id: str,
    parent_id: str,
    file_name: str,
    content_hash: str,
    size_bytes: int,
    target_node_id: str | None = None,
    expected_current_version_id: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "space_id": space_id,
        "parent_id": parent_id,
        "file_name": file_name,
        "size_bytes": size_bytes,
        "content_hash": content_hash,
        "hash_algo": "sha256",
        "mime_type": "application/octet-stream",
    }
    if target_node_id is not None:
        payload["target_node_id"] = target_node_id
        payload["expected_current_version_id"] = expected_current_version_id
    response = await client.post(
        "/api/v1/uploads/init",
        headers={
            "X-CSRF-Token": csrf_token,
            "X-Client-Operation-ID": str(uuid4()),
        },
        json=payload,
    )
    assert response.status_code == 201
    assert response.json()["mode"] == "instant"
    return response.json()


@pytest.mark.asyncio
async def test_targeted_instant_upload_creates_new_version_without_replacing_node(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space = await create_space(client, csrf_token, slug="desktop-sprint8-instant")
    tenant_id = UUID(str(space["tenant_id"]))
    first_hash = "1" * 64
    second_hash = "2" * 64
    await add_blob(
        session_factory,
        tenant_id=tenant_id,
        content_hash=first_hash,
        size_bytes=1024,
    )
    await add_blob(
        session_factory,
        tenant_id=tenant_id,
        content_hash=second_hash,
        size_bytes=1024,
    )

    first = await instant_upload(
        client,
        csrf_token=csrf_token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        file_name="双向同步.bin",
        content_hash=first_hash,
        size_bytes=1024,
    )
    second = await instant_upload(
        client,
        csrf_token=csrf_token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        file_name="双向同步.bin",
        content_hash=second_hash,
        size_bytes=1024,
        target_node_id=str(first["node_id"]),
        expected_current_version_id=str(first["version_id"]),
    )

    assert second["node_id"] == first["node_id"]
    assert second["version_id"] != first["version_id"]
    conflict = await client.post(
        "/api/v1/uploads/init",
        headers={
            "X-CSRF-Token": csrf_token,
            "X-Client-Operation-ID": str(uuid4()),
        },
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "file_name": "双向同步.bin",
            "size_bytes": 1024,
            "content_hash": first_hash,
            "hash_algo": "sha256",
            "target_node_id": first["node_id"],
            "expected_current_version_id": first["version_id"],
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "FILE_VERSION_CONFLICT"
    assert conflict.json()["details"]["actual_current_version_id"] == second["version_id"]

    async with session_factory() as session:
        node = (
            await session.execute(select(Node).where(Node.id == UUID(str(first["node_id"]))))
        ).scalar_one()
        versions = (
            (
                await session.execute(
                    select(FileVersion)
                    .where(FileVersion.node_id == node.id)
                    .order_by(FileVersion.version_no)
                )
            )
            .scalars()
            .all()
        )
        quota = (await session.execute(select(QuotaAccount))).scalar_one()

    assert node.current_version_id == UUID(str(second["version_id"]))
    assert [version.version_no for version in versions] == [1, 2]
    assert quota.used_bytes == 2048


@pytest.mark.asyncio
async def test_targeted_multipart_complete_rechecks_remote_version(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space = await create_space(client, csrf_token, slug="desktop-sprint8-multipart")
    tenant_id = UUID(str(space["tenant_id"]))
    initial_hash = "3" * 64
    await add_blob(
        session_factory,
        tenant_id=tenant_id,
        content_hash=initial_hash,
        size_bytes=1024,
    )
    initial = await instant_upload(
        client,
        csrf_token=csrf_token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        file_name="离线恢复.bin",
        content_hash=initial_hash,
        size_bytes=1024,
    )

    size_bytes = settings.upload_part_size_bytes + 64
    initialized = await client.post(
        "/api/v1/uploads/init",
        headers={
            "X-CSRF-Token": csrf_token,
            "X-Client-Operation-ID": str(uuid4()),
        },
        json={
            "space_id": space["id"],
            "parent_id": space["root_node_id"],
            "file_name": "离线恢复.bin",
            "size_bytes": size_bytes,
            "content_hash": hashlib.sha256(b"\x00" * size_bytes).hexdigest(),
            "hash_algo": "sha256",
            "target_node_id": initial["node_id"],
            "expected_current_version_id": initial["version_id"],
        },
    )
    assert initialized.status_code == 201
    assert initialized.json()["mode"] == "multipart"
    session_id = UUID(initialized.json()["session_id"])

    async with session_factory() as session:
        node = (
            await session.execute(select(Node).where(Node.id == UUID(str(initial["node_id"]))))
        ).scalar_one()
        competing_blob = FileBlob(
            tenant_id=tenant_id,
            hash_algo="sha256",
            content_hash="4" * 64,
            size_bytes=2048,
            storage_key="objects/test/competing",
            mime_type="application/octet-stream",
            ref_count=1,
        )
        session.add(competing_blob)
        await session.flush()
        competing_version = FileVersion(
            tenant_id=tenant_id,
            node_id=node.id,
            blob_id=competing_blob.id,
            version_no=2,
            size_bytes=2048,
            mime_type="application/octet-stream",
            created_by=node.owner_id,
        )
        session.add(competing_version)
        await session.flush()
        node.current_version_id = competing_version.id
        competing_version_id = competing_version.id
        await session.commit()

    completed = await client.post(
        f"/api/v1/uploads/{session_id}/complete",
        headers={
            "X-CSRF-Token": csrf_token,
            "X-Client-Operation-ID": str(uuid4()),
        },
        json={
            "parts": [
                {
                    "part_no": 1,
                    "etag": "part-1",
                    "size_bytes": settings.upload_part_size_bytes,
                },
                {"part_no": 2, "etag": "part-2", "size_bytes": 64},
            ]
        },
    )
    assert completed.status_code == 409
    assert completed.json()["code"] == "FILE_VERSION_CONFLICT"
    assert completed.json()["details"]["actual_current_version_id"] == str(competing_version_id)

    async with session_factory() as session:
        upload_session = (
            await session.execute(select(UploadSession).where(UploadSession.id == session_id))
        ).scalar_one()
        node = (
            await session.execute(select(Node).where(Node.id == UUID(str(initial["node_id"]))))
        ).scalar_one()

    assert upload_session.status == "initiated"
    assert upload_session.completed_version_id is None
    assert node.current_version_id == competing_version_id
