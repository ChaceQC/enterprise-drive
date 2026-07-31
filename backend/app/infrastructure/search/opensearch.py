from __future__ import annotations

import asyncio
from datetime import datetime

from opensearchpy import OpenSearch
from opensearchpy.exceptions import NotFoundError

from app.core.config import Settings
from app.infrastructure.search.base import FileSearchDocument, SearchHit, SearchQuery, SearchResult


class OpenSearchIndexAdapter:
    def __init__(self, *, settings: Settings) -> None:
        self.index_name = settings.opensearch_index_name
        self.client = OpenSearch(hosts=[settings.opensearch_url])

    async def upsert_file_document(self, document: FileSearchDocument) -> None:
        await asyncio.to_thread(
            self.client.index,
            index=self.index_name,
            id=document.document_id,
            body=document.to_opensearch(),
            refresh=False,
        )

    async def delete_file_document(self, *, tenant_id: str, node_id: str) -> None:
        await asyncio.to_thread(
            self.client.delete,
            index=self.index_name,
            id=_document_id(tenant_id=tenant_id, node_id=node_id),
            ignore=[404],
            refresh=False,
        )

    async def search_files(self, query: SearchQuery) -> SearchResult:
        try:
            response = await asyncio.to_thread(
                self.client.search,
                index=self.index_name,
                body=_search_body(query),
            )
        except NotFoundError as exc:
            if _is_index_not_found(exc):
                return SearchResult(total=0, hits=[])
            raise
        hits = response.get("hits", {})
        total = hits.get("total", 0)
        total_value = int(total.get("value", 0)) if isinstance(total, dict) else int(total)
        return SearchResult(
            total=total_value,
            hits=[_parse_hit(hit) for hit in hits.get("hits", [])],
        )


def _is_index_not_found(exc: NotFoundError) -> bool:
    if exc.error == "index_not_found_exception":
        return True
    if not isinstance(exc.info, dict):
        return False
    error = exc.info.get("error")
    return isinstance(error, dict) and error.get("type") == "index_not_found_exception"


def _document_id(*, tenant_id: str, node_id: str) -> str:
    return f"{tenant_id}:{node_id}"


def _search_body(query: SearchQuery) -> dict[str, object]:
    filters: list[dict[str, object]] = [
        {"term": {"tenant_id": query.tenant_id}},
        {"term": {"is_deleted": False}},
        {"terms": {"acl_tokens": query.acl_tokens}},
    ]
    must_not: list[dict[str, object]] = []
    if query.deny_acl_tokens:
        must_not.append({"terms": {"deny_acl_tokens": query.deny_acl_tokens}})
    body: dict[str, object] = {
        "size": query.limit,
        "query": {
            "bool": {
                "must": [
                    {
                        "multi_match": {
                            "query": query.query,
                            "fields": ["name^3", "normalized_name^2", "content"],
                        }
                    }
                ],
                "filter": filters,
                "must_not": must_not,
            }
        },
        "highlight": {
            "pre_tags": ["<mark>"],
            "post_tags": ["</mark>"],
            "encoder": "html",
            "fields": {
                "name": {"number_of_fragments": 0},
                "normalized_name": {"number_of_fragments": 0},
                "content": {"fragment_size": 160, "number_of_fragments": 3},
            },
        },
        "sort": [{"_score": "desc"}, {"updated_at": "desc"}, {"node_id": "asc"}],
    }
    if query.search_after is not None:
        body["search_after"] = query.search_after
    return body


def _parse_hit(hit: dict[str, object]) -> SearchHit:
    source = hit.get("_source")
    if not isinstance(source, dict):
        raise ValueError("OpenSearch hit missing _source")
    return SearchHit(
        node_id=str(source["node_id"]),
        space_id=str(source["space_id"]),
        name=str(source["name"]),
        mime_type=str(source["mime_type"]) if source.get("mime_type") is not None else None,
        size_bytes=int(source["size_bytes"]),
        updated_at=_parse_datetime(source["updated_at"]),
        score=_parse_score(hit.get("_score")),
        highlights=_parse_highlights(hit.get("highlight")),
        sort_values=_parse_sort_values(hit.get("sort")),
    )


def _parse_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise ValueError("OpenSearch hit has invalid updated_at")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _parse_score(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float | str):
        return float(value)
    raise ValueError("OpenSearch hit has invalid _score")


def _parse_highlights(value: object) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    highlights: dict[str, list[str]] = {}
    for field, fragments in value.items():
        if isinstance(fragments, list):
            highlights[str(field)] = [str(fragment) for fragment in fragments]
    return highlights


def _parse_sort_values(value: object) -> list[object]:
    if not isinstance(value, list):
        return []
    sort_values: list[object] = []
    for item in value:
        if isinstance(item, str | int | float | bool) or item is None:
            sort_values.append(item)
        else:
            sort_values.append(str(item))
    return sort_values
