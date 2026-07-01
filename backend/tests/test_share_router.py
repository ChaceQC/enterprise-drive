from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.modules.file.models import FileBlob
from app.modules.share.models import Share
from tests.helpers import client as client
from tests.helpers import create_second_user, create_space, login, seed_admin
from tests.helpers import session_factory as session_factory
from tests.helpers import settings as settings
from tests.helpers import storage_adapter as storage_adapter


async def create_instant_file(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    csrf_token: str,
    *,
    tenant_id: str,
    space_id: str,
    parent_id: str,
    file_name: str,
    content_hash: str,
) -> dict[str, object]:
    async with session_factory() as session:
        session.add(
            FileBlob(
                tenant_id=UUID(tenant_id),
                hash_algo="sha256",
                content_hash=content_hash,
                size_bytes=128,
                storage_key=f"objects/test/{content_hash[:2]}/{content_hash}",
                mime_type="text/plain",
                ref_count=0,
            )
        )
        await session.commit()

    response = await client.post(
        "/api/v1/uploads/init",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "space_id": space_id,
            "parent_id": parent_id,
            "file_name": file_name,
            "size_bytes": 128,
            "content_hash": content_hash,
            "hash_algo": "sha256",
            "mime_type": "text/plain",
        },
    )
    assert response.status_code == 201
    return dict(response.json())


@pytest.mark.asyncio
async def test_share_api_create_detail_and_revoke(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space = await create_space(client, csrf_token, slug="share-api-space")
    file_payload = await create_instant_file(
        client,
        session_factory,
        csrf_token,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        file_name="接口分享.txt",
        content_hash="2" * 64,
    )

    create_response = await client.post(
        "/api/v1/shares",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "share_type": "external",
            "root_node_id": file_payload["node_id"],
            "permission": "download",
            "passcode": "123456",
            "max_views": 3,
            "max_downloads": 2,
        },
    )

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["raw_token"]
    assert created["share_type"] == "external"
    assert created["root_node_id"] == file_payload["node_id"]
    assert created["status"] == "active"

    detail_response = await client.get(f"/api/v1/shares/{created['id']}")

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["id"] == created["id"]
    assert detail["download_count"] == 0

    revoke_response = await client.post(
        f"/api/v1/shares/{created['id']}/revoke",
        headers={"X-CSRF-Token": csrf_token},
    )

    assert revoke_response.status_code == 200
    assert revoke_response.json() == {"share_id": created["id"], "revoked": True}

    async with session_factory() as session:
        share = (await session.execute(select(Share))).scalar_one()

    assert share.status == "revoked"


@pytest.mark.asyncio
async def test_share_api_requires_csrf_for_create(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space = await create_space(client, csrf_token, slug="share-api-csrf-space")
    file_payload = await create_instant_file(
        client,
        session_factory,
        csrf_token,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        file_name="缺少 csrf.txt",
        content_hash="3" * 64,
    )

    response = await client.post(
        "/api/v1/shares",
        json={
            "share_type": "external",
            "root_node_id": file_payload["node_id"],
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_TOKEN_INVALID"


@pytest.mark.asyncio
async def test_share_api_hides_share_from_non_creator(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    await seed_admin(session_factory, settings)
    csrf_token = await login(client)
    space = await create_space(client, csrf_token, slug="share-api-owner-space")
    await create_second_user(session_factory)
    file_payload = await create_instant_file(
        client,
        session_factory,
        csrf_token,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        file_name="非创建者.txt",
        content_hash="4" * 64,
    )
    create_response = await client.post(
        "/api/v1/shares",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "share_type": "external",
            "root_node_id": file_payload["node_id"],
        },
    )
    assert create_response.status_code == 201
    share_id = create_response.json()["id"]
    member_csrf = await login(client, username="member", password="member-password")

    detail_response = await client.get(f"/api/v1/shares/{share_id}")
    revoke_response = await client.post(
        f"/api/v1/shares/{share_id}/revoke",
        headers={"X-CSRF-Token": member_csrf},
    )

    assert detail_response.status_code == 404
    assert detail_response.json()["code"] == "SHARE_NOT_FOUND"
    assert revoke_response.status_code == 404
    assert revoke_response.json()["code"] == "SHARE_NOT_FOUND"
