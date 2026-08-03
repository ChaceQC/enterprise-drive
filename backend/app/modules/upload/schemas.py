from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.core.transfer_protocol import DriveTransferProtocolResponse


class InitUploadRequest(BaseModel):
    space_id: UUID
    parent_id: UUID
    file_name: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=1)
    content_hash: str = Field(min_length=16, max_length=128)
    hash_algo: str = Field(default="sha256", min_length=1, max_length=16)
    mime_type: str | None = Field(default=None, max_length=255)
    conflict_policy: Literal["fail"] = "fail"
    target_node_id: UUID | None = None
    expected_current_version_id: UUID | None = None

    @model_validator(mode="after")
    def validate_version_target(self) -> InitUploadRequest:
        if self.target_node_id is None and self.expected_current_version_id is not None:
            raise ValueError("expected_current_version_id requires target_node_id")
        if self.target_node_id is not None and self.expected_current_version_id is None:
            raise ValueError("target_node_id requires expected_current_version_id")
        return self


class InstantUploadResponse(DriveTransferProtocolResponse):
    mode: Literal["instant"] = "instant"
    node_id: UUID
    version_id: UUID
    blob_id: UUID


class MultipartUploadResponse(DriveTransferProtocolResponse):
    mode: Literal["multipart"] = "multipart"
    session_id: UUID
    part_size_bytes: int
    total_parts: int
    max_parallelism: int
    checksum_algorithm: Literal["sha256"] = "sha256"
    expires_at: datetime


class UploadPartUrlResponse(DriveTransferProtocolResponse):
    part_no: int
    upload_url: str
    expires_at: datetime
    headers: dict[str, str]


class UploadSessionStatusResponse(DriveTransferProtocolResponse):
    session_id: UUID
    status: str
    file_name: str
    size_bytes: int
    part_size_bytes: int
    total_parts: int
    max_parallelism: int
    checksum_algorithm: Literal["sha256"] = "sha256"
    uploaded_parts: list[int]
    expires_at: datetime
    completed_node_id: UUID | None
    completed_version_id: UUID | None
    target_node_id: UUID | None
    expected_current_version_id: UUID | None


class CompleteUploadPartRequest(BaseModel):
    part_no: int = Field(ge=1)
    etag: str = Field(min_length=1, max_length=255)
    size_bytes: int | None = Field(default=None, ge=1)


class CompleteUploadRequest(BaseModel):
    parts: list[CompleteUploadPartRequest] = Field(min_length=1)


class BatchPresignUploadPartsRequest(BaseModel):
    part_numbers: list[int] = Field(min_length=1, max_length=32)


class BatchPresignUploadPartsResponse(DriveTransferProtocolResponse):
    session_id: UUID
    max_parallelism: int
    items: list[UploadPartUrlResponse]


class ConfirmUploadPartRequest(BaseModel):
    etag: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=1)


class ConfirmUploadPartResponse(DriveTransferProtocolResponse):
    session_id: UUID
    part_no: int
    uploaded_parts: list[int]


class CompleteUploadResponse(DriveTransferProtocolResponse):
    session_id: UUID
    status: Literal["completed"] = "completed"
    node_id: UUID
    version_id: UUID
    blob_id: UUID


class AbortUploadResponse(DriveTransferProtocolResponse):
    session_id: UUID
    status: Literal["aborted"] = "aborted"


InitUploadResponse = InstantUploadResponse | MultipartUploadResponse
