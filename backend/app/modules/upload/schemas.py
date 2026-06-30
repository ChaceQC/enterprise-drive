from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class InitUploadRequest(BaseModel):
    space_id: UUID
    parent_id: UUID
    file_name: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=1)
    content_hash: str = Field(min_length=16, max_length=128)
    hash_algo: str = Field(default="sha256", min_length=1, max_length=16)
    mime_type: str | None = Field(default=None, max_length=255)
    conflict_policy: Literal["fail"] = "fail"


class InstantUploadResponse(BaseModel):
    mode: Literal["instant"] = "instant"
    node_id: UUID
    version_id: UUID
    blob_id: UUID


class MultipartUploadResponse(BaseModel):
    mode: Literal["multipart"] = "multipart"
    session_id: UUID
    part_size_bytes: int
    total_parts: int
    expires_at: datetime


class UploadPartUrlResponse(BaseModel):
    part_no: int
    upload_url: str
    expires_at: datetime
    headers: dict[str, str]


class UploadSessionStatusResponse(BaseModel):
    session_id: UUID
    status: str
    file_name: str
    size_bytes: int
    part_size_bytes: int
    total_parts: int
    uploaded_parts: list[int]
    expires_at: datetime
    completed_node_id: UUID | None
    completed_version_id: UUID | None


InitUploadResponse = InstantUploadResponse | MultipartUploadResponse
