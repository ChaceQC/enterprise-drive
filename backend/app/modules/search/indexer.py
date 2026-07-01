from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.infrastructure.search.base import FileSearchDocument, SearchIndexAdapter
from app.modules.search.acl import build_index_acl_token_set
from app.modules.search.repository import FileIndexRecord, SearchRepository


@dataclass(frozen=True)
class SearchAclRebuildResult:
    scanned: int
    indexed: int


class SearchIndexService:
    def __init__(self, *, repository: SearchRepository, index_adapter: SearchIndexAdapter) -> None:
        self.repository = repository
        self.index_adapter = index_adapter

    async def index_file(self, *, tenant_id: UUID, node_id: UUID) -> bool:
        record = await self.repository.get_file_index_record(tenant_id=tenant_id, node_id=node_id)
        if record is None:
            await self.index_adapter.delete_file_document(
                tenant_id=str(tenant_id),
                node_id=str(node_id),
            )
            return False
        await self.index_adapter.upsert_file_document(build_file_search_document(record))
        return True

    async def rebuild_acl_tokens(
        self,
        *,
        tenant_id: UUID,
        scope: str,
        resource_id: UUID,
    ) -> SearchAclRebuildResult:
        if scope == "space":
            node_ids = await self.repository.list_active_file_node_ids_for_space(
                tenant_id=tenant_id,
                space_id=resource_id,
            )
        elif scope == "node":
            node_ids = await self.repository.list_active_file_node_ids_under_node(
                tenant_id=tenant_id,
                node_id=resource_id,
            )
        else:
            raise ValueError(f"unsupported search acl rebuild scope: {scope}")

        indexed = 0
        for node_id in node_ids:
            if await self.index_file(tenant_id=tenant_id, node_id=node_id):
                indexed += 1
        return SearchAclRebuildResult(scanned=len(node_ids), indexed=indexed)


def build_file_search_document(record: FileIndexRecord) -> FileSearchDocument:
    token_set = build_index_acl_token_set(
        space_members=record.space_members,
        acl_entries=[
            entry
            for entry in record.acl_entries
            if entry.node_id == record.node.id or entry.inherit
        ],
    )
    return FileSearchDocument(
        document_id=f"{record.node.tenant_id}:{record.node.id}",
        tenant_id=str(record.node.tenant_id),
        space_id=str(record.node.space_id),
        node_id=str(record.node.id),
        parent_id=str(record.node.parent_id) if record.node.parent_id else None,
        owner_id=str(record.node.owner_id),
        version_id=str(record.version.id),
        blob_id=str(record.blob.id),
        name=record.node.name,
        normalized_name=record.node.normalized_name,
        mime_type=record.version.mime_type or record.blob.mime_type,
        size_bytes=record.version.size_bytes,
        hash_algo=record.blob.hash_algo,
        content_hash=record.blob.content_hash,
        acl_tokens=token_set.allow_tokens,
        deny_acl_tokens=token_set.deny_tokens,
        created_at=record.node.created_at,
        updated_at=record.node.updated_at,
        is_deleted=record.node.is_deleted,
    )
