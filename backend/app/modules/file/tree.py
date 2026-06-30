from __future__ import annotations

from app.api.errors import ApiError
from app.core.security import utc_now
from app.modules.file.models import Node
from app.modules.file.repository import FileRepository


def ensure_mutable_node(node: Node) -> None:
    if node.parent_id is None:
        raise ApiError("NODE_ROOT_IMMUTABLE", "根目录不允许执行该操作", status_code=400)


def touch_node(node: Node) -> None:
    node.updated_at = utc_now()
    node.permission_version += 1


async def ensure_not_moving_into_self(
    *,
    repository: FileRepository,
    node: Node,
    target_parent: Node,
) -> None:
    current: Node | None = target_parent
    while current is not None:
        if current.id == node.id:
            raise ApiError("NODE_MOVE_INVALID", "不能移动到自身或子目录", status_code=400)
        if current.parent_id is None:
            return
        current = await repository.get_node(
            tenant_id=node.tenant_id,
            space_id=node.space_id,
            node_id=current.parent_id,
        )


async def collect_subtree(
    *,
    repository: FileRepository,
    node: Node,
    include_deleted: bool,
) -> list[Node]:
    collected = [node]
    cursor = 0
    while cursor < len(collected):
        current = collected[cursor]
        cursor += 1
        if current.node_type != "folder":
            continue
        children = await repository.list_child_nodes(
            tenant_id=current.tenant_id,
            space_id=current.space_id,
            parent_id=current.id,
            include_deleted=include_deleted,
        )
        collected.extend(children)
    return collected


async def collect_restore_subtree(
    *,
    repository: FileRepository,
    node: Node,
) -> list[Node]:
    collected = [node]
    cursor = 0
    while cursor < len(collected):
        current = collected[cursor]
        cursor += 1
        if current.node_type != "folder":
            continue
        children = await repository.list_child_nodes(
            tenant_id=current.tenant_id,
            space_id=current.space_id,
            parent_id=current.id,
            include_deleted=True,
        )
        collected.extend(
            child
            for child in children
            if child.is_deleted
            and child.deleted_at == node.deleted_at
            and child.deleted_by == node.deleted_by
        )
    return collected
