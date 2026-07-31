from __future__ import annotations

from typing import Any, cast

import pytest
from opensearchpy import OpenSearch
from opensearchpy.exceptions import NotFoundError

from app.infrastructure.search.base import SearchQuery, SearchResult
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


def _adapter(client: Any) -> OpenSearchIndexAdapter:
    adapter = object.__new__(OpenSearchIndexAdapter)
    adapter.index_name = "drive_files_v1"
    adapter.client = cast(OpenSearch, client)
    return adapter


def _query() -> SearchQuery:
    return SearchQuery(
        tenant_id="tenant-1",
        query="missing",
        acl_tokens=["user:user-1"],
        deny_acl_tokens=[],
        limit=20,
    )


@pytest.mark.asyncio
async def test_missing_index_is_an_empty_search_result() -> None:
    result = await _adapter(_MissingIndexClient()).search_files(_query())

    assert result == SearchResult(total=0, hits=[])


@pytest.mark.asyncio
async def test_other_not_found_errors_are_not_hidden() -> None:
    with pytest.raises(NotFoundError):
        await _adapter(_MissingDocumentClient()).search_files(_query())
