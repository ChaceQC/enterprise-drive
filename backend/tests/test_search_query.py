from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.infrastructure.search.testing import InMemorySearchIndexAdapter
from app.modules.auth.models import User
from app.modules.file.models import FileBlob
from app.modules.permission.actions import ACTION_READ_META
from app.modules.permission.models import AclEntry
from app.modules.search.indexer import SearchIndexService
from app.modules.search.repository import SearchRepository
from tests.helpers import client as client
from tests.helpers import create_space, login, seed_admin
from tests.helpers import search_index_adapter as search_index_adapter
from tests.helpers import session_factory as session_factory
from tests.helpers import settings as settings
from tests.helpers import storage_adapter as storage_adapter


async def _create_instant_file(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    token: str,
    *,
    tenant_id: str,
    space_id: str,
    parent_id: str,
    file_name: str,
    content_hash: str,
    size_bytes: int = 128,
) -> str:
    async with session_factory() as session:
        session.add(
            FileBlob(
                tenant_id=UUID(tenant_id),
                hash_algo="sha256",
                content_hash=content_hash,
                size_bytes=size_bytes,
                storage_key=f"objects/test/{content_hash[:2]}/{content_hash}",
                mime_type="text/plain",
                ref_count=0,
            )
        )
        await session.commit()

    response = await client.post(
        "/api/v1/uploads/init",
        headers={"X-CSRF-Token": token},
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
    payload = response.json()
    assert payload["mode"] == "instant"
    return str(payload["node_id"])


async def _index_file(
    session_factory: async_sessionmaker[AsyncSession],
    search_index_adapter: InMemorySearchIndexAdapter,
    *,
    tenant_id: str,
    node_id: str,
) -> None:
    async with session_factory() as session:
        indexed = await SearchIndexService(
            repository=SearchRepository(session),
            index_adapter=search_index_adapter,
        ).index_file(tenant_id=UUID(tenant_id), node_id=UUID(node_id))
        assert indexed is True


@pytest.mark.asyncio
async def test_search_files_returns_role_visible_indexed_file(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    search_index_adapter: InMemorySearchIndexAdapter,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="search-query-visible")
    node_id = await _create_instant_file(
        client,
        session_factory,
        token,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        file_name="项目计划.txt",
        content_hash="1" * 64,
    )
    await _index_file(
        session_factory,
        search_index_adapter,
        tenant_id=str(space["tenant_id"]),
        node_id=node_id,
    )

    response = await client.get("/api/v1/search", params={"q": "项目", "limit": 10})

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "项目"
    assert payload["total"] == 1
    assert payload["items"][0]["node_id"] == node_id
    assert payload["items"][0]["space_id"] == space["id"]
    assert payload["items"][0]["name"] == "项目计划.txt"
    assert payload["items"][0]["highlights"]["name"] == ["<mark>项目</mark>计划.txt"]
    assert payload["next_cursor"] is None


@pytest.mark.asyncio
async def test_search_files_uses_cursor_pagination_and_query_bound_cursor(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    search_index_adapter: InMemorySearchIndexAdapter,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="search-query-cursor")
    node_ids: list[str] = []
    for index, content_hash in enumerate(["a" * 64, "b" * 64, "c" * 64], start=1):
        node_ids.append(
            await _create_instant_file(
                client,
                session_factory,
                token,
                tenant_id=str(space["tenant_id"]),
                space_id=str(space["id"]),
                parent_id=str(space["root_node_id"]),
                file_name=f"分页文件{index}.txt",
                content_hash=content_hash,
            )
        )
    for index, node_id in enumerate(node_ids, start=1):
        await _index_file(
            session_factory,
            search_index_adapter,
            tenant_id=str(space["tenant_id"]),
            node_id=node_id,
        )
        document_id = f"{space['tenant_id']}:{node_id}"
        document = search_index_adapter.documents[document_id]
        search_index_adapter.documents[document_id] = replace(
            document,
            updated_at=datetime(2026, 7, 1, 0, 0, index, tzinfo=UTC),
        )

    first_response = await client.get("/api/v1/search", params={"q": "分页", "limit": 2})

    assert first_response.status_code == 200
    first_payload = first_response.json()
    assert [item["node_id"] for item in first_payload["items"]] == [node_ids[2], node_ids[1]]
    assert first_payload["next_cursor"] is not None
    assert first_payload["items"][0]["highlights"]["name"] == ["<mark>分页</mark>文件3.txt"]

    second_response = await client.get(
        "/api/v1/search",
        params={"q": "分页", "limit": 2, "cursor": first_payload["next_cursor"]},
    )

    assert second_response.status_code == 200
    second_payload = second_response.json()
    assert [item["node_id"] for item in second_payload["items"]] == [node_ids[0]]
    assert second_payload["next_cursor"] is None

    wrong_query_response = await client.get(
        "/api/v1/search",
        params={"q": "分页文件", "limit": 2, "cursor": first_payload["next_cursor"]},
    )

    assert wrong_query_response.status_code == 400
    assert wrong_query_response.json()["code"] == "CURSOR_INVALID"


@pytest.mark.asyncio
async def test_search_query_layer_excludes_denied_acl_token(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    search_index_adapter: InMemorySearchIndexAdapter,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="search-query-deny-token")
    node_id = await _create_instant_file(
        client,
        session_factory,
        token,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        file_name="拒绝命中.txt",
        content_hash="2" * 64,
    )
    await _index_file(
        session_factory,
        search_index_adapter,
        tenant_id=str(space["tenant_id"]),
        node_id=node_id,
    )
    async with session_factory() as session:
        current_user = (await session.execute(select(User))).scalar_one()
    document_id = f"{space['tenant_id']}:{node_id}"
    document = search_index_adapter.documents[document_id]
    search_index_adapter.documents[document_id] = replace(
        document,
        deny_acl_tokens=[f"user:{current_user.id}"],
    )

    response = await client.get("/api/v1/search", params={"q": "拒绝", "limit": 10})

    assert response.status_code == 200
    assert response.json()["items"] == []


@pytest.mark.asyncio
async def test_search_results_are_rechecked_against_current_permissions(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    search_index_adapter: InMemorySearchIndexAdapter,
) -> None:
    await seed_admin(session_factory, settings)
    token = await login(client)
    space = await create_space(client, token, slug="search-query-recheck")
    node_id = await _create_instant_file(
        client,
        session_factory,
        token,
        tenant_id=str(space["tenant_id"]),
        space_id=str(space["id"]),
        parent_id=str(space["root_node_id"]),
        file_name="滞后索引.txt",
        content_hash="3" * 64,
    )
    await _index_file(
        session_factory,
        search_index_adapter,
        tenant_id=str(space["tenant_id"]),
        node_id=node_id,
    )
    async with session_factory() as session:
        current_user = (await session.execute(select(User))).scalar_one()
        session.add(
            AclEntry(
                tenant_id=current_user.tenant_id,
                node_id=UUID(node_id),
                subject_type="user",
                subject_id=current_user.id,
                effect="deny",
                actions=[ACTION_READ_META],
                inherit=True,
                created_by=current_user.id,
            )
        )
        await session.commit()

    response = await client.get("/api/v1/search", params={"q": "滞后", "limit": 10})

    assert response.status_code == 200
    assert response.json()["items"] == []
