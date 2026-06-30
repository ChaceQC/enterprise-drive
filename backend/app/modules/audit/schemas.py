from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID


@dataclass(frozen=True)
class AuditContext:
    request_id: str | None = None
    ip: str | None = None
    user_agent: str | None = None


@dataclass(frozen=True)
class AuditEvent:
    tenant_id: UUID
    action: str
    resource_type: str
    result: str
    actor_id: UUID | None = None
    actor_type: str = "user"
    resource_id: UUID | None = None
    risk_level: str = "low"
    metadata: dict[str, object] = field(default_factory=dict)
