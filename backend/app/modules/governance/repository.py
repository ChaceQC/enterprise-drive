from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import CTE

from app.core.pagination import PageCursor
from app.core.security import utc_now
from app.modules.admin.models import AdminJob
from app.modules.file.models import FileBlob, FileTreeOperation, Node
from app.modules.governance.models import LifecyclePolicy, PermissionRebuildOperation
from app.modules.preview.models import PreviewArtifact
from app.modules.share.models import Share
from app.modules.space.models import Space
from app.modules.upload.models import UploadSession


class GovernanceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_lifecycle_policy(self, *, tenant_id: UUID) -> LifecyclePolicy | None:
        result = await self.session.execute(
            select(LifecyclePolicy).where(LifecyclePolicy.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def get_lifecycle_policy_for_update(
        self,
        *,
        tenant_id: UUID,
    ) -> LifecyclePolicy | None:
        result = await self.session.execute(
            select(LifecyclePolicy).where(LifecyclePolicy.tenant_id == tenant_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def create_lifecycle_policy(
        self,
        *,
        tenant_id: UUID,
        updated_by: UUID,
        trash_retention_days: int,
        preview_retention_days: int,
    ) -> LifecyclePolicy:
        policy = LifecyclePolicy(
            id=uuid4(),
            tenant_id=tenant_id,
            updated_by=updated_by,
            trash_retention_days=trash_retention_days,
            preview_retention_days=preview_retention_days,
        )
        self.session.add(policy)
        await self.session.flush()
        return policy

    async def get_space(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
    ) -> Space | None:
        result = await self.session.execute(
            select(Space).where(Space.tenant_id == tenant_id, Space.id == space_id)
        )
        return result.scalar_one_or_none()

    async def get_node(
        self,
        *,
        tenant_id: UUID,
        node_id: UUID,
    ) -> Node | None:
        result = await self.session.execute(
            select(Node).where(
                Node.tenant_id == tenant_id,
                Node.id == node_id,
                Node.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def create_or_refresh_permission_rebuild(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        root_node_id: UUID | None,
        scope: str,
        permission_version: int,
        requested_by: UUID | None,
        request_id: str | None,
    ) -> tuple[PermissionRebuildOperation, bool]:
        scope_key = _scope_key(scope=scope, resource_id=root_node_id or space_id)
        active = await self.get_active_permission_rebuild(
            tenant_id=tenant_id,
            scope_key=scope_key,
            for_update=True,
        )
        if active is not None:
            if permission_version > active.permission_version:
                active.permission_version = permission_version
                active.restart_requested = True
                active.updated_at = utc_now()
            return active, False

        snapshot_at = utc_now()
        total_count = await self.count_permission_rebuild_files(
            tenant_id=tenant_id,
            space_id=space_id,
            root_node_id=root_node_id,
            snapshot_at=snapshot_at,
        )
        operation = PermissionRebuildOperation(
            id=uuid4(),
            tenant_id=tenant_id,
            space_id=space_id,
            root_node_id=root_node_id,
            scope=scope,
            scope_key=scope_key,
            permission_version=permission_version,
            status="pending",
            snapshot_at=snapshot_at,
            total_count=total_count,
            requested_by=requested_by,
            request_id=request_id,
        )
        self.session.add(operation)
        await self.session.flush()
        return operation, True

    async def get_active_permission_rebuild(
        self,
        *,
        tenant_id: UUID,
        scope_key: str,
        for_update: bool = False,
    ) -> PermissionRebuildOperation | None:
        statement = select(PermissionRebuildOperation).where(
            PermissionRebuildOperation.tenant_id == tenant_id,
            PermissionRebuildOperation.scope_key == scope_key,
            PermissionRebuildOperation.status.in_(["pending", "running"]),
        )
        if for_update:
            statement = statement.with_for_update()
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_permission_rebuild(
        self,
        *,
        tenant_id: UUID,
        operation_id: UUID,
        for_update: bool = False,
    ) -> PermissionRebuildOperation | None:
        statement = select(PermissionRebuildOperation).where(
            PermissionRebuildOperation.tenant_id == tenant_id,
            PermissionRebuildOperation.id == operation_id,
        )
        if for_update:
            statement = statement.with_for_update()
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_permission_rebuild_for_update(
        self,
        *,
        operation_id: UUID,
    ) -> PermissionRebuildOperation | None:
        result = await self.session.execute(
            select(PermissionRebuildOperation)
            .where(PermissionRebuildOperation.id == operation_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def list_permission_rebuilds(
        self,
        *,
        tenant_id: UUID,
        status: str | None,
        scope: str | None,
        cursor: PageCursor | None,
        limit: int,
    ) -> list[PermissionRebuildOperation]:
        conditions = [PermissionRebuildOperation.tenant_id == tenant_id]
        if status is not None:
            conditions.append(PermissionRebuildOperation.status == status)
        if scope is not None:
            conditions.append(PermissionRebuildOperation.scope == scope)
        if cursor is not None:
            conditions.append(
                or_(
                    PermissionRebuildOperation.created_at < cursor.created_at,
                    and_(
                        PermissionRebuildOperation.created_at == cursor.created_at,
                        PermissionRebuildOperation.id < cursor.item_id,
                    ),
                )
            )
        result = await self.session.execute(
            select(PermissionRebuildOperation)
            .where(*conditions)
            .order_by(
                PermissionRebuildOperation.created_at.desc(),
                PermissionRebuildOperation.id.desc(),
            )
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_runnable_permission_rebuild_ids(
        self,
        *,
        limit: int,
        tenant_id: UUID | None = None,
    ) -> list[UUID]:
        conditions: list[ColumnElement[bool]] = [
            PermissionRebuildOperation.status.in_(["pending", "running"])
        ]
        if tenant_id is not None:
            conditions.append(PermissionRebuildOperation.tenant_id == tenant_id)
        result = await self.session.execute(
            select(PermissionRebuildOperation.id)
            .where(*conditions)
            .order_by(
                PermissionRebuildOperation.created_at,
                PermissionRebuildOperation.id,
            )
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_permission_rebuild_files(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        root_node_id: UUID | None,
        snapshot_at: datetime,
    ) -> int:
        statement = (
            select(func.count())
            .select_from(Node)
            .where(
                Node.tenant_id == tenant_id,
                Node.space_id == space_id,
                Node.node_type == "file",
                Node.is_deleted.is_(False),
                Node.created_at <= snapshot_at,
            )
        )
        if root_node_id is not None:
            subtree = _node_subtree_cte(
                tenant_id=tenant_id,
                space_id=space_id,
                root_node_id=root_node_id,
            )
            statement = statement.join(subtree, subtree.c.id == Node.id)
        result = await self.session.execute(statement)
        return int(result.scalar_one())

    async def list_permission_rebuild_batch(
        self,
        *,
        operation: PermissionRebuildOperation,
        limit: int,
    ) -> list[tuple[UUID, datetime]]:
        conditions = [
            Node.tenant_id == operation.tenant_id,
            Node.space_id == operation.space_id,
            Node.node_type == "file",
            Node.is_deleted.is_(False),
            Node.created_at <= operation.snapshot_at,
        ]
        if operation.cursor_created_at is not None and operation.cursor_node_id is not None:
            conditions.append(
                or_(
                    Node.created_at > operation.cursor_created_at,
                    and_(
                        Node.created_at == operation.cursor_created_at,
                        Node.id > operation.cursor_node_id,
                    ),
                )
            )
        statement = (
            select(Node.id, Node.created_at)
            .where(*conditions)
            .order_by(Node.created_at, Node.id)
            .limit(limit)
        )
        if operation.root_node_id is not None:
            subtree = _node_subtree_cte(
                tenant_id=operation.tenant_id,
                space_id=operation.space_id,
                root_node_id=operation.root_node_id,
            )
            statement = statement.join(subtree, subtree.c.id == Node.id)
        result = await self.session.execute(statement)
        return [(row[0], row[1]) for row in result.all()]

    async def lifecycle_dry_run_counts(
        self,
        *,
        tenant_id: UUID,
        trash_retention_days: int,
        preview_retention_days: int,
    ) -> dict[str, int]:
        now = datetime.now(UTC)
        return {
            "expired_uploads": await self._count(
                UploadSession,
                UploadSession.tenant_id == tenant_id,
                UploadSession.status.in_(["initiated", "uploading", "completing"]),
                UploadSession.expires_at <= now,
            ),
            "expired_trash_roots": await self._count(
                Node,
                Node.tenant_id == tenant_id,
                Node.is_deleted.is_(True),
                Node.deleted_root_id == Node.id,
                Node.deleted_at <= now - timedelta(days=trash_retention_days),
            ),
            "expired_shares": await self._count(
                Share,
                Share.tenant_id == tenant_id,
                Share.status == "active",
                Share.expires_at.is_not(None),
                Share.expires_at <= now,
            ),
            "stale_preview_artifacts": await self._count(
                PreviewArtifact,
                PreviewArtifact.tenant_id == tenant_id,
                PreviewArtifact.last_accessed_at <= now - timedelta(days=preview_retention_days),
            ),
            "unreferenced_blobs": await self._count(
                FileBlob,
                FileBlob.tenant_id == tenant_id,
                FileBlob.ref_count <= 0,
            ),
        }

    async def governance_counts(self, *, tenant_id: UUID) -> dict[str, int]:
        values: dict[str, int] = {}
        for status in ("pending", "running", "completed", "failed"):
            values[f"permission_rebuild_{status}"] = await self._count(
                PermissionRebuildOperation,
                PermissionRebuildOperation.tenant_id == tenant_id,
                PermissionRebuildOperation.status == status,
            )
            values[f"tree_operations_{status}"] = await self._count(
                FileTreeOperation,
                FileTreeOperation.tenant_id == tenant_id,
                FileTreeOperation.status == status,
            )
        values["lifecycle_runs_pending"] = await self._count(
            AdminJob,
            AdminJob.tenant_id == tenant_id,
            AdminJob.kind == "governance",
            AdminJob.operation == "lifecycle.run_policy",
            AdminJob.status.in_(["pending", "running"]),
        )
        values["lifecycle_runs_failed"] = await self._count(
            AdminJob,
            AdminJob.tenant_id == tenant_id,
            AdminJob.kind == "governance",
            AdminJob.operation == "lifecycle.run_policy",
            AdminJob.status == "failed",
        )
        return values

    async def list_tree_operations(
        self,
        *,
        tenant_id: UUID,
        status: str | None,
        cursor: PageCursor | None,
        limit: int,
    ) -> list[FileTreeOperation]:
        conditions = [FileTreeOperation.tenant_id == tenant_id]
        if status is not None:
            conditions.append(FileTreeOperation.status == status)
        if cursor is not None:
            conditions.append(
                or_(
                    FileTreeOperation.created_at < cursor.created_at,
                    and_(
                        FileTreeOperation.created_at == cursor.created_at,
                        FileTreeOperation.id < cursor.item_id,
                    ),
                )
            )
        result = await self.session.execute(
            select(FileTreeOperation)
            .where(*conditions)
            .order_by(
                FileTreeOperation.created_at.desc(),
                FileTreeOperation.id.desc(),
            )
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_lifecycle_runs(
        self,
        *,
        tenant_id: UUID,
        cursor: PageCursor | None,
        limit: int,
    ) -> list[AdminJob]:
        conditions = [
            AdminJob.tenant_id == tenant_id,
            AdminJob.kind == "governance",
            AdminJob.operation == "lifecycle.run_policy",
        ]
        if cursor is not None:
            conditions.append(
                or_(
                    AdminJob.created_at < cursor.created_at,
                    and_(
                        AdminJob.created_at == cursor.created_at,
                        AdminJob.id < cursor.item_id,
                    ),
                )
            )
        result = await self.session.execute(
            select(AdminJob)
            .where(*conditions)
            .order_by(AdminJob.created_at.desc(), AdminJob.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def _count(
        self,
        model: type[object],
        *conditions: ColumnElement[bool],
    ) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(model).where(*conditions)
        )
        return int(result.scalar_one())

    async def flush(self) -> None:
        await self.session.flush()

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()


def _scope_key(*, scope: str, resource_id: UUID) -> str:
    return f"{scope}:{resource_id}"


def _node_subtree_cte(
    *,
    tenant_id: UUID,
    space_id: UUID,
    root_node_id: UUID,
) -> CTE:
    subtree = (
        select(Node.id.label("id"))
        .where(
            Node.tenant_id == tenant_id,
            Node.space_id == space_id,
            Node.id == root_node_id,
        )
        .cte(name="governance_node_subtree", recursive=True)
    )
    child = aliased(Node)
    return subtree.union_all(
        select(child.id).where(
            child.tenant_id == tenant_id,
            child.space_id == space_id,
            child.parent_id == subtree.c.id,
        )
    )
