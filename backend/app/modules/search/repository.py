from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.file.models import FileBlob, FileVersion, Node
from app.modules.permission.models import AclEntry, SpaceMember


@dataclass(frozen=True)
class FileIndexRecord:
    node: Node
    version: FileVersion
    blob: FileBlob
    path_ids: list[UUID]
    space_members: list[SpaceMember]
    acl_entries: list[AclEntry]


class SearchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_file_index_record(
        self,
        *,
        tenant_id: UUID,
        node_id: UUID,
    ) -> FileIndexRecord | None:
        result = await self.session.execute(
            select(Node, FileVersion, FileBlob)
            .join(
                FileVersion,
                (FileVersion.tenant_id == Node.tenant_id)
                & (FileVersion.id == Node.current_version_id)
                & (FileVersion.node_id == Node.id),
            )
            .join(
                FileBlob,
                (FileBlob.tenant_id == FileVersion.tenant_id)
                & (FileBlob.id == FileVersion.blob_id),
            )
            .where(
                Node.tenant_id == tenant_id,
                Node.id == node_id,
                Node.node_type == "file",
                Node.is_deleted.is_(False),
            )
        )
        row = result.one_or_none()
        if row is None:
            return None
        node = row[0]
        path_ids = await self.get_node_path_ids(
            tenant_id=tenant_id,
            space_id=node.space_id,
            node_id=node.id,
        )
        if path_ids is None:
            return None
        return FileIndexRecord(
            node=node,
            version=row[1],
            blob=row[2],
            path_ids=path_ids,
            space_members=await self.list_space_members(
                tenant_id=tenant_id,
                space_id=node.space_id,
            ),
            acl_entries=await self.list_acl_entries_for_nodes(
                tenant_id=tenant_id,
                node_ids=path_ids,
            ),
        )

    async def get_node_path_ids(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        node_id: UUID,
    ) -> list[UUID] | None:
        result = await self.session.execute(
            select(Node).where(
                Node.tenant_id == tenant_id,
                Node.space_id == space_id,
                Node.id == node_id,
                Node.is_deleted.is_(False),
            )
        )
        node = result.scalar_one_or_none()
        if node is None:
            return None

        path_ids = [node.id]
        seen = {node.id}
        parent_id = node.parent_id
        while parent_id is not None:
            if len(path_ids) >= 64 or parent_id in seen:
                return None
            parent_result = await self.session.execute(
                select(Node).where(
                    Node.tenant_id == tenant_id,
                    Node.space_id == space_id,
                    Node.id == parent_id,
                    Node.is_deleted.is_(False),
                )
            )
            parent = parent_result.scalar_one_or_none()
            if parent is None:
                return None
            path_ids.append(parent.id)
            seen.add(parent.id)
            parent_id = parent.parent_id
        return list(reversed(path_ids))

    async def list_space_members(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
    ) -> list[SpaceMember]:
        result = await self.session.execute(
            select(SpaceMember).where(
                SpaceMember.tenant_id == tenant_id,
                SpaceMember.space_id == space_id,
            )
        )
        return list(result.scalars().all())

    async def list_acl_entries_for_nodes(
        self,
        *,
        tenant_id: UUID,
        node_ids: list[UUID],
    ) -> list[AclEntry]:
        if not node_ids:
            return []
        result = await self.session.execute(
            select(AclEntry).where(
                AclEntry.tenant_id == tenant_id,
                AclEntry.node_id.in_(node_ids),
            )
        )
        return list(result.scalars().all())
