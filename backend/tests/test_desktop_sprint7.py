from __future__ import annotations

import hashlib
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.security import utc_now
from app.infrastructure.storage.testing import InMemoryStorageAdapter
from app.modules.sync.cursor import SyncCursor, encode_sync_cursor
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


def _device_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Device {token}"}


async def _register_device(
    client: AsyncClient,
    *,
    installation_id: UUID,
    device_name: str = "Windows 测试设备",
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/device-sessions/register",
        json={
            "tenant_slug": "default",
            "username": "admin",
            "password": "admin-password",
            "installation_id": str(installation_id),
            "device_name": device_name,
            "platform": "windows",
            "client_version": "0.5.0",
        },
    )
    assert response.status_code == 200
    return dict(response.json())


@pytest.mark.asyncio
async def test_device_session_rotation_and_revocation(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    first = await _register_device(client, installation_id=uuid4())
    first_token = str(first["access_token"])
    first_device = dict(first["device"])

    profile = await client.get("/api/v1/auth/me", headers=_device_headers(first_token))
    created_space = await client.post(
        "/api/v1/spaces",
        headers=_device_headers(first_token),
        json={"slug": "device-auth-space", "name": "设备认证空间", "space_type": "team"},
    )
    devices = await client.get(
        "/api/v1/device-sessions",
        headers=_device_headers(first_token),
    )

    assert profile.status_code == 200
    assert created_space.status_code == 201
    assert devices.status_code == 200
    assert devices.json()["items"][0]["current"] is True

    rotated = await client.post(
        "/api/v1/device-sessions/rotate",
        headers=_device_headers(first_token),
        json={"client_version": "0.5.0"},
    )
    assert rotated.status_code == 200
    rotated_token = str(rotated.json()["access_token"])
    assert rotated_token != first_token

    old_access = await client.get("/api/v1/auth/me", headers=_device_headers(first_token))
    new_access = await client.get("/api/v1/auth/me", headers=_device_headers(rotated_token))
    assert old_access.status_code == 401
    assert old_access.json()["code"] == "DEVICE_SESSION_REVOKED"
    assert new_access.status_code == 200

    reused = await client.post(
        "/api/v1/device-sessions/rotate",
        headers=_device_headers(first_token),
        json={},
    )
    revoked_family = await client.get(
        "/api/v1/auth/me",
        headers=_device_headers(rotated_token),
    )
    assert reused.status_code == 401
    assert reused.json()["code"] == "DEVICE_SESSION_REUSED"
    assert revoked_family.status_code == 401

    replacement = await _register_device(
        client,
        installation_id=uuid4(),
        device_name="可吊销设备",
    )
    replacement_token = str(replacement["access_token"])
    replacement_device_id = str(dict(replacement["device"])["id"])
    revoked = await client.delete(
        f"/api/v1/device-sessions/{replacement_device_id}",
        headers=_device_headers(replacement_token),
    )
    denied_after_revoke = await client.get(
        "/api/v1/auth/me",
        headers=_device_headers(replacement_token),
    )
    assert revoked.status_code == 200
    assert revoked.json()["revoked_device_ids"] == [replacement_device_id]
    assert denied_after_revoke.status_code == 401
    assert first_device["id"] != replacement_device_id


@pytest.mark.asyncio
async def test_incremental_cursor_tombstone_and_client_operation_replay(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space = await create_space(client, csrf_token, slug="desktop-sync-space")
    space_id = str(space["id"])
    root_node_id = str(space["root_node_id"])

    anchor = await client.get(
        "/api/v1/sync/changes",
        params={"space_id": space_id, "root_node_id": root_node_id},
    )
    assert anchor.status_code == 200
    assert anchor.json()["items"] == []
    cursor = str(anchor.json()["next_cursor"])

    create_headers = {
        "X-CSRF-Token": csrf_token,
        "X-Client-Operation-ID": "desktop-create-folder-1",
    }
    created = await client.post(
        "/api/v1/files/folders",
        headers=create_headers,
        json={
            "space_id": space_id,
            "parent_id": root_node_id,
            "name": "同步目录",
        },
    )
    replayed = await client.post(
        "/api/v1/files/folders",
        headers=create_headers,
        json={
            "space_id": space_id,
            "parent_id": root_node_id,
            "name": "同步目录",
        },
    )
    reused = await client.post(
        "/api/v1/files/folders",
        headers=create_headers,
        json={
            "space_id": space_id,
            "parent_id": root_node_id,
            "name": "另一个目录",
        },
    )
    assert created.status_code == 201
    assert replayed.status_code == 201
    assert replayed.json()["id"] == created.json()["id"]
    assert reused.status_code == 409
    assert reused.json()["code"] == "CLIENT_OPERATION_ID_REUSED"

    first_changes = await client.get(
        "/api/v1/sync/changes",
        params={
            "space_id": space_id,
            "root_node_id": root_node_id,
            "cursor": cursor,
        },
    )
    assert first_changes.status_code == 200
    created_items = [
        item for item in first_changes.json()["items"] if item["node_id"] == created.json()["id"]
    ]
    assert len(created_items) == 1
    assert created_items[0]["change_type"] == "created"
    assert created_items[0]["tombstone"] is False
    assert created_items[0]["client_operation_id"] == "desktop-create-folder-1"
    cursor = str(first_changes.json()["next_cursor"])

    target = await create_folder(
        client,
        csrf_token,
        space_id=space_id,
        parent_id=root_node_id,
        name="目标目录",
    )
    renamed = await client.patch(
        f"/api/v1/files/{created.json()['id']}",
        headers={
            "X-CSRF-Token": csrf_token,
            "X-Client-Operation-ID": "desktop-rename-1",
        },
        json={"name": "已重命名"},
    )
    moved = await client.post(
        f"/api/v1/files/{created.json()['id']}/move",
        headers={
            "X-CSRF-Token": csrf_token,
            "X-Client-Operation-ID": "desktop-move-1",
        },
        json={"target_parent_id": target["id"]},
    )
    assert renamed.status_code == 200
    assert moved.status_code == 200

    moved_changes = await client.get(
        "/api/v1/sync/changes",
        params={
            "space_id": space_id,
            "root_node_id": root_node_id,
            "cursor": cursor,
        },
    )
    assert moved_changes.status_code == 200
    source_changes = [
        item for item in moved_changes.json()["items"] if item["node_id"] == created.json()["id"]
    ]
    assert [item["change_type"] for item in source_changes] == ["renamed", "moved"]
    assert source_changes[-1]["parent_id"] == target["id"]
    cursor = str(moved_changes.json()["next_cursor"])

    deleted = await client.delete(
        f"/api/v1/files/{created.json()['id']}",
        headers={
            "X-CSRF-Token": csrf_token,
            "X-Client-Operation-ID": "desktop-delete-1",
        },
    )
    deleted_changes = await client.get(
        "/api/v1/sync/changes",
        params={
            "space_id": space_id,
            "root_node_id": root_node_id,
            "cursor": cursor,
        },
    )
    assert deleted.status_code == 200
    tombstone = next(
        item
        for item in deleted_changes.json()["items"]
        if item["node_id"] == created.json()["id"] and item["change_type"] == "deleted"
    )
    assert tombstone["tombstone"] is True
    assert tombstone["name"] is None
    assert tombstone["client_operation_id"] == "desktop-delete-1"

    wrong_scope = await client.get(
        "/api/v1/sync/changes",
        params={
            "space_id": space_id,
            "root_node_id": target["id"],
            "cursor": deleted_changes.json()["next_cursor"],
        },
    )
    assert wrong_scope.status_code == 400
    assert wrong_scope.json()["code"] == "SYNC_CURSOR_SCOPE_MISMATCH"

    expired_cursor = encode_sync_cursor(
        settings,
        SyncCursor(
            tenant_id=UUID(str(space["tenant_id"])),
            user_id=UUID(profile_id := str((await client.get("/api/v1/auth/me")).json()["id"])),
            space_id=UUID(space_id),
            root_node_id=UUID(root_node_id),
            sequence=0,
            issued_at=utc_now() - timedelta(days=settings.sync_cursor_ttl_days + 1),
        ),
    )
    assert profile_id
    expired = await client.get(
        "/api/v1/sync/changes",
        params={
            "space_id": space_id,
            "root_node_id": root_node_id,
            "cursor": expired_cursor,
        },
    )
    assert expired.status_code == 410
    assert expired.json()["code"] == "SYNC_CURSOR_EXPIRED"
    assert expired.json()["details"]["requires_full_resync"] is True


@pytest.mark.asyncio
async def test_dtp_batch_presign_and_file_version_precondition(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    storage_adapter: InMemoryStorageAdapter,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space = await create_space(client, csrf_token, slug="desktop-transfer-space")
    size_bytes = settings.upload_part_size_bytes + 1024
    content_hash = hashlib.sha256(b"\x00" * size_bytes).hexdigest()
    init_headers = {
        "X-CSRF-Token": csrf_token,
        "X-Client-Operation-ID": "desktop-upload-init-1",
    }
    init_payload = {
        "space_id": space["id"],
        "parent_id": space["root_node_id"],
        "file_name": "desktop-large.bin",
        "size_bytes": size_bytes,
        "content_hash": content_hash,
        "hash_algo": "sha256",
        "mime_type": "application/octet-stream",
    }
    initialized = await client.post(
        "/api/v1/uploads/init",
        headers=init_headers,
        json=init_payload,
    )
    replayed_init = await client.post(
        "/api/v1/uploads/init",
        headers=init_headers,
        json=init_payload,
    )
    assert initialized.status_code == 201
    assert initialized.json()["mode"] == "multipart"
    assert initialized.json()["max_parallelism"] == settings.upload_max_parallelism
    assert initialized.json()["checksum_algorithm"] == "sha256"
    assert initialized.json()["client_operation_id"] == "desktop-upload-init-1"
    assert replayed_init.json()["session_id"] == initialized.json()["session_id"]
    session_id = str(initialized.json()["session_id"])

    batch = await client.post(
        f"/api/v1/uploads/{session_id}/parts/presign",
        headers={"X-CSRF-Token": csrf_token},
        json={"part_numbers": [1, 2]},
    )
    duplicate_parts = await client.post(
        f"/api/v1/uploads/{session_id}/parts/presign",
        headers={"X-CSRF-Token": csrf_token},
        json={"part_numbers": [1, 1]},
    )
    assert batch.status_code == 200
    assert [item["part_no"] for item in batch.json()["items"]] == [1, 2]
    assert batch.json()["max_parallelism"] == settings.upload_max_parallelism
    assert duplicate_parts.status_code == 422
    assert duplicate_parts.json()["code"] == "UPLOAD_PART_INVALID"

    confirmed_one = await client.post(
        f"/api/v1/uploads/{session_id}/parts/1/confirm",
        headers={"X-CSRF-Token": csrf_token},
        json={"etag": "desktop-part-1", "size_bytes": settings.upload_part_size_bytes},
    )
    confirmed_two = await client.post(
        f"/api/v1/uploads/{session_id}/parts/2/confirm",
        headers={"X-CSRF-Token": csrf_token},
        json={"etag": "desktop-part-2", "size_bytes": 1024},
    )
    status_response = await client.get(f"/api/v1/uploads/{session_id}")
    assert confirmed_one.status_code == 200
    assert confirmed_two.json()["uploaded_parts"] == [1, 2]
    assert status_response.json()["uploaded_parts"] == [1, 2]

    completed = await client.post(
        f"/api/v1/uploads/{session_id}/complete",
        headers={
            "X-CSRF-Token": csrf_token,
            "X-Client-Operation-ID": "desktop-upload-complete-1",
        },
        json={
            "parts": [
                {
                    "part_no": 1,
                    "etag": "desktop-part-1",
                    "size_bytes": settings.upload_part_size_bytes,
                },
                {"part_no": 2, "etag": "desktop-part-2", "size_bytes": 1024},
            ]
        },
    )
    assert completed.status_code == 200
    assert completed.json()["client_operation_id"] == "desktop-upload-complete-1"
    node_id = str(completed.json()["node_id"])
    version_id = str(completed.json()["version_id"])

    conflict = await client.patch(
        f"/api/v1/files/{node_id}",
        headers={
            "X-CSRF-Token": csrf_token,
            "X-Client-Operation-ID": "desktop-version-conflict-1",
        },
        json={
            "name": "conflict.bin",
            "expected_current_version_id": str(uuid4()),
        },
    )
    renamed = await client.patch(
        f"/api/v1/files/{node_id}",
        headers={
            "X-CSRF-Token": csrf_token,
            "X-Client-Operation-ID": "desktop-version-rename-1",
        },
        json={
            "name": "renamed-desktop-large.bin",
            "expected_current_version_id": version_id,
        },
    )
    replayed_rename = await client.patch(
        f"/api/v1/files/{node_id}",
        headers={
            "X-CSRF-Token": csrf_token,
            "X-Client-Operation-ID": "desktop-version-rename-1",
        },
        json={
            "name": "renamed-desktop-large.bin",
            "expected_current_version_id": version_id,
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "FILE_VERSION_CONFLICT"
    assert conflict.json()["details"]["actual_current_version_id"] == version_id
    assert renamed.status_code == 200
    assert replayed_rename.status_code == 200
    assert replayed_rename.json()["id"] == node_id
    download = await client.get(f"/api/v1/files/{node_id}/download")
    assert download.status_code == 200
    assert download.json()["hash_algo"] == "sha256"
    assert download.json()["content_hash"] == content_hash
    assert storage_adapter.created_uploads
