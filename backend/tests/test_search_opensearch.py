from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from opensearchpy import OpenSearch
from opensearchpy.exceptions import NotFoundError, RequestError

from app.infrastructure.search.base import FileSearchDocument, SearchQuery, SearchResult
from app.infrastructure.search.opensearch import OpenSearchIndexAdapter


class _MissingIndexClient:
    def search(self, *, index: str, body: dict[str, object]) -> dict[str, object]:
        raise NotFoundError(
            404,
            "index_not_found_exception",
            {"error": {"type": "index_not_found_exception"}},
        )


class _MissingDocumentClient:
    def search(self, *, index: str, body: dict[str, object]) -> dict[str, object]:
        raise NotFoundError(
            404,
            "document_missing_exception",
            {"error": {"type": "document_missing_exception"}},
        )


class _IndicesClient:
    def __init__(self, *, events: list[str], mapping: dict[str, object] | None = None) -> None:
        self.events = events
        self.mapping = mapping

    def create(
        self,
        *,
        index: str,
        body: dict[str, object],
    ) -> dict[str, object]:
        self.events.append("create")
        if self.mapping is not None:
            raise RequestError(
                400,
                "resource_already_exists_exception",
                {"error": {"type": "resource_already_exists_exception"}},
            )
        mappings = cast(dict[str, object], body["mappings"])
        properties = cast(dict[str, object], mappings["properties"])
        assert properties["node_id"] == {"type": "keyword"}
        assert properties["acl_tokens"] == {"type": "keyword"}
        return {"acknowledged": True}

    def get_mapping(self, *, index: str) -> dict[str, object]:
        self.events.append("mapping")
        assert self.mapping is not None
        return self.mapping


class _IndexingClient:
    def __init__(self, *, mapping: dict[str, object] | None = None) -> None:
        self.events: list[str] = []
        self.indices = _IndicesClient(events=self.events, mapping=mapping)

    def index(
        self,
        *,
        index: str,
        id: str,
        body: dict[str, object],
        refresh: bool,
    ) -> dict[str, object]:
        self.events.append("index")
        return {"result": "created"}


def _adapter(client: Any) -> OpenSearchIndexAdapter:
    adapter = object.__new__(OpenSearchIndexAdapter)
    adapter.index_name = "drive_files_v1"
    adapter.client = cast(OpenSearch, client)
    adapter._index_ready = False
    adapter._index_lock = asyncio.Lock()
    return adapter


def _query() -> SearchQuery:
    return SearchQuery(
        tenant_id="tenant-1",
        query="missing",
        acl_tokens=["user:user-1"],
        deny_acl_tokens=[],
        limit=20,
    )


def _document() -> FileSearchDocument:
    now = datetime.now(UTC)
    return FileSearchDocument(
        document_id="tenant-1:node-1",
        tenant_id="tenant-1",
        space_id="space-1",
        node_id="node-1",
        parent_id="parent-1",
        owner_id="user-1",
        version_id="version-1",
        blob_id="blob-1",
        name="索引测试.txt",
        normalized_name="索引测试.txt",
        mime_type="text/plain",
        size_bytes=128,
        hash_algo="sha256",
        content_hash="a" * 64,
        acl_tokens=["user:user-1"],
        deny_acl_tokens=[],
        created_at=now,
        updated_at=now,
        is_deleted=False,
    )


def _compatible_mapping() -> dict[str, object]:
    keyword_fields = {
        "tenant_id",
        "space_id",
        "node_id",
        "parent_id",
        "owner_id",
        "version_id",
        "blob_id",
        "mime_type",
        "hash_algo",
        "content_hash",
        "acl_tokens",
        "deny_acl_tokens",
    }
    return {
        "drive_files_v1": {
            "mappings": {"properties": {field: {"type": "keyword"} for field in keyword_fields}}
        }
    }


@pytest.mark.asyncio
async def test_upsert_creates_keyword_mapping_before_indexing() -> None:
    client = _IndexingClient()

    await _adapter(client).upsert_file_document(_document())

    assert client.events == ["create", "index"]


@pytest.mark.asyncio
async def test_upsert_accepts_existing_compatible_index() -> None:
    client = _IndexingClient(mapping=_compatible_mapping())

    await _adapter(client).upsert_file_document(_document())

    assert client.events == ["create", "mapping", "index"]


@pytest.mark.asyncio
async def test_upsert_rejects_existing_incompatible_index() -> None:
    client = _IndexingClient(
        mapping={
            "drive_files_v1": {
                "mappings": {
                    "properties": {
                        "node_id": {"type": "text"},
                    }
                }
            }
        }
    )

    with pytest.raises(RuntimeError, match="mapping 不兼容"):
        await _adapter(client).upsert_file_document(_document())

    assert client.events == ["create", "mapping"]


@pytest.mark.asyncio
async def test_missing_index_is_an_empty_search_result() -> None:
    result = await _adapter(_MissingIndexClient()).search_files(_query())

    assert result == SearchResult(total=0, hits=[])


@pytest.mark.asyncio
async def test_other_not_found_errors_are_not_hidden() -> None:
    with pytest.raises(NotFoundError):
        await _adapter(_MissingDocumentClient()).search_files(_query())
