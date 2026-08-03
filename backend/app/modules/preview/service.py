from __future__ import annotations

from uuid import UUID

from app.api.errors import ApiError
from app.core.config import Settings
from app.infrastructure.storage.base import StorageAdapter
from app.modules.auth.models import User
from app.modules.file.repository import FileRepository
from app.modules.permission.actions import ACTION_PREVIEW
from app.modules.permission.service import PermissionService
from app.modules.preview.repository import PreviewRepository
from app.modules.preview.schemas import FilePreviewResponse, PreviewArtifactResponse
from app.modules.space.repository import SpaceRepository


class PreviewAccessService:
    def __init__(
        self,
        *,
        repository: PreviewRepository,
        file_repository: FileRepository,
        space_repository: SpaceRepository,
        permission_service: PermissionService,
        storage: StorageAdapter,
        settings: Settings,
    ) -> None:
        self.repository = repository
        self.file_repository = file_repository
        self.space_repository = space_repository
        self.permission_service = permission_service
        self.storage = storage
        self.settings = settings

    async def create_preview_url(
        self,
        *,
        current_user: User,
        node_id: UUID,
    ) -> FilePreviewResponse:
        node = await self.file_repository.get_node_by_id(
            tenant_id=current_user.tenant_id,
            node_id=node_id,
        )
        if node is None:
            raise ApiError("NODE_NOT_FOUND", "节点不存在或无权访问", status_code=404)
        if node.node_type != "file":
            raise ApiError("NODE_NOT_FILE", "节点不是文件", status_code=400)
        if node.current_version_id is None:
            raise ApiError("FILE_VERSION_NOT_FOUND", "文件当前版本不存在", status_code=404)

        space = await self.space_repository.get_active_space(
            tenant_id=current_user.tenant_id,
            space_id=node.space_id,
        )
        node_path_ids = await self.file_repository.get_node_path_ids(
            tenant_id=current_user.tenant_id,
            space_id=node.space_id,
            node_id=node.id,
        )
        allowed = (
            space is not None
            and node_path_ids is not None
            and await self.permission_service.can_access_node(
                tenant_id=current_user.tenant_id,
                user_id=current_user.id,
                space_id=node.space_id,
                action=ACTION_PREVIEW,
                node_path_ids=node_path_ids,
            )
        )
        if not allowed:
            raise ApiError("NODE_NOT_FOUND", "节点不存在或无权访问", status_code=404)

        record = await self.repository.get_version_blob_node(
            tenant_id=current_user.tenant_id,
            version_id=node.current_version_id,
        )
        if record is None:
            raise ApiError("FILE_VERSION_NOT_FOUND", "文件当前版本不存在", status_code=404)
        version, _, _ = record
        artifact = await self.repository.get_artifact(
            tenant_id=current_user.tenant_id,
            version_id=version.id,
            artifact_type="image",
        )
        if artifact is None:
            return FilePreviewResponse(
                node_id=node.id,
                version_id=version.id,
                status=version.preview_status,
                error=version.preview_error,
            )

        await self.repository.touch_artifact(artifact)
        presigned = await self.storage.presign_download(
            bucket=self.settings.s3_bucket,
            storage_key=artifact.storage_key,
            filename=f"{node.name}.webp",
            expires_in_seconds=self.settings.preview_presign_expires_seconds,
        )
        await self.repository.commit()
        return FilePreviewResponse(
            node_id=node.id,
            version_id=version.id,
            status=version.preview_status,
            error=version.preview_error,
            artifact=PreviewArtifactResponse(
                artifact_id=artifact.id,
                artifact_type=artifact.artifact_type,
                mime_type=artifact.mime_type,
                size_bytes=artifact.size_bytes,
                preview_url=presigned.download_url,
                expires_at=presigned.expires_at,
                headers=presigned.headers,
            ),
        )
