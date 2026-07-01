from __future__ import annotations

from app.infrastructure.search.base import FileSearchDocument


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
