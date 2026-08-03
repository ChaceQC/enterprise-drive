from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID, uuid4

from sqlalchemy import event, inspect, select
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session
from sqlalchemy.orm.state import InstanceState

from app.modules.auth.models import Tenant
from app.modules.file.models import Node
from app.modules.space.models import Space
from app.modules.sync.models import SyncChange

_REGISTERED = False


def register_sync_change_listeners() -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    event.listen(Session, "before_flush", _capture_sync_changes)
    _REGISTERED = True


def _capture_sync_changes(
    session: Session,
    flush_context: object,
    instances: object,
) -> None:
    del flush_context, instances
    if session.info.get("disable_sync_change_capture") is True:
        return

    connection = session.connection()
    actor_id = _uuid_or_none(session.info.get("actor_id"))
    client_operation_id = _string_or_none(session.info.get("client_operation_id"))

    for node in list(session.new):
        if not isinstance(node, Node):
            continue
        if node.id is None:
            node.id = uuid4()
        session.add(
            _node_change(
                connection=connection,
                node=node,
                change_type="created",
                tombstone=False,
                old_parent_id=None,
                new_parent_id=node.parent_id,
                actor_id=actor_id,
                client_operation_id=client_operation_id,
            )
        )

    for node in list(session.dirty):
        if not isinstance(node, Node):
            continue
        state = inspect(node)
        change_type = _dirty_node_change_type(state)
        if change_type is None:
            continue
        parent_history = state.attrs.parent_id.history
        old_parent_id = (
            _uuid_or_none(parent_history.deleted[0]) if parent_history.deleted else node.parent_id
        )
        new_parent_id = (
            _uuid_or_none(parent_history.added[0]) if parent_history.added else node.parent_id
        )
        session.add(
            _node_change(
                connection=connection,
                node=node,
                change_type=change_type,
                tombstone=change_type == "deleted",
                old_parent_id=old_parent_id,
                new_parent_id=new_parent_id,
                actor_id=actor_id,
                client_operation_id=client_operation_id,
            )
        )

    for node in list(session.deleted):
        if not isinstance(node, Node):
            continue
        session.add(
            _node_change(
                connection=connection,
                node=node,
                change_type="purged",
                tombstone=True,
                old_parent_id=node.parent_id,
                new_parent_id=None,
                actor_id=actor_id,
                client_operation_id=client_operation_id,
            )
        )

    for space in list(session.dirty):
        if not isinstance(space, Space):
            continue
        if not inspect(space).attrs.permission_version.history.has_changes():
            continue
        session.add(
            SyncChange(
                tenant_id=space.tenant_id,
                space_id=space.id,
                node_id=None,
                parent_id=None,
                change_type="permission_changed",
                permission_version=space.permission_version,
                tombstone=False,
                scope_node_ids=[],
                actor_id=actor_id,
                client_operation_id=client_operation_id,
            )
        )

    for tenant in list(session.dirty):
        if not isinstance(tenant, Tenant):
            continue
        if not inspect(tenant).attrs.permission_version.history.has_changes():
            continue
        session.add(
            SyncChange(
                tenant_id=tenant.id,
                space_id=None,
                node_id=None,
                parent_id=None,
                change_type="tenant_permission_changed",
                permission_version=tenant.permission_version,
                tombstone=False,
                scope_node_ids=[],
                actor_id=actor_id,
                client_operation_id=client_operation_id,
            )
        )


def _node_change(
    *,
    connection: Connection,
    node: Node,
    change_type: str,
    tombstone: bool,
    old_parent_id: UUID | None,
    new_parent_id: UUID | None,
    actor_id: UUID | None,
    client_operation_id: str | None,
) -> SyncChange:
    old_scope = _path_from_parent(
        connection=connection,
        tenant_id=node.tenant_id,
        space_id=node.space_id,
        parent_id=old_parent_id,
    )
    new_scope = _path_from_parent(
        connection=connection,
        tenant_id=node.tenant_id,
        space_id=node.space_id,
        parent_id=new_parent_id,
    )
    scope_ids = _stable_uuid_strings([*old_scope, *new_scope, node.id])
    return SyncChange(
        tenant_id=node.tenant_id,
        space_id=node.space_id,
        node_id=node.id,
        parent_id=node.parent_id,
        change_type=change_type,
        node_type=node.node_type,
        name=None if tombstone else node.name,
        current_version_id=node.current_version_id,
        permission_version=node.permission_version,
        tombstone=tombstone,
        scope_node_ids=scope_ids,
        actor_id=actor_id,
        client_operation_id=client_operation_id,
    )


def _path_from_parent(
    *,
    connection: Connection,
    tenant_id: UUID,
    space_id: UUID,
    parent_id: UUID | None,
) -> list[UUID]:
    path: list[UUID] = []
    seen: set[UUID] = set()
    current_id = parent_id
    while current_id is not None and len(path) < 64 and current_id not in seen:
        seen.add(current_id)
        row = connection.execute(
            select(Node.id, Node.parent_id).where(
                Node.tenant_id == tenant_id,
                Node.space_id == space_id,
                Node.id == current_id,
            )
        ).one_or_none()
        if row is None:
            path.append(current_id)
            break
        path.append(row.id)
        current_id = row.parent_id
    path.reverse()
    return path


def _dirty_node_change_type(state: InstanceState[Node]) -> str | None:
    attrs = state.attrs
    deleted_history = attrs.is_deleted.history
    if deleted_history.has_changes():
        return "deleted" if bool(attrs.is_deleted.value) else "restored"
    if attrs.parent_id.history.has_changes():
        return "moved"
    if attrs.name.history.has_changes() or attrs.normalized_name.history.has_changes():
        return "renamed"
    if attrs.current_version_id.history.has_changes():
        return "version_changed"
    if attrs.permission_version.history.has_changes():
        return "permission_changed"
    return None


def _stable_uuid_strings(values: Iterable[UUID | None]) -> list[str]:
    result: list[str] = []
    seen: set[UUID] = set()
    for value in values:
        if value is None or value in seen:
            continue
        seen.add(value)
        result.append(str(value))
    return result


def _uuid_or_none(value: object) -> UUID | None:
    return value if isinstance(value, UUID) else None


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
