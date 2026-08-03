from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class SyncChangeResponse(BaseModel):
    sequence: int
    change_type: str
    node_id: UUID
    space_id: UUID
    parent_id: UUID | None
    node_type: str | None
    name: str | None
    current_version_id: UUID | None
    permission_version: int | None
    tombstone: bool
    client_operation_id: str | None
    changed_at: datetime


class SyncChangeListResponse(BaseModel):
    space_id: UUID
    root_node_id: UUID
    items: list[SyncChangeResponse]
    next_cursor: str
    has_more: bool
    cursor_expires_at: datetime
