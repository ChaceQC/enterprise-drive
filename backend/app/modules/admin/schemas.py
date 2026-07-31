from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class AdminAuditLogResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    actor_id: UUID | None
    actor_type: str
    action: str
    resource_type: str
    resource_id: UUID | None
    result: str
    risk_level: str
    request_id: str | None
    ip: str | None
    user_agent: str | None
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: datetime


class AdminAuditLogListResponse(BaseModel):
    items: list[AdminAuditLogResponse]
    next_cursor: str | None = None
