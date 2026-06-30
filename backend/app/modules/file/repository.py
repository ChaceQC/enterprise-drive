from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import PageCursor
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

    async def flush(self) -> None:
        await self.session.flush()

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
