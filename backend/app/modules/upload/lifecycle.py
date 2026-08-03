from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.api.errors import ApiError
from app.core.config import Settings
from app.core.security import ensure_utc, utc_now
from app.infrastructure.storage.base import CompletedUploadPart, StorageAdapter
from app.modules.audit.schemas import AuditContext
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.file.models import Node
from app.modules.file.repository import FileRepository
from app.modules.file.validators import node_name_conflict_error
from app.modules.permission.actions import ACTION_UPLOAD
from app.modules.permission.service import PermissionService
from app.modules.preview.events import emit_preview_render_requested
from app.modules.quota.service import QuotaService
from app.modules.search.events import emit_search_extract_requested, emit_search_index_requested
from app.modules.space.repository import SpaceRepository
from app.modules.sync.client_operations import ClientOperationService
from app.modules.upload.audit import (
    aborted_upload_metadata,
    completed_upload_metadata,
    failed_upload_metadata,
    record_upload_event,
)
from app.modules.upload.hash import ensure_supported_upload_hash_algo, normalize_upload_hash
from app.modules.upload.models import UploadSession
from app.modules.upload.repository import UploadRepository
from app.modules.upload.schemas import (
    AbortUploadResponse,
    CompleteUploadPartRequest,
    CompleteUploadResponse,
)
from app.modules.upload.storage_keys import build_object_storage_key, is_upload_temp_storage_key
from app.modules.upload.timing import (
    UploadCompleteTimings,
    measure_upload_complete_phase,
)


class UploadLifecycleService:
    def __init__(
        self,
        *,
        repository: UploadRepository,
        file_repository: FileRepository,
        space_repository: SpaceRepository,
        permission_service: PermissionService,
        quota_service: QuotaService,
        storage: StorageAdapter,
        settings: Settings,
        client_operation_service: ClientOperationService,
        audit_service: AuditService | None = None,
    ) -> None:
        self.repository = repository
        self.file_repository = file_repository
        self.space_repository = space_repository
        self.permission_service = permission_service
        self.quota_service = quota_service
        self.storage = storage
        self.settings = settings
        self.client_operation_service = client_operation_service
        self.audit_service = audit_service

    async def complete_upload(
        self,
        *,
        current_user: User,
        session_id: UUID,
        parts: list[CompleteUploadPartRequest],
        client_operation_id: str | None = None,
        audit_context: AuditContext | None = None,
        timings: UploadCompleteTimings | None = None,
    ) -> CompleteUploadResponse:
        tenant_id = current_user.tenant_id
        user_id = current_user.id
        upload_session = await self._get_upload_session_for_update(
            current_user=current_user,
            session_id=session_id,
        )
        if upload_session.status == "completed":
            operation = await self.client_operation_service.start(
                tenant_id=tenant_id,
                user_id=user_id,
                operation_id=client_operation_id,
                action="upload.complete",
                request_payload={
                    "session_id": str(session_id),
                    "parts": [part.model_dump(mode="json") for part in parts],
                },
                allow_pending_recovery=True,
            )
            if operation.replay_json is not None:
                return CompleteUploadResponse.model_validate(operation.replay_json)
            response = self._completed_response(
                upload_session,
                client_operation_id=client_operation_id,
            )
            self.client_operation_service.complete(
                record=operation.record,
                response=response,
                response_status=200,
            )
            await self.repository.commit()
            return response
        if upload_session.status == "completing":
            raise ApiError("UPLOAD_COMPLETING", "上传正在完成中", status_code=409)
        await self._ensure_active_upload_session(upload_session)
        self._validate_complete_parts(upload_session=upload_session, parts=parts)

        await self._ensure_parent_still_owned(
            current_user=current_user,
            upload_session=upload_session,
        )
        await self._ensure_name_available(current_user=current_user, upload_session=upload_session)
        await self.quota_service.ensure_upload_capacity(
            tenant_id=tenant_id,
            space_id=upload_session.space_id,
            size_bytes=upload_session.size_bytes,
            user_id=user_id,
            file_name=upload_session.file_name,
            mime_type=upload_session.mime_type,
        )
        operation = await self.client_operation_service.start(
            tenant_id=tenant_id,
            user_id=user_id,
            operation_id=client_operation_id,
            action="upload.complete",
            request_payload={
                "session_id": str(session_id),
                "parts": [part.model_dump(mode="json") for part in parts],
            },
            allow_pending_recovery=True,
        )
        if operation.replay_json is not None:
            return CompleteUploadResponse.model_validate(operation.replay_json)
        upload_session.status = "completing"
        await self.repository.commit()

        try:
            with measure_upload_complete_phase(timings, "storage_complete"):
                completed = await self.storage.complete_multipart_upload(
                    bucket=upload_session.storage_bucket,
                    storage_key=upload_session.storage_key,
                    provider_upload_id=str(upload_session.provider_upload_id),
                    parts=[
                        CompletedUploadPart(
                            part_no=part.part_no,
                            etag=part.etag,
                            size_bytes=part.size_bytes,
                        )
                        for part in parts
                    ],
                )
        except Exception as exc:
            await self._mark_failed(
                current_user=current_user,
                session_id=session_id,
                reason="storage_complete_failed",
                audit_context=audit_context,
            )
            raise ApiError(
                "UPLOAD_COMPLETE_FAILED", "对象存储合并上传失败", status_code=502
            ) from exc

        if completed.size_bytes is not None and completed.size_bytes != upload_session.size_bytes:
            await self._mark_failed(
                current_user=current_user,
                session_id=session_id,
                reason="size_mismatch",
                audit_context=audit_context,
            )
            raise ApiError("UPLOAD_SIZE_MISMATCH", "上传对象大小不匹配", status_code=422)

        with measure_upload_complete_phase(timings, "hash_validation"):
            await self._validate_completed_object_hash(
                current_user=current_user,
                upload_session=upload_session,
                audit_context=audit_context,
            )
        storage_bucket = upload_session.storage_bucket
        temp_storage_key = upload_session.storage_key
        try:
            with measure_upload_complete_phase(timings, "final_object"):
                final_storage_key = await self._prepare_final_object(
                    current_user=current_user,
                    tenant_id=tenant_id,
                    upload_session=upload_session,
                    audit_context=audit_context,
                )
        except ApiError:
            raise
        should_delete_temp_object = final_storage_key != temp_storage_key

        upload_session = await self._get_upload_session_for_update(
            current_user=current_user,
            session_id=session_id,
        )
        try:
            if upload_session.status == "completed":
                response = self._completed_response(
                    upload_session,
                    client_operation_id=client_operation_id,
                )
                self.client_operation_service.complete(
                    record=operation.record,
                    response=response,
                    response_status=200,
                )
                await self.repository.commit()
                return response
            if upload_session.status != "completing":
                raise ApiError("UPLOAD_NOT_ACTIVE", "上传会话不可继续上传", status_code=409)
            now = utc_now()
            await self.repository.record_uploaded_parts(
                tenant_id=tenant_id,
                upload_session_id=upload_session.id,
                parts=[(part.part_no, part.etag, part.size_bytes) for part in parts],
                uploaded_at=now,
            )
            blob_resolution = await self.repository.resolve_file_blob_reference(
                tenant_id=tenant_id,
                hash_algo=upload_session.hash_algo,
                content_hash=upload_session.content_hash,
                size_bytes=upload_session.size_bytes,
                storage_key=final_storage_key,
                mime_type=upload_session.mime_type,
            )
            blob = blob_resolution.blob
            if not blob_resolution.created:
                if blob.status != "active":
                    raise ApiError("BLOB_DELETING", "文件内容正在清理，请稍后重试", status_code=409)
                blob_referenced = await self.repository.increment_blob_ref_count(
                    tenant_id=tenant_id,
                    blob_id=blob.id,
                )
                if not blob_referenced:
                    raise ApiError("BLOB_DELETING", "文件内容正在清理，请稍后重试", status_code=409)
            node = await self.repository.create_file_node(
                tenant_id=tenant_id,
                space_id=upload_session.space_id,
                parent_id=upload_session.parent_id,
                owner_id=user_id,
                name=upload_session.file_name,
                normalized_name=upload_session.normalized_name,
            )
            version = await self.repository.create_file_version(
                tenant_id=tenant_id,
                node_id=node.id,
                blob_id=blob.id,
                version_no=1,
                size_bytes=upload_session.size_bytes,
                mime_type=upload_session.mime_type,
                created_by=user_id,
            )
            node.current_version_id = version.id
            await self.quota_service.reserve_file_version(
                tenant_id=tenant_id,
                space_id=upload_session.space_id,
                version_id=version.id,
                size_bytes=upload_session.size_bytes,
                user_id=user_id,
                file_name=node.name,
                mime_type=upload_session.mime_type,
            )
            upload_session.status = "completed"
            upload_session.completed_node_id = node.id
            upload_session.completed_version_id = version.id
            upload_session.completed_blob_id = blob.id
            await self.repository.flush()
            await record_upload_event(
                audit_service=self.audit_service,
                current_user=current_user,
                action="upload.completed",
                resource_id=upload_session.id,
                audit_context=audit_context,
                metadata=completed_upload_metadata(
                    upload_session=upload_session,
                    node=node,
                    version=version,
                    blob=blob,
                ),
            )
            await emit_search_index_requested(
                audit_service=self.audit_service,
                tenant_id=tenant_id,
                node_id=node.id,
                space_id=upload_session.space_id,
                reason="upload_completed",
                metadata={"version_id": str(version.id), "blob_id": str(blob.id)},
            )
            await emit_search_extract_requested(
                audit_service=self.audit_service,
                tenant_id=tenant_id,
                node_id=node.id,
                version_id=version.id,
                blob_id=blob.id,
                reason="upload_completed",
            )
            await emit_preview_render_requested(
                audit_service=self.audit_service,
                tenant_id=tenant_id,
                node_id=node.id,
                version_id=version.id,
                blob_id=blob.id,
                reason="upload_completed",
            )
            response = CompleteUploadResponse(
                session_id=upload_session.id,
                node_id=node.id,
                version_id=version.id,
                blob_id=blob.id,
                client_operation_id=client_operation_id,
            )
            self.client_operation_service.complete(
                record=operation.record,
                response=response,
                response_status=200,
            )
            await self.repository.commit()
            if should_delete_temp_object:
                await self._delete_temp_object(
                    bucket=storage_bucket,
                    storage_key=temp_storage_key,
                )
        except ApiError as exc:
            await self.repository.rollback()
            failure_reason = {
                "QUOTA_EXCEEDED": "quota_exceeded",
                "BLOB_DELETING": "blob_deleting",
            }.get(exc.code, "db_finalize_failed")
            await self._mark_failed(
                current_user=current_user,
                session_id=session_id,
                reason=failure_reason,
                audit_context=audit_context,
            )
            raise
        except IntegrityError as exc:
            await self.repository.rollback()
            await self._mark_failed(
                current_user=current_user,
                session_id=session_id,
                reason="db_finalize_failed",
                audit_context=audit_context,
            )
            raise node_name_conflict_error() from exc

        return response

    async def abort_upload(
        self,
        *,
        current_user: User,
        session_id: UUID,
        client_operation_id: str | None = None,
        audit_context: AuditContext | None = None,
    ) -> AbortUploadResponse:
        upload_session = await self._get_upload_session_for_update(
            current_user=current_user,
            session_id=session_id,
        )
        if upload_session.status == "aborted":
            operation = await self.client_operation_service.start(
                tenant_id=current_user.tenant_id,
                user_id=current_user.id,
                operation_id=client_operation_id,
                action="upload.abort",
                request_payload={"session_id": str(session_id)},
                allow_pending_recovery=True,
            )
            if operation.replay_json is not None:
                return AbortUploadResponse.model_validate(operation.replay_json)
            response = AbortUploadResponse(
                session_id=upload_session.id,
                client_operation_id=client_operation_id,
            )
            self.client_operation_service.complete(
                record=operation.record,
                response=response,
                response_status=200,
            )
            await self.repository.commit()
            return response
        if upload_session.status == "completed":
            raise ApiError("UPLOAD_ALREADY_COMPLETED", "上传已完成，不能取消", status_code=409)
        if upload_session.status == "completing":
            raise ApiError("UPLOAD_COMPLETING", "上传正在完成中", status_code=409)

        provider_upload_id = upload_session.provider_upload_id
        storage_bucket = upload_session.storage_bucket
        storage_key = upload_session.storage_key
        operation = await self.client_operation_service.start(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            operation_id=client_operation_id,
            action="upload.abort",
            request_payload={"session_id": str(session_id)},
            allow_pending_recovery=True,
        )
        if operation.replay_json is not None:
            return AbortUploadResponse.model_validate(operation.replay_json)
        upload_session.status = "aborted"
        await self.repository.commit()

        if provider_upload_id is not None:
            try:
                await self.storage.abort_multipart_upload(
                    bucket=storage_bucket,
                    storage_key=storage_key,
                    provider_upload_id=provider_upload_id,
                )
            except Exception as exc:
                await self._mark_failed(
                    current_user=current_user,
                    session_id=session_id,
                    reason="storage_abort_failed",
                    audit_context=audit_context,
                )
                raise ApiError(
                    "UPLOAD_ABORT_FAILED", "对象存储取消上传失败", status_code=502
                ) from exc

        upload_session = await self._get_upload_session_for_update(
            current_user=current_user,
            session_id=session_id,
        )
        await record_upload_event(
            audit_service=self.audit_service,
            current_user=current_user,
            action="upload.aborted",
            resource_id=upload_session.id,
            audit_context=audit_context,
            metadata=aborted_upload_metadata(upload_session=upload_session),
        )
        response = AbortUploadResponse(
            session_id=upload_session.id,
            client_operation_id=client_operation_id,
        )
        self.client_operation_service.complete(
            record=operation.record,
            response=response,
            response_status=200,
        )
        await self.repository.commit()
        return response

    async def _mark_failed(
        self,
        *,
        current_user: User,
        session_id: UUID,
        reason: str,
        audit_context: AuditContext | None,
    ) -> None:
        upload_session = await self._get_upload_session_for_update(
            current_user=current_user,
            session_id=session_id,
        )
        if upload_session.status in {"completed", "expired"}:
            await self.repository.rollback()
            return
        storage_bucket = upload_session.storage_bucket
        storage_key = upload_session.storage_key
        provider_upload_id = upload_session.provider_upload_id
        upload_session.status = "failed"
        await self.repository.commit()

        cleanup_errors = await self._cleanup_failed_storage(
            bucket=storage_bucket,
            storage_key=storage_key,
            provider_upload_id=provider_upload_id,
        )
        upload_session = await self._get_upload_session_for_update(
            current_user=current_user,
            session_id=session_id,
        )
        await record_upload_event(
            audit_service=self.audit_service,
            current_user=current_user,
            action="upload.failed",
            resource_id=upload_session.id,
            result="denied",
            audit_context=audit_context,
            metadata=failed_upload_metadata(
                upload_session=upload_session,
                reason=reason,
                cleanup_errors=cleanup_errors,
            ),
        )
        await self.repository.commit()

    async def _cleanup_failed_storage(
        self,
        *,
        bucket: str,
        storage_key: str,
        provider_upload_id: str | None,
    ) -> list[str]:
        errors: list[str] = []
        if provider_upload_id is not None:
            try:
                await self.storage.abort_multipart_upload(
                    bucket=bucket,
                    storage_key=storage_key,
                    provider_upload_id=provider_upload_id,
                )
            except Exception:
                errors.append("abort_multipart_upload_failed")
        if is_upload_temp_storage_key(storage_key):
            try:
                await self.storage.delete_object(bucket=bucket, storage_key=storage_key)
            except Exception:
                errors.append("delete_temp_object_failed")
        return errors

    async def _validate_completed_object_hash(
        self,
        *,
        current_user: User,
        upload_session: UploadSession,
        audit_context: AuditContext | None,
    ) -> None:
        try:
            ensure_supported_upload_hash_algo(upload_session.hash_algo)
        except ApiError:
            await self._mark_failed(
                current_user=current_user,
                session_id=upload_session.id,
                reason="unsupported_hash_algo",
                audit_context=audit_context,
            )
            raise

        hash_algo = upload_session.hash_algo.lower()
        try:
            actual_hash = await self.storage.calculate_object_hash(
                bucket=upload_session.storage_bucket,
                storage_key=upload_session.storage_key,
                hash_algo=hash_algo,
            )
        except Exception as exc:
            await self._mark_failed(
                current_user=current_user,
                session_id=upload_session.id,
                reason="hash_calculation_failed",
                audit_context=audit_context,
            )
            raise ApiError(
                "UPLOAD_HASH_VALIDATION_FAILED", "上传文件 hash 校验失败", status_code=502
            ) from exc

        if normalize_upload_hash(actual_hash) != normalize_upload_hash(upload_session.content_hash):
            await self._mark_failed(
                current_user=current_user,
                session_id=upload_session.id,
                reason="hash_mismatch",
                audit_context=audit_context,
            )
            raise ApiError("UPLOAD_HASH_MISMATCH", "上传文件 hash 不匹配", status_code=422)

    async def _prepare_final_object(
        self,
        *,
        current_user: User,
        tenant_id: UUID,
        upload_session: UploadSession,
        audit_context: AuditContext | None,
    ) -> str:
        upload_session_id = upload_session.id
        hash_algo = upload_session.hash_algo
        content_hash = upload_session.content_hash
        size_bytes = upload_session.size_bytes
        storage_bucket = upload_session.storage_bucket
        source_key = upload_session.storage_key
        existing_blob = await self.repository.get_blob_by_hash_any_status(
            tenant_id=tenant_id,
            hash_algo=hash_algo,
            content_hash=content_hash,
            size_bytes=size_bytes,
        )
        if existing_blob is not None:
            if existing_blob.status == "active":
                return existing_blob.storage_key
            await self._mark_failed(
                current_user=current_user,
                session_id=upload_session_id,
                reason="blob_deleting",
                audit_context=audit_context,
            )
            raise ApiError("BLOB_DELETING", "文件内容正在清理，请稍后重试", status_code=409)
        await self.repository.commit()

        destination_key = build_object_storage_key(
            tenant_id=tenant_id,
            content_hash=content_hash,
        )
        try:
            await self.storage.copy_object(
                bucket=storage_bucket,
                source_key=source_key,
                destination_key=destination_key,
            )
        except Exception as exc:
            await self._mark_failed(
                current_user=current_user,
                session_id=upload_session_id,
                reason="object_finalize_failed",
                audit_context=audit_context,
            )
            raise ApiError(
                "UPLOAD_OBJECT_FINALIZE_FAILED", "上传对象归档失败", status_code=502
            ) from exc
        return destination_key

    async def _delete_temp_object(self, *, bucket: str, storage_key: str) -> None:
        try:
            await self.storage.delete_object(bucket=bucket, storage_key=storage_key)
        except Exception:
            return

    async def _get_upload_session_for_update(
        self,
        *,
        current_user: User,
        session_id: UUID,
    ) -> UploadSession:
        upload_session = await self.repository.get_upload_session_for_update(
            tenant_id=current_user.tenant_id,
            uploader_id=current_user.id,
            session_id=session_id,
        )
        if upload_session is None:
            raise ApiError("UPLOAD_SESSION_NOT_FOUND", "上传会话不存在或无权访问", status_code=404)
        return upload_session

    async def _ensure_active_upload_session(self, upload_session: UploadSession) -> None:
        if upload_session.status not in {"initiated", "uploading"}:
            raise ApiError("UPLOAD_NOT_ACTIVE", "上传会话不可继续上传", status_code=409)
        if ensure_utc(upload_session.expires_at) <= utc_now():
            upload_session.status = "expired"
            await self.repository.commit()
            raise ApiError("UPLOAD_SESSION_EXPIRED", "上传会话已过期", status_code=410)
        if upload_session.provider_upload_id is None:
            raise ApiError("UPLOAD_SESSION_INVALID", "上传会话缺少对象存储会话", status_code=500)

    def _validate_complete_parts(
        self,
        *,
        upload_session: UploadSession,
        parts: list[CompleteUploadPartRequest],
    ) -> None:
        if len(parts) != upload_session.total_parts:
            raise ApiError("UPLOAD_PART_MISSING", "上传分片数量不完整", status_code=422)
        sorted_parts = sorted(parts, key=lambda part: part.part_no)
        expected_numbers = list(range(1, upload_session.total_parts + 1))
        actual_numbers = [part.part_no for part in sorted_parts]
        if actual_numbers != expected_numbers or len(set(actual_numbers)) != len(actual_numbers):
            raise ApiError("UPLOAD_PART_INVALID", "上传分片编号不合法", status_code=422)

    async def _ensure_parent_still_owned(
        self,
        *,
        current_user: User,
        upload_session: UploadSession,
    ) -> Node:
        space = await self.space_repository.get_active_space(
            tenant_id=current_user.tenant_id,
            space_id=upload_session.space_id,
        )
        if space is None:
            raise ApiError("SPACE_NOT_FOUND", "空间不存在或无权访问", status_code=404)
        parent = await self.file_repository.get_node(
            tenant_id=current_user.tenant_id,
            space_id=upload_session.space_id,
            node_id=upload_session.parent_id,
        )
        if parent is None:
            raise ApiError("PARENT_NOT_FOUND", "父目录不存在或无权访问", status_code=404)
        if parent.node_type != "folder":
            raise ApiError("PARENT_NOT_FOLDER", "父节点不是文件夹", status_code=400)
        node_path_ids = await self.file_repository.get_node_path_ids(
            tenant_id=current_user.tenant_id,
            space_id=upload_session.space_id,
            node_id=parent.id,
        )
        allowed = node_path_ids is not None and await self.permission_service.can_access_node(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            space_id=upload_session.space_id,
            action=ACTION_UPLOAD,
            node_path_ids=node_path_ids,
        )
        if not allowed:
            raise ApiError("SPACE_NOT_FOUND", "空间不存在或无权访问", status_code=404)
        return parent

    async def _ensure_name_available(
        self,
        *,
        current_user: User,
        upload_session: UploadSession,
    ) -> None:
        existing_sibling = await self.file_repository.get_sibling_by_name(
            tenant_id=current_user.tenant_id,
            space_id=upload_session.space_id,
            parent_id=upload_session.parent_id,
            normalized_name=upload_session.normalized_name,
        )
        if existing_sibling is not None:
            raise node_name_conflict_error()

    def _completed_response(
        self,
        upload_session: UploadSession,
        *,
        client_operation_id: str | None = None,
    ) -> CompleteUploadResponse:
        if (
            upload_session.completed_node_id is None
            or upload_session.completed_version_id is None
            or upload_session.completed_blob_id is None
        ):
            raise ApiError("UPLOAD_SESSION_INVALID", "上传会话缺少完成结果", status_code=500)
        return CompleteUploadResponse(
            session_id=upload_session.id,
            node_id=upload_session.completed_node_id,
            version_id=upload_session.completed_version_id,
            blob_id=upload_session.completed_blob_id,
            client_operation_id=client_operation_id,
        )
