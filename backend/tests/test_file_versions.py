from __future__ import annotations

import hashlib
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.infrastructure.storage.testing import InMemoryStorageAdapter
from app.modules.audit.models import AuditLog, OutboxEvent
from app.modules.file.models import FileBlob, FileVersion, Node
from app.modules.quota.models import QuotaAccount, QuotaLedger
from tests.helpers import (
    add_space_member,
    create_second_user,
    create_space,
    login,
    seed_admin,
)
from tests.helpers import (
    client as client,
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


def _zero_bytes_sha256(size_bytes: int) -> str:
    return hashlib.sha256(b"\x00" * size_bytes).hexdigest()


async def _complete_file(
    client: AsyncClient,
    csrf_token: str,
    *,
    space_id: str,
    parent_id: str,
    file_name: str,
) -> dict[str, str]:
    init_response = await client.post(
        "/api/v1/uploads/init",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "space_id": space_id,
            "parent_id": parent_id,
            "file_name": file_name,
            "size_bytes": 1024,
            "content_hash": _zero_bytes_sha256(1024),
            "hash_algo": "sha256",
            "mime_type": "text/plain",
        },
    )
    assert init_response.status_code == 201
    complete_response = await client.post(
        f"/api/v1/uploads/{init_response.json()['session_id']}/complete",
        headers={"X-CSRF-Token": csrf_token},
        json={"parts": [{"part_no": 1, "etag": "version-etag", "size_bytes": 1024}]},
    )
    assert complete_response.status_code == 200
    return dict(complete_response.json())


@pytest.mark.asyncio
async def test_file_version_list_download_and_rollback_create_new_version(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    storage_adapter: InMemoryStorageAdapter,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="file-version-workflow")
    completed = await _complete_file(
        client,
        token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        file_name="版本文件.txt",
    )
    node_id = completed["node_id"]
    source_version_id = completed["version_id"]

    first_page = await client.get(
        f"/api/v1/files/{node_id}/versions",
        params={"page_size": 1},
        headers={"X-Request-ID": "req_versions_before"},
    )
    assert first_page.status_code == 200
    assert first_page.json()["items"][0]["id"] == source_version_id
    assert first_page.json()["items"][0]["is_current"] is True
    assert first_page.json()["next_cursor"] is None

    rollback = await client.post(
        f"/api/v1/files/{node_id}/versions/{source_version_id}/rollback",
        headers={"X-CSRF-Token": token, "X-Request-ID": "req_version_rollback"},
        json={"expected_current_version_id": source_version_id},
    )
    assert rollback.status_code == 200
    rollback_payload = rollback.json()
    new_version_id = rollback_payload["new_version_id"]
    assert new_version_id != source_version_id
    assert rollback_payload["version_no"] == 2
    assert rollback_payload["current_version_id"] == new_version_id

    versions_page_one = await client.get(
        f"/api/v1/files/{node_id}/versions",
        params={"page_size": 1},
    )
    assert versions_page_one.status_code == 200
    page_one_payload = versions_page_one.json()
    assert page_one_payload["items"][0]["id"] == new_version_id
    assert page_one_payload["items"][0]["is_current"] is True
    assert page_one_payload["next_cursor"]

    versions_page_two = await client.get(
        f"/api/v1/files/{node_id}/versions",
        params={"page_size": 1, "cursor": page_one_payload["next_cursor"]},
    )
    assert versions_page_two.status_code == 200
    assert versions_page_two.json()["items"][0]["id"] == source_version_id
    assert versions_page_two.json()["items"][0]["is_current"] is False
    assert versions_page_two.json()["next_cursor"] is None

    historical_download = await client.get(
        f"/api/v1/files/{node_id}/versions/{source_version_id}/download",
        headers={"X-Request-ID": "req_version_download"},
    )
    assert historical_download.status_code == 200
    assert historical_download.json()["protocol_version"] == "DTP/1"
    assert historical_download.json()["version_id"] == source_version_id
    assert storage_adapter.presigned_downloads[-1][1].startswith("objects/")

    async with session_factory() as session:
        node = (await session.execute(select(Node).where(Node.id == UUID(node_id)))).scalar_one()
        versions = (
            (
                await session.execute(
                    select(FileVersion)
                    .where(FileVersion.node_id == UUID(node_id))
                    .order_by(FileVersion.version_no)
                )
            )
            .scalars()
            .all()
        )
        blob = (
            await session.execute(select(FileBlob).where(FileBlob.id == versions[0].blob_id))
        ).scalar_one()
        quota_account = (await session.execute(select(QuotaAccount))).scalar_one()
        ledgers = (
            (
                await session.execute(
                    select(QuotaLedger).where(QuotaLedger.reason == "file_version_created")
                )
            )
            .scalars()
            .all()
        )
        rollback_audit = (
            await session.execute(
                select(AuditLog).where(AuditLog.action == "file.version.rolled_back")
            )
        ).scalar_one()
        version_download_audit = (
            await session.execute(
                select(AuditLog).where(AuditLog.action == "file.version.downloaded")
            )
        ).scalar_one()
        rollback_events = (
            (
                await session.execute(
                    select(OutboxEvent).where(
                        OutboxEvent.event_type.in_(
                            [
                                "search.index_requested",
                                "search.extract_requested",
                                "preview.render_requested",
                            ]
                        ),
                        OutboxEvent.payload["reason"].as_string() == "file_version_rollback",
                    )
                )
            )
            .scalars()
            .all()
        )

    assert node.current_version_id == UUID(new_version_id)
    assert [version.version_no for version in versions] == [1, 2]
    assert versions[0].blob_id == versions[1].blob_id
    assert blob.ref_count == 2
    assert quota_account.used_bytes == 2048
    assert len(ledgers) == 2
    assert {ledger.ref_id for ledger in ledgers} == {
        UUID(source_version_id),
        UUID(new_version_id),
    }
    assert rollback_audit.request_id == "req_version_rollback"
    assert rollback_audit.metadata_json["source_version_id"] == source_version_id
    assert rollback_audit.metadata_json["new_version_id"] == new_version_id
    assert version_download_audit.request_id == "req_version_download"
    assert {event.event_type for event in rollback_events} == {
        "search.index_requested",
        "search.extract_requested",
        "preview.render_requested",
    }


@pytest.mark.asyncio
async def test_viewer_can_list_and_download_versions_but_cannot_rollback(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    admin_token = await login(client)
    space = await create_space(client, admin_token, slug="file-version-viewer")
    completed = await _complete_file(
        client,
        admin_token,
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        file_name="viewer-version.txt",
    )
    await create_second_user(session_factory)
    await add_space_member(
        session_factory,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
        role="viewer",
    )
    viewer_token = await login(client, username="member", password="member-password")

    versions = await client.get(f"/api/v1/files/{completed['node_id']}/versions")
    download = await client.get(
        f"/api/v1/files/{completed['node_id']}/versions/{completed['version_id']}/download"
    )
    rollback = await client.post(
        f"/api/v1/files/{completed['node_id']}/versions/{completed['version_id']}/rollback",
        headers={"X-CSRF-Token": viewer_token},
        json={},
    )

    assert versions.status_code == 200
    assert download.status_code == 200
    assert rollback.status_code == 404
    assert rollback.json()["code"] == "NODE_NOT_FOUND"
