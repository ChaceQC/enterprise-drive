from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

FileClassification = Literal["internal", "confidential", "restricted"]
FileDownloadMode = Literal["presigned", "proxy", "watermark", "blocked"]
DlpAction = Literal["audit", "block"]


class AdminFileSecurityPolicyResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    priority: int
    classification: FileClassification
    download_mode: FileDownloadMode
    extensions: list[str]
    mime_prefixes: list[str]
    dlp_keywords: list[str]
    dlp_action: DlpAction
    fail_closed: bool
    watermark_text: str | None
    is_active: bool
    version: int
    created_at: datetime
    updated_at: datetime


class AdminFileSecurityPolicyListResponse(BaseModel):
    items: list[AdminFileSecurityPolicyResponse]
    next_cursor: str | None = None


class AdminFileSecurityPolicyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    priority: int = Field(default=100, ge=0, le=1_000_000)
    classification: FileClassification = "internal"
    download_mode: FileDownloadMode = "presigned"
    extensions: list[str] = Field(default_factory=list, max_length=100)
    mime_prefixes: list[str] = Field(default_factory=list, max_length=100)
    dlp_keywords: list[str] = Field(default_factory=list, max_length=100)
    dlp_action: DlpAction = "audit"
    fail_closed: bool = False
    watermark_text: str | None = Field(default=None, max_length=256)
    is_active: bool = True


class AdminFileSecurityPolicyUpdateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    priority: int | None = Field(default=None, ge=0, le=1_000_000)
    classification: FileClassification | None = None
    download_mode: FileDownloadMode | None = None
    extensions: list[str] | None = Field(default=None, max_length=100)
    mime_prefixes: list[str] | None = Field(default=None, max_length=100)
    dlp_keywords: list[str] | None = Field(default=None, max_length=100)
    dlp_action: DlpAction | None = None
    fail_closed: bool | None = None
    watermark_text: str | None = Field(default=None, max_length=256)
    clear_watermark_text: bool = False
    is_active: bool | None = None

    @model_validator(mode="after")
    def ensure_change_requested(self) -> AdminFileSecurityPolicyUpdateRequest:
        changed = any(
            value is not None
            for value in (
                self.name,
                self.priority,
                self.classification,
                self.download_mode,
                self.extensions,
                self.mime_prefixes,
                self.dlp_keywords,
                self.dlp_action,
                self.fail_closed,
                self.watermark_text,
                self.is_active,
            )
        )
        if not changed and not self.clear_watermark_text:
            raise ValueError("至少提供一个安全策略变更字段")
        return self
