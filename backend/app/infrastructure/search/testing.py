from __future__ import annotations

import re
from html import escape

from app.infrastructure.search.base import FileSearchDocument, SearchHit, SearchQuery, SearchResult


class InMemorySearchIndexAdapter:
    def __init__(self) -> None:
        self.documents: dict[str, FileSearchDocument] = {}
        self.deleted_document_ids: list[str] = []

    async def upsert_file_document(self, document: FileSearchDocument) -> None:
        self.documents[document.document_id] = document

    async def delete_file_document(self, *, tenant_id: str, node_id: str) -> None:
        document_id = f"{tenant_id}:{node_id}"
        self.documents.pop(document_id, None)
        self.deleted_document_ids.append(document_id)

    async def search_files(self, query: SearchQuery) -> SearchResult:
        query_text = query.query.casefold()
        hits = [
            document
            for document in self.documents.values()
            if document.tenant_id == query.tenant_id
            and not document.is_deleted
            and any(token in document.acl_tokens for token in query.acl_tokens)
            and not any(token in document.deny_acl_tokens for token in query.deny_acl_tokens)
            and (
                query_text in document.name.casefold()
                or query_text in document.normalized_name.casefold()
                or query_text in document.content.casefold()
            )
        ]
        hits.sort(key=_sort_key)
        if query.search_after is not None:
            hits = _after_cursor(hits, query.search_after)
        return SearchResult(
            total=len(hits),
            hits=[
                SearchHit(
                    node_id=document.node_id,
                    space_id=document.space_id,
                    name=document.name,
                    mime_type=document.mime_type,
                    size_bytes=document.size_bytes,
                    updated_at=document.updated_at,
                    score=None,
                    highlights=_highlights(document, query.query),
                    sort_values=_sort_values(document),
                )
                for document in hits[: query.limit]
            ],
        )


def _sort_key(document: FileSearchDocument) -> tuple[float, str, str]:
    return (-document.updated_at.timestamp(), document.node_id, document.document_id)


def _sort_values(document: FileSearchDocument) -> list[object]:
    return [None, document.updated_at.isoformat(), document.node_id]


def _after_cursor(
    documents: list[FileSearchDocument],
    search_after: list[object],
) -> list[FileSearchDocument]:
    for index, document in enumerate(documents):
        if _sort_values(document) == search_after:
            return documents[index + 1 :]
    return documents


def _highlights(document: FileSearchDocument, query: str) -> dict[str, list[str]]:
    highlights: dict[str, list[str]] = {}
    _append_highlight(highlights, "name", document.name, query)
    _append_highlight(highlights, "normalized_name", document.normalized_name, query)
    _append_highlight(highlights, "content", document.content, query)
    return highlights


def _append_highlight(
    highlights: dict[str, list[str]],
    field: str,
    value: str,
    query: str,
) -> None:
    if not value or query.casefold() not in value.casefold():
        return
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    fragments: list[str] = []
    position = 0
    for match in pattern.finditer(value):
        fragments.append(escape(value[position : match.start()]))
        fragments.append(f"<mark>{escape(match.group(0))}</mark>")
        position = match.end()
    fragments.append(escape(value[position:]))
    highlights[field] = ["".join(fragments)]
