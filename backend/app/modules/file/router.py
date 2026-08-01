from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    build_audit_context,
    enforce_rate_limit,
    ensure_supported_transfer_protocol,
    get_current_user,
    get_rate_limiter,
    get_storage_adapter,
)
from app.api.errors import ApiError
from app.core.config import Settings, get_settings
from app.core.metrics import record_download_request
from app.db.session import get_db_session
from app.infrastructure.rate_limit.base import RateLimiter
from app.infrastructure.storage.base import StorageAdapter
from app.modules.audit.repository import AuditRepository
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.file.download import FileDownloadService
from app.modules.file.repository import FileRepository
from app.modules.file.schemas import (
    CreateFolderRequest,
    DeleteNodeResponse,
    FileDownloadUrlResponse,
    FileListResponse,
    FileNodeResponse,
    FileVersionListResponse,
    FileVersionRollbackRequest,
    FileVersionRollbackResponse,
    MoveNodeRequest,
    PurgeNodeResponse,
    RenameNodeRequest,
    RestoreNodeRequest,
)
from app.modules.file.service import FileService
from app.modules.file.version_service import FileVersionService
from app.modules.org.repository import OrgRepository
from app.modules.org.service import OrgService
from app.modules.permission.repository import PermissionRepository
from app.modules.permission.service import PermissionService
from app.modules.preview.repository import PreviewRepository
from app.modules.preview.schemas import FilePreviewResponse
from app.modules.preview.service import PreviewAccessService
from app.modules.quota.repository import QuotaRepository
from app.modules.quota.service import QuotaService
from app.modules.space.repository import SpaceRepository

router = APIRouter()


def get_file_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> FileService:
    permission_repository = PermissionRepository(session)
    org_service = OrgService(repository=OrgRepository(session))
    return FileService(
        repository=FileRepository(session),
        space_repository=SpaceRepository(session),
        permission_service=PermissionService(
            repository=permission_repository,
            org_service=org_service,
        ),
        quota_service=QuotaService(
            repository=QuotaRepository(session),
            default_space_limit_bytes=settings.default_space_quota_bytes,
            default_user_limit_bytes=settings.default_user_quota_bytes,
            default_tenant_limit_bytes=settings.default_tenant_quota_bytes,
            policy_enabled=settings.quota_policy_enabled,
        ),
        settings=settings,
        audit_service=AuditService(repository=AuditRepository(session)),
    )


def get_file_download_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    storage: Annotated[StorageAdapter, Depends(get_storage_adapter)],
) -> FileDownloadService:
    permission_repository = PermissionRepository(session)
    org_service = OrgService(repository=OrgRepository(session))
    return FileDownloadService(
        repository=FileRepository(session),
        space_repository=SpaceRepository(session),
        permission_service=PermissionService(
            repository=permission_repository,
            org_service=org_service,
        ),
        storage=storage,
        settings=settings,
        audit_service=AuditService(repository=AuditRepository(session)),
    )


def get_file_version_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    storage: Annotated[StorageAdapter, Depends(get_storage_adapter)],
) -> FileVersionService:
    permission_repository = PermissionRepository(session)
    org_service = OrgService(repository=OrgRepository(session))
    return FileVersionService(
        repository=FileRepository(session),
        space_repository=SpaceRepository(session),
        permission_service=PermissionService(
            repository=permission_repository,
            org_service=org_service,
        ),
        quota_service=QuotaService(
            repository=QuotaRepository(session),
            default_space_limit_bytes=settings.default_space_quota_bytes,
            default_user_limit_bytes=settings.default_user_quota_bytes,
            default_tenant_limit_bytes=settings.default_tenant_quota_bytes,
            policy_enabled=settings.quota_policy_enabled,
        ),
        storage=storage,
        settings=settings,
        audit_service=AuditService(repository=AuditRepository(session)),
    )


def get_preview_access_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    storage: Annotated[StorageAdapter, Depends(get_storage_adapter)],
) -> PreviewAccessService:
    permission_repository = PermissionRepository(session)
    org_service = OrgService(repository=OrgRepository(session))
    return PreviewAccessService(
        repository=PreviewRepository(session),
        file_repository=FileRepository(session),
        space_repository=SpaceRepository(session),
        permission_service=PermissionService(
            repository=permission_repository,
            org_service=org_service,
        ),
        storage=storage,
        settings=settings,
    )


@router.post("/folders", response_model=FileNodeResponse, status_code=status.HTTP_201_CREATED)
async def create_folder(
    http_request: Request,
    request: CreateFolderRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[FileService, Depends(get_file_service)],
) -> FileNodeResponse:
    return await service.create_folder(
        current_user=current_user,
        space_id=request.space_id,
        parent_id=request.parent_id,
        name=request.name,
        audit_context=build_audit_context(http_request),
    )


@router.get("", response_model=FileListResponse)
async def list_files(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[FileService, Depends(get_file_service)],
    space_id: Annotated[UUID, Query()],
    parent_id: Annotated[UUID | None, Query()] = None,
    cursor: Annotated[str | None, Query(min_length=1)] = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> FileListResponse:
    return await service.list_children(
        current_user=current_user,
        space_id=space_id,
        parent_id=parent_id,
        cursor=cursor,
        page_size=page_size,
    )


@router.patch("/{node_id}", response_model=FileNodeResponse)
async def rename_node(
    http_request: Request,
    node_id: UUID,
    request: RenameNodeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[FileService, Depends(get_file_service)],
) -> FileNodeResponse:
    return await service.rename_node(
        current_user=current_user,
        node_id=node_id,
        name=request.name,
        audit_context=build_audit_context(http_request),
    )


@router.post("/{node_id}/move", response_model=FileNodeResponse)
async def move_node(
    http_request: Request,
    node_id: UUID,
    request: MoveNodeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[FileService, Depends(get_file_service)],
) -> FileNodeResponse:
    return await service.move_node(
        current_user=current_user,
        node_id=node_id,
        target_parent_id=request.target_parent_id,
        new_name=request.new_name,
        audit_context=build_audit_context(http_request),
    )


@router.delete("/{node_id}", response_model=DeleteNodeResponse)
async def delete_node(
    http_request: Request,
    node_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[FileService, Depends(get_file_service)],
) -> DeleteNodeResponse:
    return await service.delete_node(
        current_user=current_user,
        node_id=node_id,
        audit_context=build_audit_context(http_request),
    )


@router.delete("/{node_id}/purge", response_model=PurgeNodeResponse)
async def purge_node(
    http_request: Request,
    node_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[FileService, Depends(get_file_service)],
) -> PurgeNodeResponse:
    return await service.purge_node(
        current_user=current_user,
        node_id=node_id,
        audit_context=build_audit_context(http_request),
    )


@router.get("/{node_id}/versions", response_model=FileVersionListResponse)
async def list_file_versions(
    http_request: Request,
    node_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[FileVersionService, Depends(get_file_version_service)],
    cursor: Annotated[str | None, Query(min_length=1)] = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> FileVersionListResponse:
    return await service.list_versions(
        current_user=current_user,
        node_id=node_id,
        cursor=cursor,
        page_size=page_size,
        audit_context=build_audit_context(http_request),
    )


@router.get(
    "/{node_id}/versions/{version_id}/download",
    response_model=FileDownloadUrlResponse,
    dependencies=[Depends(ensure_supported_transfer_protocol)],
)
async def create_version_download_url(
    http_request: Request,
    node_id: UUID,
    version_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    service: Annotated[FileVersionService, Depends(get_file_version_service)],
) -> FileDownloadUrlResponse:
    try:
        await enforce_rate_limit(
            settings=settings,
            rate_limiter=rate_limiter,
            current_user=current_user,
            action="file.download_presign",
            resource_key=f"node:{node_id}:version:{version_id}",
            request=http_request,
        )
        response = await service.create_version_download_url(
            current_user=current_user,
            node_id=node_id,
            version_id=version_id,
            audit_context=build_audit_context(http_request),
        )
    except ApiError as exc:
        record_download_request(
            channel="internal_version",
            outcome="denied" if exc.status_code < 500 else "error",
        )
        raise
    except Exception:
        record_download_request(channel="internal_version", outcome="error")
        raise
    record_download_request(channel="internal_version", outcome="allowed")
    return response


@router.post(
    "/{node_id}/versions/{version_id}/rollback",
    response_model=FileVersionRollbackResponse,
)
async def rollback_file_version(
    http_request: Request,
    node_id: UUID,
    version_id: UUID,
    request: FileVersionRollbackRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[FileVersionService, Depends(get_file_version_service)],
) -> FileVersionRollbackResponse:
    return await service.rollback_version(
        current_user=current_user,
        node_id=node_id,
        source_version_id=version_id,
        expected_current_version_id=request.expected_current_version_id,
        audit_context=build_audit_context(http_request),
    )


@router.get(
    "/{node_id}/download",
    response_model=FileDownloadUrlResponse,
    dependencies=[Depends(ensure_supported_transfer_protocol)],
)
async def create_download_url(
    http_request: Request,
    node_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    service: Annotated[FileDownloadService, Depends(get_file_download_service)],
) -> FileDownloadUrlResponse:
    try:
        await enforce_rate_limit(
            settings=settings,
            rate_limiter=rate_limiter,
            current_user=current_user,
            action="file.download_presign",
            resource_key=f"node:{node_id}",
            request=http_request,
        )
        response = await service.create_download_url(
            current_user=current_user,
            node_id=node_id,
            audit_context=build_audit_context(http_request),
        )
    except ApiError as exc:
        record_download_request(
            channel="internal",
            outcome="denied" if exc.status_code < 500 else "error",
        )
        raise
    except Exception:
        record_download_request(channel="internal", outcome="error")
        raise
    record_download_request(channel="internal", outcome="allowed")
    return response


@router.get(
    "/{node_id}/content",
    dependencies=[Depends(ensure_supported_transfer_protocol)],
    response_class=StreamingResponse,
    responses={
        200: {"description": "完整代理下载"},
        206: {"description": "单段 Range 代理下载"},
        416: {"description": "Range 不合法、不可满足或超过单段上限"},
    },
)
async def proxy_download_content(
    http_request: Request,
    node_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    service: Annotated[FileDownloadService, Depends(get_file_download_service)],
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> StreamingResponse:
    if not settings.download_proxy_enabled:
        raise ApiError("DOWNLOAD_PROXY_DISABLED", "代理下载未启用", status_code=404)
    try:
        await enforce_rate_limit(
            settings=settings,
            rate_limiter=rate_limiter,
            current_user=current_user,
            action="file.download_proxy",
            resource_key=f"node:{node_id}",
            request=http_request,
        )
        download = await service.create_proxy_download(
            current_user=current_user,
            node_id=node_id,
            range_header=range_header,
            audit_context=build_audit_context(http_request),
        )
    except ApiError as exc:
        record_download_request(
            channel="internal_proxy",
            outcome="denied" if exc.status_code < 500 else "error",
        )
        raise
    except Exception:
        record_download_request(channel="internal_proxy", outcome="error")
        raise
    record_download_request(channel="internal_proxy", outcome="allowed")
    return StreamingResponse(
        content=download.body,
        status_code=download.status_code,
        media_type=download.media_type,
        headers=download.headers,
    )


@router.get("/{node_id}/preview", response_model=FilePreviewResponse)
async def create_preview_url(
    node_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[PreviewAccessService, Depends(get_preview_access_service)],
) -> FilePreviewResponse:
    return await service.create_preview_url(current_user=current_user, node_id=node_id)


@router.post("/{node_id}/restore", response_model=FileNodeResponse)
async def restore_node(
    http_request: Request,
    node_id: UUID,
    request: RestoreNodeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[FileService, Depends(get_file_service)],
) -> FileNodeResponse:
    return await service.restore_node(
        current_user=current_user,
        node_id=node_id,
        target_parent_id=request.target_parent_id,
        new_name=request.new_name,
        audit_context=build_audit_context(http_request),
    )
