from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.pagination import PageCursor
from app.core.security import utc_now
from app.modules.file.models import FileBlob, FileVersion, Node


class FileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_node(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        parent_id: UUID | None,
        owner_id: UUID,
        node_type: str,
        name: str,
        normalized_name: str,
    ) -> Node:
        node = Node(
            tenant_id=tenant_id,
            space_id=space_id,
            parent_id=parent_id,
            owner_id=owner_id,
            node_type=node_type,
            name=name,
            normalized_name=normalized_name,
        )
        self.session.add(node)
        await self.session.flush()
        return node

    async def get_root_node(self, *, tenant_id: UUID, space_id: UUID) -> Node | None:
        result = await self.session.execute(
            select(Node).where(
                Node.tenant_id == tenant_id,
                Node.space_id == space_id,
                Node.parent_id.is_(None),
                Node.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def get_node(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        node_id: UUID,
        include_deleted: bool = False,
    ) -> Node | None:
        conditions = [
            Node.tenant_id == tenant_id,
            Node.space_id == space_id,
            Node.id == node_id,
        ]
        if not include_deleted:
            conditions.append(Node.is_deleted.is_(False))

        result = await self.session.execute(select(Node).where(*conditions))
        return result.scalar_one_or_none()

    async def get_node_by_id(
        self,
        *,
        tenant_id: UUID,
        node_id: UUID,
        include_deleted: bool = False,
    ) -> Node | None:
        conditions = [
            Node.tenant_id == tenant_id,
            Node.id == node_id,
        ]
        if not include_deleted:
            conditions.append(Node.is_deleted.is_(False))

        result = await self.session.execute(select(Node).where(*conditions))
        return result.scalar_one_or_none()

    async def get_node_path_ids(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        node_id: UUID,
        include_deleted: bool = False,
    ) -> list[UUID] | None:
        node = await self.get_node(
            tenant_id=tenant_id,
            space_id=space_id,
            node_id=node_id,
            include_deleted=include_deleted,
        )
        if node is None:
            return None

        path_ids = [node.id]
        seen = {node.id}
        parent_id = node.parent_id
        while parent_id is not None:
            if len(path_ids) >= 64 or parent_id in seen:
                return None
            parent = await self.get_node(
                tenant_id=tenant_id,
                space_id=space_id,
                node_id=parent_id,
                include_deleted=include_deleted,
            )
            if parent is None:
                return None
            path_ids.append(parent.id)
            seen.add(parent.id)
            parent_id = parent.parent_id
        return list(reversed(path_ids))

    async def get_sibling_by_name(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        parent_id: UUID | None,
        normalized_name: str,
        exclude_node_id: UUID | None = None,
    ) -> Node | None:
        parent_condition = (
            Node.parent_id.is_(None) if parent_id is None else Node.parent_id == parent_id
        )
        conditions = [
            Node.tenant_id == tenant_id,
            Node.space_id == space_id,
            parent_condition,
            func.lower(Node.normalized_name) == normalized_name.lower(),
            Node.is_deleted.is_(False),
        ]
        if exclude_node_id is not None:
            conditions.append(Node.id != exclude_node_id)

        result = await self.session.execute(select(Node).where(*conditions))
        return result.scalar_one_or_none()

    async def list_child_nodes(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        parent_id: UUID,
        include_deleted: bool = False,
    ) -> list[Node]:
        conditions = [
            Node.tenant_id == tenant_id,
            Node.space_id == space_id,
            Node.parent_id == parent_id,
        ]
        if not include_deleted:
            conditions.append(Node.is_deleted.is_(False))

        result = await self.session.execute(select(Node).where(*conditions))
        return list(result.scalars().all())

    async def list_children(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        parent_id: UUID,
        limit: int,
        cursor: PageCursor | None,
    ) -> list[Node]:
        conditions = [
            Node.tenant_id == tenant_id,
            Node.space_id == space_id,
            Node.parent_id == parent_id,
            Node.is_deleted.is_(False),
        ]
        if cursor is not None:
            conditions.append(
                or_(
                    Node.created_at < cursor.created_at,
                    and_(Node.created_at == cursor.created_at, Node.id < cursor.item_id),
                )
            )

        result = await self.session.execute(
            select(Node)
            .where(*conditions)
            .order_by(Node.created_at.desc(), Node.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_current_version_with_blob(
        self,
        *,
        tenant_id: UUID,
        node_id: UUID,
        version_id: UUID,
    ) -> tuple[FileVersion, FileBlob] | None:
        result = await self.session.execute(
            select(FileVersion, FileBlob)
            .join(FileBlob, FileBlob.id == FileVersion.blob_id)
            .where(
                FileVersion.tenant_id == tenant_id,
                FileVersion.node_id == node_id,
                FileVersion.id == version_id,
                FileBlob.tenant_id == tenant_id,
            )
        )
        row = result.one_or_none()
        if row is None:
            return None
        return row[0], row[1]

    async def list_versions_for_nodes(
        self,
        *,
        tenant_id: UUID,
        node_ids: list[UUID],
    ) -> list[FileVersion]:
        if not node_ids:
            return []
        result = await self.session.execute(
            select(FileVersion).where(
                FileVersion.tenant_id == tenant_id,
                FileVersion.node_id.in_(node_ids),
            )
        )
        return list(result.scalars().all())

    async def list_unreferenced_blob_ids(
        self,
        *,
        tenant_id: UUID,
        limit: int,
    ) -> list[UUID]:
        result = await self.session.execute(
            select(FileBlob.id)
            .where(
                FileBlob.tenant_id == tenant_id,
                FileBlob.ref_count == 0,
                FileBlob.status == "active",
                _blob_has_no_versions(),
            )
            .order_by(FileBlob.created_at, FileBlob.id)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_existing_blob_storage_keys(
        self,
        *,
        tenant_id: UUID,
        storage_keys: list[str],
    ) -> set[str]:
        if not storage_keys:
            return set()
        result = await self.session.execute(
            select(FileBlob.storage_key).where(
                FileBlob.tenant_id == tenant_id,
                FileBlob.storage_key.in_(storage_keys),
            )
        )
        return set(result.scalars().all())

    async def mark_blob_deleting(
        self,
        *,
        tenant_id: UUID,
        blob_id: UUID,
    ) -> bool:
        result = await self.session.execute(
            update(FileBlob)
            .where(
                FileBlob.tenant_id == tenant_id,
                FileBlob.id == blob_id,
                FileBlob.ref_count == 0,
                FileBlob.status == "active",
                _blob_has_no_versions(),
            )
            .values(status="deleting")
            .returning(FileBlob.id)
        )
        return result.scalar_one_or_none() is not None

    async def get_deleting_blob_for_update(
        self,
        *,
        tenant_id: UUID,
        blob_id: UUID,
    ) -> FileBlob | None:
        result = await self.session.execute(
            select(FileBlob)
            .where(
                FileBlob.tenant_id == tenant_id,
                FileBlob.id == blob_id,
                FileBlob.ref_count == 0,
                FileBlob.status == "deleting",
                _blob_has_no_versions(),
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def restore_blob_active(
        self,
        *,
        tenant_id: UUID,
        blob_id: UUID,
    ) -> None:
        await self.session.execute(
            update(FileBlob)
            .where(
                FileBlob.tenant_id == tenant_id,
                FileBlob.id == blob_id,
                FileBlob.status == "deleting",
            )
            .values(status="active")
        )

    async def delete_deleting_blob(
        self,
        *,
        tenant_id: UUID,
        blob_id: UUID,
    ) -> bool:
        result = await self.session.execute(
            delete(FileBlob)
            .where(
                FileBlob.tenant_id == tenant_id,
                FileBlob.id == blob_id,
                FileBlob.ref_count == 0,
                FileBlob.status == "deleting",
                _blob_has_no_versions(),
            )
            .returning(FileBlob.id)
        )
        return result.scalar_one_or_none() is not None

    async def decrement_blob_ref_counts(
        self,
        *,
        tenant_id: UUID,
        blob_counts: dict[UUID, int],
    ) -> bool:
        for blob_id, count in blob_counts.items():
            result = await self.session.execute(
                update(FileBlob)
                .where(
                    FileBlob.tenant_id == tenant_id,
                    FileBlob.id == blob_id,
                    FileBlob.ref_count >= count,
                )
                .values(ref_count=FileBlob.ref_count - count)
                .returning(FileBlob.id)
            )
            if result.scalar_one_or_none() is None:
                return False
        return True

    async def delete_versions_for_nodes(
        self,
        *,
        tenant_id: UUID,
        node_ids: list[UUID],
    ) -> None:
        if not node_ids:
            return
        await self.session.execute(
            delete(FileVersion).where(
                FileVersion.tenant_id == tenant_id,
                FileVersion.node_id.in_(node_ids),
            )
        )

    async def delete_node(self, *, tenant_id: UUID, node_id: UUID) -> None:
        await self.session.execute(
            delete(Node).where(Node.tenant_id == tenant_id, Node.id == node_id)
        )

    async def bump_node_permission_version(self, *, tenant_id: UUID, node_id: UUID) -> int:
        await self.session.execute(
            update(Node)
            .where(Node.tenant_id == tenant_id, Node.id == node_id)
            .values(permission_version=Node.permission_version + 1, updated_at=utc_now())
        )
        await self.session.flush()
        result = await self.session.execute(
            select(Node.permission_version).where(Node.tenant_id == tenant_id, Node.id == node_id)
        )
        return int(result.scalar_one())

    async def flush(self) -> None:
        await self.session.flush()

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()


def _blob_has_no_versions() -> ColumnElement[bool]:
    return ~(
        select(FileVersion.id)
        .where(
            FileVersion.tenant_id == FileBlob.tenant_id,
            FileVersion.blob_id == FileBlob.id,
        )
        .exists()
    )
