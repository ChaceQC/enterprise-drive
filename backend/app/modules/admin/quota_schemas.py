from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

QuotaOwnerType = Literal["space", "tenant", "user", "policy"]
ManageableQuotaOwnerType = Literal["space", "tenant", "user"]


class AdminQuotaAccountResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    owner_type: QuotaOwnerType
    owner_id: UUID
    limit_bytes: int
    used_bytes: int
    remaining_bytes: int
    created_at: datetime
    updated_at: datetime


class AdminQuotaAccountListResponse(BaseModel):
    items: list[AdminQuotaAccountResponse]
    next_cursor: str | None = None


class AdminQuotaAccountUpsertRequest(BaseModel):
    limit_bytes: int = Field(ge=1)
    expected_limit_bytes: int | None = Field(default=None, ge=1)


class AdminQuotaPolicyResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    priority: int
    limit_bytes: int
    used_bytes: int
    max_file_size_bytes: int | None
    extensions: list[str]
    mime_prefixes: list[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AdminQuotaPolicyListResponse(BaseModel):
    items: list[AdminQuotaPolicyResponse]
    next_cursor: str | None = None


class AdminQuotaPolicyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    priority: int = Field(default=100, ge=0, le=1_000_000)
    limit_bytes: int = Field(ge=1)
    max_file_size_bytes: int | None = Field(default=None, ge=1)
    extensions: list[str] = Field(default_factory=list, max_length=100)
    mime_prefixes: list[str] = Field(default_factory=list, max_length=100)
    is_active: bool = True


class AdminQuotaPolicyUpdateRequest(BaseModel):
    expected_limit_bytes: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    priority: int | None = Field(default=None, ge=0, le=1_000_000)
    limit_bytes: int | None = Field(default=None, ge=1)
    max_file_size_bytes: int | None = Field(default=None, ge=1)
    clear_max_file_size: bool = False
    extensions: list[str] | None = Field(default=None, max_length=100)
    mime_prefixes: list[str] | None = Field(default=None, max_length=100)
    is_active: bool | None = None

    @model_validator(mode="after")
    def ensure_change_requested(self) -> AdminQuotaPolicyUpdateRequest:
        changed = any(
            value is not None
            for value in (
                self.name,
                self.priority,
                self.limit_bytes,
                self.max_file_size_bytes,
                self.extensions,
                self.mime_prefixes,
                self.is_active,
            )
        )
        if not changed and not self.clear_max_file_size:
            raise ValueError("至少提供一个策略变更字段")
        return self
