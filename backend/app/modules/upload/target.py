from __future__ import annotations

from uuid import UUID

from app.api.errors import ApiError
from app.modules.auth.models import User
from app.modules.file.models import Node
from app.modules.file.repository import FileRepository
from app.modules.permission.actions import ACTION_UPDATE
from app.modules.permission.service import PermissionService


async def require_upload_version_target(
    *,
    file_repository: FileRepository,
    permission_service: PermissionService,
    current_user: User,
    target_node_id: UUID,
    space_id: UUID,
    parent_id: UUID,
    normalized_name: str,
    expected_current_version_id: UUID,
    for_update: bool,
) -> Node:
    if for_update:
        node = await file_repository.get_node_by_id_for_update(
            tenant_id=current_user.tenant_id,
            node_id=target_node_id,
        )
    else:
        node = await file_repository.get_node_by_id(
            tenant_id=current_user.tenant_id,
            node_id=target_node_id,
        )
    if (
        node is None
        or node.node_type != "file"
        or node.space_id != space_id
        or node.parent_id != parent_id
        or node.normalized_name != normalized_name
    ):
        raise ApiError("NODE_NOT_FOUND", "文件不存在或无权访问", status_code=404)

    path = await file_repository.get_node_path_ids(
        tenant_id=current_user.tenant_id,
        space_id=node.space_id,
        node_id=node.id,
    )
    allowed = path is not None and await permission_service.can_access_node(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        space_id=node.space_id,
        action=ACTION_UPDATE,
        node_path_ids=path,
    )
    if not allowed:
        raise ApiError("NODE_NOT_FOUND", "文件不存在或无权访问", status_code=404)
    if node.current_version_id != expected_current_version_id:
        raise ApiError(
            "FILE_VERSION_CONFLICT",
            "文件版本已变化，请刷新后重试",
            status_code=409,
            details={
                "expected_current_version_id": str(expected_current_version_id),
                "actual_current_version_id": (
                    str(node.current_version_id) if node.current_version_id else None
                ),
            },
        )
    return node
