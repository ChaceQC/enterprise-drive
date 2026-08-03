from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from app.api.errors import ApiError
from app.core.config import Settings
from app.core.security import utc_now
from app.modules.auth.models import User
from app.modules.file.models import Node
from app.modules.file.repository import FileRepository
from app.modules.permission.actions import ACTION_LIST, ACTION_READ_META
from app.modules.permission.service import PermissionService
from app.modules.space.repository import SpaceRepository
from app.modules.sync.cursor import SyncCursor, decode_sync_cursor, encode_sync_cursor
from app.modules.sync.models import SyncChange
from app.modules.sync.repository import SyncRepository
from app.modules.sync.schemas import SyncChangeListResponse, SyncChangeResponse


class SyncService:
    def __init__(
        self,
        *,
        repository: SyncRepository,
        file_repository: FileRepository,
        space_repository: SpaceRepository,
        permission_service: PermissionService,
        settings: Settings,
    ) -> None:
        self.repository = repository
        self.file_repository = file_repository
        self.space_repository = space_repository
        self.permission_service = permission_service
        self.settings = settings

    async def list_changes(
        self,
        *,
        current_user: User,
        space_id: UUID,
        root_node_id: UUID,
        raw_cursor: str | None,
        page_size: int,
    ) -> SyncChangeListResponse:
        root = await self._get_accessible_root(
            current_user=current_user,
            space_id=space_id,
            root_node_id=root_node_id,
        )
        now = utc_now()
        if raw_cursor is None:
            sequence = await self.repository.max_sequence(
                tenant_id=current_user.tenant_id,
                space_id=space_id,
            )
            cursor = SyncCursor(
                tenant_id=current_user.tenant_id,
                user_id=current_user.id,
                space_id=space_id,
                root_node_id=root_node_id,
                sequence=sequence,
                issued_at=now,
            )
            return self._response(
                cursor=cursor,
                root=root,
                items=[],
                has_more=False,
            )

        cursor = decode_sync_cursor(self.settings, raw_cursor)
        self._validate_cursor_scope(
            cursor=cursor,
            current_user=current_user,
            space_id=space_id,
            root_node_id=root_node_id,
            now=now,
        )
        current_max = await self.repository.max_sequence(
            tenant_id=current_user.tenant_id,
            space_id=space_id,
        )
        if cursor.sequence > current_max:
            raise ApiError("SYNC_CURSOR_INVALID", "增量同步游标超出当前变更范围", status_code=400)

        scan_sequence = cursor.sequence
        items: list[SyncChangeResponse] = []
        batch_size = max(100, min(500, page_size * 5))
        while len(items) < page_size:
            changes = await self.repository.list_changes_after(
                tenant_id=current_user.tenant_id,
                space_id=space_id,
                sequence=scan_sequence,
                limit=batch_size,
            )
            if not changes:
                break
            for change in changes:
                scan_sequence = change.sequence
                if not self._applies_to_root(change=change, root_node_id=root_node_id):
                    continue
                rendered = await self._render_change(
                    current_user=current_user,
                    root=root,
                    change=change,
                )
                if rendered is not None:
                    items.append(rendered)
                if len(items) >= page_size:
                    break
            if len(changes) < batch_size or len(items) >= page_size:
                break

        next_cursor = SyncCursor(
            tenant_id=cursor.tenant_id,
            user_id=cursor.user_id,
            space_id=cursor.space_id,
            root_node_id=cursor.root_node_id,
            sequence=scan_sequence,
            issued_at=cursor.issued_at,
        )
        has_more = await self.repository.has_changes_after(
            tenant_id=current_user.tenant_id,
            space_id=space_id,
            sequence=scan_sequence,
        )
        return self._response(
            cursor=next_cursor,
            root=root,
            items=items,
            has_more=has_more,
        )

    async def _get_accessible_root(
        self,
        *,
        current_user: User,
        space_id: UUID,
        root_node_id: UUID,
    ) -> Node:
        space = await self.space_repository.get_active_space(
            tenant_id=current_user.tenant_id,
            space_id=space_id,
        )
        root = await self.file_repository.get_node(
            tenant_id=current_user.tenant_id,
            space_id=space_id,
            node_id=root_node_id,
        )
        if space is None or root is None or root.node_type != "folder":
            raise ApiError("SYNC_ROOT_NOT_FOUND", "同步根目录不存在或无权访问", status_code=404)
        path = await self.file_repository.get_node_path_ids(
            tenant_id=current_user.tenant_id,
            space_id=space_id,
            node_id=root.id,
        )
        allowed = path is not None and await self.permission_service.can_access_node(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            space_id=space_id,
            action=ACTION_LIST,
            node_path_ids=path,
        )
        if not allowed:
            raise ApiError(
                "SYNC_PERMISSION_REVOKED",
                "同步目录权限已撤销",
                status_code=403,
                details={"requires_full_resync": True},
            )
        return root

    def _validate_cursor_scope(
        self,
        *,
        cursor: SyncCursor,
        current_user: User,
        space_id: UUID,
        root_node_id: UUID,
        now: datetime,
    ) -> None:
        if (
            cursor.tenant_id != current_user.tenant_id
            or cursor.user_id != current_user.id
            or cursor.space_id != space_id
            or cursor.root_node_id != root_node_id
        ):
            raise ApiError(
                "SYNC_CURSOR_SCOPE_MISMATCH",
                "增量同步游标与当前用户或同步目录不匹配",
                status_code=400,
            )
        expires_at = cursor.issued_at + timedelta(days=self.settings.sync_cursor_ttl_days)
        if now >= expires_at:
            raise ApiError(
                "SYNC_CURSOR_EXPIRED",
                "增量同步游标已过期，需要重新建立索引",
                status_code=410,
                details={"requires_full_resync": True},
            )

    @staticmethod
    def _applies_to_root(*, change: SyncChange, root_node_id: UUID) -> bool:
        if change.space_id is None or change.node_id is None:
            return True
        return str(root_node_id) in change.scope_node_ids

    async def _render_change(
        self,
        *,
        current_user: User,
        root: Node,
        change: SyncChange,
    ) -> SyncChangeResponse | None:
        if change.node_id is None:
            return self._root_permission_change(root=root, change=change)
        if change.tombstone:
            return self._tombstone(change=change, space_id=root.space_id)

        node = await self.file_repository.get_node_by_id(
            tenant_id=current_user.tenant_id,
            node_id=change.node_id,
            include_deleted=True,
        )
        if node is None or node.is_deleted:
            return self._tombstone(change=change, space_id=root.space_id)
        path = await self.file_repository.get_node_path_ids(
            tenant_id=current_user.tenant_id,
            space_id=node.space_id,
            node_id=node.id,
            include_deleted=True,
        )
        if path is None:
            return None
        if root.id not in path:
            return self._tombstone(
                change=change,
                space_id=root.space_id,
                change_type="moved_out",
            )
        allowed = await self.permission_service.can_access_node(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            space_id=node.space_id,
            action=ACTION_READ_META,
            node_path_ids=path,
        )
        if not allowed:
            return self._tombstone(
                change=change,
                space_id=root.space_id,
                change_type="permission_revoked",
            )
        return SyncChangeResponse(
            sequence=change.sequence,
            change_type=change.change_type,
            node_id=node.id,
            space_id=node.space_id,
            parent_id=node.parent_id,
            node_type=node.node_type,
            name=node.name,
            current_version_id=node.current_version_id,
            permission_version=node.permission_version,
            tombstone=False,
            client_operation_id=change.client_operation_id,
            changed_at=change.created_at,
        )

    @staticmethod
    def _root_permission_change(
        *,
        root: Node,
        change: SyncChange,
    ) -> SyncChangeResponse:
        return SyncChangeResponse(
            sequence=change.sequence,
            change_type=change.change_type,
            node_id=root.id,
            space_id=root.space_id,
            parent_id=root.parent_id,
            node_type=root.node_type,
            name=root.name,
            current_version_id=root.current_version_id,
            permission_version=change.permission_version,
            tombstone=False,
            client_operation_id=change.client_operation_id,
            changed_at=change.created_at,
        )

    @staticmethod
    def _tombstone(
        *,
        change: SyncChange,
        space_id: UUID,
        change_type: str | None = None,
    ) -> SyncChangeResponse:
        assert change.node_id is not None
        return SyncChangeResponse(
            sequence=change.sequence,
            change_type=change_type or change.change_type,
            node_id=change.node_id,
            space_id=space_id,
            parent_id=change.parent_id,
            node_type=change.node_type,
            name=None,
            current_version_id=change.current_version_id,
            permission_version=change.permission_version,
            tombstone=True,
            client_operation_id=change.client_operation_id,
            changed_at=change.created_at,
        )

    def _response(
        self,
        *,
        cursor: SyncCursor,
        root: Node,
        items: list[SyncChangeResponse],
        has_more: bool,
    ) -> SyncChangeListResponse:
        return SyncChangeListResponse(
            space_id=root.space_id,
            root_node_id=root.id,
            items=items,
            next_cursor=encode_sync_cursor(self.settings, cursor),
            has_more=has_more,
            cursor_expires_at=cursor.issued_at + timedelta(days=self.settings.sync_cursor_ttl_days),
        )
