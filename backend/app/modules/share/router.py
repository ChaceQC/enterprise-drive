from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    build_audit_context,
    enforce_public_rate_limit,
    ensure_supported_transfer_protocol,
    get_current_user,
    get_rate_limiter,
    get_storage_adapter,
)
from app.api.errors import ApiError
from app.core.config import Settings, get_settings
from app.core.security import hash_token
from app.db.session import get_db_session
from app.infrastructure.rate_limit.base import RateLimiter
from app.infrastructure.storage.base import StorageAdapter
from app.modules.audit.repository import AuditRepository
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.auth.repository import AuthRepository
from app.modules.auth.service import AuthService
from app.modules.file.repository import FileRepository
from app.modules.org.repository import OrgRepository
from app.modules.org.service import OrgService
from app.modules.permission.repository import PermissionRepository
from app.modules.permission.service import PermissionService
from app.modules.share.external_access import ShareExternalAccessService
from app.modules.share.external_download import ShareExternalDownloadService
from app.modules.share.repository import ShareRepository
from app.modules.share.schemas import (
    CreateShareRequest,
    CreateShareResponse,
    ExternalShareAccessRequest,
    ExternalShareAccessResponse,
    ExternalShareDownloadRequest,
    ExternalShareDownloadResponse,
    RevokeShareResponse,
    ShareDetail,
)
from app.modules.share.service import ShareService

router = APIRouter()


def get_share_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ShareService:
    permission_repository = PermissionRepository(session)
    org_service = OrgService(repository=OrgRepository(session))
    return ShareService(
        repository=ShareRepository(session),
        file_repository=FileRepository(session),
        permission_service=PermissionService(
            repository=permission_repository,
            org_service=org_service,
        ),
        audit_service=AuditService(repository=AuditRepository(session)),
    )


def get_auth_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthService:
    return AuthService(repository=AuthRepository(session), settings=settings)


def get_share_external_access_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ShareExternalAccessService:
    return ShareExternalAccessService(
        repository=ShareRepository(session),
        audit_service=AuditService(repository=AuditRepository(session)),
    )


def get_share_external_download_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    storage: Annotated[StorageAdapter, Depends(get_storage_adapter)],
) -> ShareExternalDownloadService:
    return ShareExternalDownloadService(
        repository=ShareRepository(session),
        file_repository=FileRepository(session),
        storage=storage,
        settings=settings,
        audit_service=AuditService(repository=AuditRepository(session)),
    )


@router.post("", response_model=CreateShareResponse, status_code=status.HTTP_201_CREATED)
async def create_share(
    http_request: Request,
    request: CreateShareRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ShareService, Depends(get_share_service)],
) -> CreateShareResponse:
    result = await service.create_share(
        current_user=current_user,
        share_type=request.share_type,
        root_node_id=request.root_node_id,
        permission=request.permission,
        item_node_ids=request.item_node_ids,
        recipients=request.recipients,
        passcode=request.passcode,
        expires_at=request.expires_at,
        max_views=request.max_views,
        max_downloads=request.max_downloads,
        audit_context=build_audit_context(http_request),
    )
    return CreateShareResponse.model_validate(result)


@router.get("/{share_id}", response_model=ShareDetail)
async def get_share_detail(
    share_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ShareService, Depends(get_share_service)],
) -> ShareDetail:
    return await service.get_share_detail(current_user=current_user, share_id=share_id)


@router.post("/{share_id}/revoke", response_model=RevokeShareResponse)
async def revoke_share(
    http_request: Request,
    share_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ShareService, Depends(get_share_service)],
) -> RevokeShareResponse:
    await service.revoke_share(
        current_user=current_user,
        share_id=share_id,
        audit_context=build_audit_context(http_request),
    )
    return RevokeShareResponse(share_id=share_id)


public_router = APIRouter()


@public_router.post("/access", response_model=ExternalShareAccessResponse)
async def access_external_share(
    http_request: Request,
    request: ExternalShareAccessRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    service: Annotated[
        ShareExternalAccessService,
        Depends(get_share_external_access_service),
    ],
) -> ExternalShareAccessResponse:
    await enforce_public_rate_limit(
        settings=settings,
        rate_limiter=rate_limiter,
        action="share.external_access",
        request=http_request,
        resource_key="share-access",
    )
    await enforce_public_rate_limit(
        settings=settings,
        rate_limiter=rate_limiter,
        action="share.external_access",
        request=http_request,
        resource_key=f"share-access-token:{hash_token(request.raw_token)}",
    )
    tenant_id = await auth_service.get_tenant_id_by_slug(request.tenant_slug)
    if tenant_id is None:
        raise ApiError("SHARE_NOT_FOUND", "分享不存在", status_code=404)
    return await service.access_external_share(
        tenant_id=tenant_id,
        raw_token=request.raw_token,
        passcode=request.passcode,
        audit_context=build_audit_context(http_request),
    )


@public_router.post(
    "/download",
    response_model=ExternalShareDownloadResponse,
    dependencies=[Depends(ensure_supported_transfer_protocol)],
)
async def create_external_download_url(
    http_request: Request,
    request: ExternalShareDownloadRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    service: Annotated[
        ShareExternalDownloadService,
        Depends(get_share_external_download_service),
    ],
) -> ExternalShareDownloadResponse:
    await enforce_public_rate_limit(
        settings=settings,
        rate_limiter=rate_limiter,
        action="share.external_download",
        request=http_request,
        resource_key="share-download",
    )
    await enforce_public_rate_limit(
        settings=settings,
        rate_limiter=rate_limiter,
        action="share.external_download",
        request=http_request,
        resource_key=f"share-download-token:{hash_token(request.raw_token)}:node:{request.node_id}",
    )
    tenant_id = await auth_service.get_tenant_id_by_slug(request.tenant_slug)
    if tenant_id is None:
        raise ApiError("SHARE_NOT_FOUND", "分享不存在", status_code=404)
    return await service.create_external_download_url(
        tenant_id=tenant_id,
        raw_token=request.raw_token,
        node_id=request.node_id,
        passcode=request.passcode,
        audit_context=build_audit_context(http_request),
    )
