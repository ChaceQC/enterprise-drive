from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.api.errors import ApiError
from app.core.config import Settings
from app.core.pagination import decode_page_cursor, encode_page_cursor
from app.core.security import utc_now
from app.modules.audit.schemas import AuditContext
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.file.audit import record_folder_created, record_node_event
from app.modules.file.models import FileVersion, Node
from app.modules.file.repository import FileRepository
from app.modules.file.schemas import (
    DeleteNodeResponse,
    FileListResponse,
    FileNodeResponse,
    PurgeNodeResponse,
    TrashListResponse,
    TrashNodeResponse,
)
from app.modules.file.tree import (
    collect_deleted_subtree,
    collect_restore_subtree,
    ensure_mutable_node,
    ensure_not_moving_into_self,
    touch_node,
)
from app.modules.file.validators import node_name_conflict_error, normalize_node_name
from app.modules.permission.actions import (
    ACTION_DELETE,
    ACTION_LIST,
    ACTION_RESTORE,
    ACTION_UPDATE,
    ACTION_UPLOAD,
)
from app.modules.permission.service import FILE_LIST_PERMISSION_ACTIONS, PermissionService
from app.modules.quota.service import QuotaService
from app.modules.search.events import emit_search_index_requested
from app.modules.space.models import Space
from app.modules.space.repository import SpaceRepository


class FileService:
    def __init__(
        self,
        *,
        repository: FileRepository,
        space_repository: SpaceRepository,
        permission_service: PermissionService,
        quota_service: QuotaService,
        settings: Settings,
        audit_service: AuditService | None = None,
    ) -> None:
        self.repository = repository
        self.space_repository = space_repository
        self.permission_service = permission_service
        self.quota_service = quota_service
        self.settings = settings
        self.audit_service = audit_service

    async def create_folder(
        self,
        *,
        current_user: User,
        space_id: UUID,
        parent_id: UUID | None,
        name: str,
        audit_context: AuditContext | None = None,
    ) -> FileNodeResponse:
        space = await self._get_active_space(current_user=current_user, space_id=space_id)
        parent_node = await self._get_parent_node(
            current_user=current_user,
            space=space,
            parent_id=parent_id,
        )
        await self._ensure_node_access(
            current_user=current_user,
            node=parent_node,
            action=ACTION_UPLOAD,
            error_code="SPACE_NOT_FOUND",
        )
        normalized_name = normalize_node_name(name)

        existing_sibling = await self.repository.get_sibling_by_name(
            tenant_id=current_user.tenant_id,
            space_id=space.id,
            parent_id=parent_node.id,
            normalized_name=normalized_name,
        )
        if existing_sibling is not None:
            raise node_name_conflict_error()

        try:
            folder = await self.repository.create_node(
                tenant_id=current_user.tenant_id,
                space_id=space.id,
                parent_id=parent_node.id,
                owner_id=current_user.id,
                node_type="folder",
                name=normalized_name,
                normalized_name=normalized_name,
            )
            await record_folder_created(
                audit_service=self.audit_service,
                current_user=current_user,
                folder=folder,
                audit_context=audit_context,
            )
            await self.repository.commit()
        except IntegrityError as exc:
            await self.repository.rollback()
            raise node_name_conflict_error() from exc

        return FileNodeResponse.model_validate(folder)

    async def list_children(
        self,
        *,
        current_user: User,
        space_id: UUID,
        parent_id: UUID | None,
        cursor: str | None,
        page_size: int,
    ) -> FileListResponse:
        space = await self._get_active_space(current_user=current_user, space_id=space_id)
        parent_node = await self._get_parent_node(
            current_user=current_user,
            space=space,
            parent_id=parent_id,
        )
        parent_path_ids = await self._ensure_node_access(
            current_user=current_user,
            node=parent_node,
            action=ACTION_LIST,
            error_code="SPACE_NOT_FOUND",
        )
        decoded_cursor = decode_page_cursor(self.settings, cursor)
        nodes = await self.repository.list_children(
            tenant_id=current_user.tenant_id,
            space_id=space.id,
            parent_id=parent_node.id,
            limit=page_size + 1,
            cursor=decoded_cursor,
        )
        items = nodes[:page_size]
        next_cursor = None
        if len(nodes) > page_size and items:
            last_item = items[-1]
            next_cursor = encode_page_cursor(
                self.settings,
                created_at=last_item.created_at,
                item_id=last_item.id,
            )
        permissions = await self.permission_service.batch_check_nodes(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            space_id=space.id,
            node_paths={node.id: [*parent_path_ids, node.id] for node in items},
            actions=FILE_LIST_PERMISSION_ACTIONS,
        )
        return FileListResponse(
            space_id=space.id,
            parent_id=parent_node.id,
            items=[
                FileNodeResponse.model_validate(node).model_copy(
                    update={"permissions": permissions.get(node.id, {})}
                )
                for node in items
            ],
            next_cursor=next_cursor,
        )

    async def list_trash(
        self,
        *,
        current_user: User,
        space_id: UUID,
        cursor: str | None,
        page_size: int,
    ) -> TrashListResponse:
        space = await self._get_active_space(current_user=current_user, space_id=space_id)
        decoded_cursor = decode_page_cursor(self.settings, cursor)
        nodes = await self.repository.list_trash_roots(
            tenant_id=current_user.tenant_id,
            space_id=space.id,
            limit=page_size + 1,
            cursor=decoded_cursor,
        )
        paths = {
            node.id: path
            for node in nodes
            if (
                path := await self.repository.get_node_path_ids(
                    tenant_id=current_user.tenant_id,
                    space_id=space.id,
                    node_id=node.id,
                    include_deleted=True,
                )
            )
            is not None
        }
        permissions = await self.permission_service.batch_check_nodes(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            space_id=space.id,
            node_paths=paths,
            actions=[ACTION_DELETE, ACTION_RESTORE],
        )
        visible_nodes = [
            node
            for node in nodes
            if permissions.get(node.id, {}).get(ACTION_DELETE, False)
            or permissions.get(node.id, {}).get(ACTION_RESTORE, False)
        ]
        items = visible_nodes[:page_size]
        next_cursor = None
        if len(visible_nodes) > page_size and items:
            last_item = items[-1]
            if last_item.deleted_at is not None:
                next_cursor = encode_page_cursor(
                    self.settings,
                    created_at=last_item.deleted_at,
                    item_id=last_item.id,
                )

        return TrashListResponse(
            space_id=space.id,
            items=[
                TrashNodeResponse.model_validate(node).model_copy(
                    update={"permissions": permissions.get(node.id, {})}
                )
                for node in items
            ],
            next_cursor=next_cursor,
        )

    async def rename_node(
        self,
        *,
        current_user: User,
        node_id: UUID,
        name: str,
        audit_context: AuditContext | None = None,
    ) -> FileNodeResponse:
        node = await self._get_accessible_node(
            current_user=current_user,
            node_id=node_id,
            action=ACTION_UPDATE,
        )
        ensure_mutable_node(node)
        normalized_name = normalize_node_name(name)
        await self._ensure_name_available(
            tenant_id=current_user.tenant_id,
            space_id=node.space_id,
            parent_id=node.parent_id,
            normalized_name=normalized_name,
            exclude_node_id=node.id,
        )
        affected_nodes = await self._collect_active_subtree(node=node)

        old_name = node.name
        try:
            node.name = normalized_name
            node.normalized_name = normalized_name
            touch_node(node)
            await self.repository.flush()
            await record_node_event(
                audit_service=self.audit_service,
                current_user=current_user,
                node=node,
                action="file.renamed",
                audit_context=audit_context,
                metadata={"old_name": old_name, "new_name": normalized_name},
            )
            await self._emit_search_index_requests(
                nodes=affected_nodes,
                reason="file_renamed",
                metadata={"root_node_id": str(node.id)},
            )
            await self.repository.commit()
        except IntegrityError as exc:
            await self.repository.rollback()
            raise node_name_conflict_error() from exc

        return FileNodeResponse.model_validate(node)

    async def move_node(
        self,
        *,
        current_user: User,
        node_id: UUID,
        target_parent_id: UUID,
        new_name: str | None,
        audit_context: AuditContext | None = None,
    ) -> FileNodeResponse:
        try:
            response = await self.move_node_in_transaction(
                current_user=current_user,
                node_id=node_id,
                target_parent_id=target_parent_id,
                new_name=new_name,
                audit_context=audit_context,
            )
            await self.repository.commit()
        except IntegrityError as exc:
            await self.repository.rollback()
            raise node_name_conflict_error() from exc
        except Exception:
            await self.repository.rollback()
            raise
        return response

    async def delete_node(
        self,
        *,
        current_user: User,
        node_id: UUID,
        audit_context: AuditContext | None = None,
    ) -> DeleteNodeResponse:
        try:
            response = await self.delete_node_in_transaction(
                current_user=current_user,
                node_id=node_id,
                audit_context=audit_context,
            )
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return response

    async def purge_node(
        self,
        *,
        current_user: User,
        node_id: UUID,
        audit_context: AuditContext | None = None,
    ) -> PurgeNodeResponse:
        try:
            response = await self.purge_node_in_transaction(
                current_user=current_user,
                node_id=node_id,
                audit_context=audit_context,
            )
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return response

    async def restore_node(
        self,
        *,
        current_user: User,
        node_id: UUID,
        target_parent_id: UUID | None,
        new_name: str | None,
        audit_context: AuditContext | None = None,
    ) -> FileNodeResponse:
        try:
            response = await self.restore_node_in_transaction(
                current_user=current_user,
                node_id=node_id,
                target_parent_id=target_parent_id,
                new_name=new_name,
                audit_context=audit_context,
            )
            await self.repository.commit()
        except IntegrityError as exc:
            await self.repository.rollback()
            raise node_name_conflict_error() from exc
        except Exception:
            await self.repository.rollback()
            raise
        return response

    async def move_node_in_transaction(
        self,
        *,
        current_user: User,
        node_id: UUID,
        target_parent_id: UUID,
        new_name: str | None,
        audit_context: AuditContext | None,
    ) -> FileNodeResponse:
        node = await self._get_accessible_node(
            current_user=current_user,
            node_id=node_id,
            action=ACTION_UPDATE,
        )
        ensure_mutable_node(node)
        target_parent = await self._get_active_folder(
            current_user=current_user,
            space_id=node.space_id,
            node_id=target_parent_id,
        )
        await ensure_not_moving_into_self(
            repository=self.repository,
            node=node,
            target_parent=target_parent,
        )
        normalized_name = (
            normalize_node_name(new_name) if new_name is not None else node.normalized_name
        )
        await self._ensure_name_available(
            tenant_id=current_user.tenant_id,
            space_id=node.space_id,
            parent_id=target_parent.id,
            normalized_name=normalized_name,
            exclude_node_id=node.id,
        )
        affected_nodes = await self._collect_active_subtree(node=node)
        old_parent_id = node.parent_id
        old_name = node.name
        node.parent_id = target_parent.id
        node.name = normalized_name
        node.normalized_name = normalized_name
        touch_node(node)
        await self.repository.flush()
        await record_node_event(
            audit_service=self.audit_service,
            current_user=current_user,
            node=node,
            action="file.moved",
            audit_context=audit_context,
            metadata={
                "old_parent_id": str(old_parent_id) if old_parent_id else None,
                "new_parent_id": str(target_parent.id),
                "old_name": old_name,
                "new_name": normalized_name,
            },
        )
        await self._emit_search_index_requests(
            nodes=affected_nodes,
            reason="file_moved",
            metadata={
                "root_node_id": str(node.id),
                "old_parent_id": str(old_parent_id) if old_parent_id else None,
                "new_parent_id": str(target_parent.id),
            },
        )
        return FileNodeResponse.model_validate(node)

    async def delete_node_in_transaction(
        self,
        *,
        current_user: User,
        node_id: UUID,
        audit_context: AuditContext | None,
    ) -> DeleteNodeResponse:
        node = await self._get_accessible_node(
            current_user=current_user,
            node_id=node_id,
            action=ACTION_DELETE,
        )
        ensure_mutable_node(node)
        subtree_nodes = await self._collect_active_subtree(node=node)
        now = utc_now()
        for subtree_node in subtree_nodes:
            subtree_node.is_deleted = True
            subtree_node.deleted_at = now
            subtree_node.deleted_by = current_user.id
            touch_node(subtree_node)
        await self.repository.flush()
        await record_node_event(
            audit_service=self.audit_service,
            current_user=current_user,
            node=node,
            action="file.deleted",
            audit_context=audit_context,
            metadata={"deleted_count": len(subtree_nodes)},
        )
        await self._emit_search_index_requests(
            nodes=subtree_nodes,
            reason="file_deleted",
            metadata={"root_node_id": str(node.id)},
        )
        return DeleteNodeResponse(node_id=node.id, deleted_count=len(subtree_nodes))

    async def purge_node_in_transaction(
        self,
        *,
        current_user: User,
        node_id: UUID,
        audit_context: AuditContext | None,
    ) -> PurgeNodeResponse:
        node = await self._get_accessible_node(
            current_user=current_user,
            node_id=node_id,
            action=ACTION_DELETE,
            include_deleted=True,
        )
        ensure_mutable_node(node)
        if not node.is_deleted:
            raise ApiError("NODE_NOT_DELETED", "节点不在回收站中", status_code=400)

        subtree_nodes = await collect_deleted_subtree(repository=self.repository, node=node)
        node_ids = [subtree_node.id for subtree_node in subtree_nodes]
        versions = await self.repository.list_versions_for_nodes(
            tenant_id=current_user.tenant_id,
            node_ids=node_ids,
        )
        released_bytes = sum(version.size_bytes for version in versions)
        blob_counts = self._blob_ref_counts(versions=versions)

        await self.quota_service.release_file_usage(
            tenant_id=current_user.tenant_id,
            space_id=node.space_id,
            ref_id=node.id,
            size_bytes=released_bytes,
            version_ids=[version.id for version in versions],
        )
        blob_refs_updated = await self.repository.decrement_blob_ref_counts(
            tenant_id=current_user.tenant_id,
            blob_counts=blob_counts,
        )
        if not blob_refs_updated:
            raise ApiError("BLOB_REFCOUNT_INVALID", "文件引用计数异常", status_code=500)
        await record_node_event(
            audit_service=self.audit_service,
            current_user=current_user,
            node=node,
            action="file.purged",
            audit_context=audit_context,
            metadata={
                "purged_count": len(subtree_nodes),
                "released_bytes": released_bytes,
            },
        )
        await self._emit_search_index_requests(
            nodes=subtree_nodes,
            reason="file_purged",
            metadata={"root_node_id": str(node.id)},
        )
        await self.repository.delete_versions_for_nodes(
            tenant_id=current_user.tenant_id,
            node_ids=node_ids,
        )
        for subtree_node in reversed(subtree_nodes):
            await self.repository.delete_node(
                tenant_id=current_user.tenant_id,
                node_id=subtree_node.id,
            )
        return PurgeNodeResponse(
            node_id=node.id,
            purged_count=len(subtree_nodes),
            released_bytes=released_bytes,
        )

    async def restore_node_in_transaction(
        self,
        *,
        current_user: User,
        node_id: UUID,
        target_parent_id: UUID | None,
        new_name: str | None,
        audit_context: AuditContext | None = None,
    ) -> FileNodeResponse:
        node = await self._get_accessible_node(
            current_user=current_user,
            node_id=node_id,
            action=ACTION_RESTORE,
            include_deleted=True,
        )
        ensure_mutable_node(node)
        if not node.is_deleted:
            raise ApiError("NODE_NOT_DELETED", "节点不在回收站中", status_code=400)

        restore_parent = await self._resolve_restore_parent(
            current_user=current_user,
            node=node,
            target_parent_id=target_parent_id,
        )
        normalized_name = (
            normalize_node_name(new_name) if new_name is not None else node.normalized_name
        )
        await self._ensure_name_available(
            tenant_id=current_user.tenant_id,
            space_id=node.space_id,
            parent_id=restore_parent.id,
            normalized_name=normalized_name,
            exclude_node_id=node.id,
        )

        subtree_nodes = await collect_restore_subtree(repository=self.repository, node=node)
        node.parent_id = restore_parent.id
        node.name = normalized_name
        node.normalized_name = normalized_name
        for subtree_node in subtree_nodes:
            subtree_node.is_deleted = False
            subtree_node.deleted_at = None
            subtree_node.deleted_by = None
            touch_node(subtree_node)
        await self.repository.flush()
        await record_node_event(
            audit_service=self.audit_service,
            current_user=current_user,
            node=node,
            action="file.restored",
            audit_context=audit_context,
            metadata={
                "restore_parent_id": str(restore_parent.id),
                "restored_count": len(subtree_nodes),
            },
        )
        await self._emit_search_index_requests(
            nodes=subtree_nodes,
            reason="file_restored",
            metadata={"root_node_id": str(node.id)},
        )
        return FileNodeResponse.model_validate(node)

    async def _get_active_space(
        self,
        *,
        current_user: User,
        space_id: UUID,
    ) -> Space:
        space = await self.space_repository.get_active_space(
            tenant_id=current_user.tenant_id,
            space_id=space_id,
        )
        if space is None:
            raise ApiError("SPACE_NOT_FOUND", "空间不存在或无权访问", status_code=404)
        return space

    async def _get_parent_node(
        self,
        *,
        current_user: User,
        space: Space,
        parent_id: UUID | None,
    ) -> Node:
        if parent_id is None:
            node = await self.repository.get_root_node(
                tenant_id=current_user.tenant_id,
                space_id=space.id,
            )
        else:
            node = await self.repository.get_node(
                tenant_id=current_user.tenant_id,
                space_id=space.id,
                node_id=parent_id,
            )

        if node is None:
            raise ApiError("PARENT_NOT_FOUND", "父目录不存在或无权访问", status_code=404)
        if node.node_type != "folder":
            raise ApiError("PARENT_NOT_FOLDER", "父节点不是文件夹", status_code=400)
        return node

    async def _get_accessible_node(
        self,
        *,
        current_user: User,
        node_id: UUID,
        action: str,
        include_deleted: bool = False,
    ) -> Node:
        node = await self.repository.get_node_by_id(
            tenant_id=current_user.tenant_id,
            node_id=node_id,
            include_deleted=include_deleted,
        )
        if node is None:
            raise ApiError("NODE_NOT_FOUND", "节点不存在或无权访问", status_code=404)
        await self._get_active_space(
            current_user=current_user,
            space_id=node.space_id,
        )
        await self._ensure_node_access(
            current_user=current_user,
            node=node,
            action=action,
            error_code="NODE_NOT_FOUND",
            include_deleted=include_deleted,
        )
        return node

    async def _get_active_folder(
        self,
        *,
        current_user: User,
        space_id: UUID,
        node_id: UUID,
    ) -> Node:
        space = await self._get_active_space(
            current_user=current_user,
            space_id=space_id,
        )
        folder = await self._get_parent_node(
            current_user=current_user,
            space=space,
            parent_id=node_id,
        )
        await self._ensure_node_access(
            current_user=current_user,
            node=folder,
            action=ACTION_UPDATE,
            error_code="PARENT_NOT_FOUND",
        )
        return folder

    async def _resolve_restore_parent(
        self,
        *,
        current_user: User,
        node: Node,
        target_parent_id: UUID | None,
    ) -> Node:
        parent_id = target_parent_id or node.parent_id
        if parent_id is None:
            raise ApiError("PARENT_NOT_FOUND", "父目录不存在或无权访问", status_code=404)
        return await self._get_active_folder(
            current_user=current_user,
            space_id=node.space_id,
            node_id=parent_id,
        )

    async def _ensure_node_access(
        self,
        *,
        current_user: User,
        node: Node,
        action: str,
        error_code: str,
        include_deleted: bool = False,
    ) -> list[UUID]:
        node_path_ids = await self.repository.get_node_path_ids(
            tenant_id=current_user.tenant_id,
            space_id=node.space_id,
            node_id=node.id,
            include_deleted=include_deleted,
        )
        allowed = node_path_ids is not None and await self.permission_service.can_access_node(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            space_id=node.space_id,
            action=action,
            node_path_ids=node_path_ids,
        )
        if not allowed:
            if error_code == "PARENT_NOT_FOUND":
                raise ApiError(error_code, "父目录不存在或无权访问", status_code=404)
            if error_code == "NODE_NOT_FOUND":
                raise ApiError(error_code, "节点不存在或无权访问", status_code=404)
            raise ApiError(error_code, "空间不存在或无权访问", status_code=404)
        assert node_path_ids is not None
        return node_path_ids

    async def _ensure_name_available(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        parent_id: UUID | None,
        normalized_name: str,
        exclude_node_id: UUID | None,
    ) -> None:
        existing_sibling = await self.repository.get_sibling_by_name(
            tenant_id=tenant_id,
            space_id=space_id,
            parent_id=parent_id,
            normalized_name=normalized_name,
            exclude_node_id=exclude_node_id,
        )
        if existing_sibling is not None:
            raise node_name_conflict_error()

    async def _collect_active_subtree(self, *, node: Node) -> list[Node]:
        collected = [node]
        cursor = 0
        while cursor < len(collected):
            current = collected[cursor]
            cursor += 1
            if current.node_type != "folder":
                continue
            children = await self.repository.list_child_nodes(
                tenant_id=current.tenant_id,
                space_id=current.space_id,
                parent_id=current.id,
                include_deleted=True,
            )
            collected.extend(child for child in children if not child.is_deleted)
        return collected

    async def _emit_search_index_requests(
        self,
        *,
        nodes: list[Node],
        reason: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        for node in nodes:
            if node.node_type != "file":
                continue
            await emit_search_index_requested(
                audit_service=self.audit_service,
                tenant_id=node.tenant_id,
                node_id=node.id,
                space_id=node.space_id,
                reason=reason,
                metadata=metadata,
            )

    def _blob_ref_counts(self, *, versions: list[FileVersion]) -> dict[UUID, int]:
        counts: dict[UUID, int] = {}
        for version in versions:
            counts[version.blob_id] = counts.get(version.blob_id, 0) + 1
        return counts
