from __future__ import annotations

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
        hits.sort(key=lambda document: (document.updated_at, document.node_id), reverse=True)
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
                )
                for document in hits[: query.limit]
            ],
        )
