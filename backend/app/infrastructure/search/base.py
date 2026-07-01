from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class FileSearchDocument:
    document_id: str
    tenant_id: str
    space_id: str
    node_id: str
    parent_id: str | None
    owner_id: str
    version_id: str
    blob_id: str
    name: str
    normalized_name: str
    mime_type: str | None
    size_bytes: int
    hash_algo: str
    content_hash: str
    acl_tokens: list[str]
    deny_acl_tokens: list[str]
    created_at: datetime
    updated_at: datetime
    is_deleted: bool
    content: str = ""

    def to_opensearch(self) -> dict[str, object]:
        return {
            "tenant_id": self.tenant_id,
            "space_id": self.space_id,
            "node_id": self.node_id,
            "parent_id": self.parent_id,
            "owner_id": self.owner_id,
            "version_id": self.version_id,
            "blob_id": self.blob_id,
            "name": self.name,
            "normalized_name": self.normalized_name,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "hash_algo": self.hash_algo,
            "content_hash": self.content_hash,
            "acl_tokens": self.acl_tokens,
            "deny_acl_tokens": self.deny_acl_tokens,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "is_deleted": self.is_deleted,
            "content": self.content,
        }


@dataclass(frozen=True)
class SearchHit:
    node_id: str
    space_id: str
    name: str
    mime_type: str | None
    size_bytes: int
    updated_at: datetime
    score: float | None = None


@dataclass(frozen=True)
class SearchQuery:
    tenant_id: str
    query: str
    acl_tokens: list[str]
    deny_acl_tokens: list[str]
    limit: int


@dataclass(frozen=True)
class SearchResult:
    total: int
    hits: list[SearchHit]


class SearchIndexAdapter(Protocol):
    async def upsert_file_document(self, document: FileSearchDocument) -> None: ...

    async def delete_file_document(self, *, tenant_id: str, node_id: str) -> None: ...

    async def search_files(self, query: SearchQuery) -> SearchResult: ...
