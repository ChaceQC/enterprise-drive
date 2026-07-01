from __future__ import annotations

import asyncio

from opensearchpy import OpenSearch

from app.core.config import Settings
from app.infrastructure.search.base import FileSearchDocument


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


def _document_id(*, tenant_id: str, node_id: str) -> str:
    return f"{tenant_id}:{node_id}"
