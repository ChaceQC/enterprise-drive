from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    build_audit_context,
    enforce_public_rate_limit,
    enforce_rate_limit,
    ensure_supported_transfer_protocol,
    get_current_user,
    get_rate_limiter,
    get_storage_adapter,
)
from app.api.errors import ApiError
from app.core.config import Settings, get_settings
from app.core.metrics import record_download_request
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
from app.modules.file_security.repository import FileSecurityRepository
from app.modules.file_security.service import FileSecurityService
from app.modules.org.repository import OrgRepository
from app.modules.org.service import OrgService
from app.modules.permission.repository import PermissionRepository
from app.modules.permission.service import PermissionService
from app.modules.share.external_access import ShareExternalAccessService
from app.modules.share.external_download import ShareExternalDownloadService
from app.modules.share.internal import InternalShareService
from app.modules.share.recipient_grants import ShareRecipientGrantService
from app.modules.share.repository import ShareRepository
from app.modules.share.schemas import (
    CreateShareRequest,
    CreateShareResponse,
    ExternalShareAccessRequest,
    ExternalShareAccessResponse,
    ExternalShareDownloadRequest,
    ExternalShareDownloadResponse,
    InternalShareDownloadRequest,
    InternalShareDownloadResponse,
    InternalShareItemsResponse,
    RevokeShareResponse,
    ShareDetail,
    ShareListResponse,
    ShareNotificationListResponse,
    ShareNotificationReadResponse,
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
        security_service=FileSecurityService(
            repository=FileSecurityRepository(session),
            enabled=settings.file_security_policy_enabled,
        ),
    )


def get_internal_share_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    storage: Annotated[StorageAdapter, Depends(get_storage_adapter)],
) -> InternalShareService:
    repository = ShareRepository(session)
    auth_repository = AuthRepository(session)
    org_service = OrgService(repository=OrgRepository(session))
    recipient_grant_service = ShareRecipientGrantService(
        repository=repository,
        auth_repository=auth_repository,
        org_service=org_service,
    )
    return InternalShareService(
        repository=repository,
        file_repository=FileRepository(session),
        auth_repository=auth_repository,
        permission_service=PermissionService(
            repository=PermissionRepository(session),
            org_service=org_service,
        ),
        recipient_grant_service=recipient_grant_service,
        storage=storage,
        settings=settings,
        audit_service=AuditService(repository=AuditRepository(session)),
        security_service=FileSecurityService(
            repository=FileSecurityRepository(session),
            enabled=settings.file_security_policy_enabled,
        ),
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


@router.get("/created", response_model=ShareListResponse)
async def list_created_shares(
    http_request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[InternalShareService, Depends(get_internal_share_service)],
    cursor: Annotated[str | None, Query(min_length=1)] = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ShareListResponse:
    return await service.list_created(
        current_user=current_user,
        cursor=cursor,
        page_size=page_size,
        audit_context=build_audit_context(http_request),
    )


@router.get("/received", response_model=ShareListResponse)
async def list_received_shares(
    http_request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[InternalShareService, Depends(get_internal_share_service)],
    cursor: Annotated[str | None, Query(min_length=1)] = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ShareListResponse:
    return await service.list_received(
        current_user=current_user,
        cursor=cursor,
        page_size=page_size,
        audit_context=build_audit_context(http_request),
    )


@router.get("/notifications", response_model=ShareNotificationListResponse)
async def list_share_notifications(
    http_request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[InternalShareService, Depends(get_internal_share_service)],
    unread_only: Annotated[bool, Query()] = False,
    cursor: Annotated[str | None, Query(min_length=1)] = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ShareNotificationListResponse:
    return await service.list_notifications(
        current_user=current_user,
        unread_only=unread_only,
        cursor=cursor,
        page_size=page_size,
        audit_context=build_audit_context(http_request),
    )


@router.post(
    "/notifications/{notification_id}/read",
    response_model=ShareNotificationReadResponse,
)
async def mark_share_notification_read(
    http_request: Request,
    notification_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[InternalShareService, Depends(get_internal_share_service)],
) -> ShareNotificationReadResponse:
    return await service.mark_notification_read(
        current_user=current_user,
        notification_id=notification_id,
        audit_context=build_audit_context(http_request),
    )


@router.get("/{share_id}/items", response_model=InternalShareItemsResponse)
async def list_internal_share_items(
    http_request: Request,
    share_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[InternalShareService, Depends(get_internal_share_service)],
) -> InternalShareItemsResponse:
    audit_context = build_audit_context(http_request)
    try:
        return await service.list_items(
            current_user=current_user,
            share_id=share_id,
            audit_context=audit_context,
        )
    except ApiError as exc:
        await service.record_denied_request(
            current_user=current_user,
            share_id=share_id,
            action="accessed",
            error=exc,
            audit_context=audit_context,
        )
        raise


@router.post(
    "/{share_id}/download",
    response_model=InternalShareDownloadResponse,
    dependencies=[Depends(ensure_supported_transfer_protocol)],
)
async def create_internal_share_download_url(
    http_request: Request,
    share_id: UUID,
    request: InternalShareDownloadRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    service: Annotated[InternalShareService, Depends(get_internal_share_service)],
) -> InternalShareDownloadResponse:
    audit_context = build_audit_context(http_request)
    try:
        await enforce_rate_limit(
            settings=settings,
            rate_limiter=rate_limiter,
            current_user=current_user,
            action="file.download_presign",
            resource_key=f"internal-share:{share_id}:node:{request.node_id}",
            request=http_request,
        )
        response = await service.create_download_url(
            current_user=current_user,
            share_id=share_id,
            node_id=request.node_id,
            delivery_mode=request.delivery_mode,
            audit_context=audit_context,
        )
    except ApiError as exc:
        await service.record_denied_request(
            current_user=current_user,
            share_id=share_id,
            action="downloaded",
            error=exc,
            audit_context=audit_context,
            node_id=request.node_id,
        )
        record_download_request(
            channel="internal_share",
            outcome="denied" if exc.status_code < 500 else "error",
        )
        raise
    except Exception:
        record_download_request(channel="internal_share", outcome="error")
        raise
    record_download_request(channel="internal_share", outcome="allowed")
    return response


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
    try:
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
        response = await service.create_external_download_url(
            tenant_id=tenant_id,
            raw_token=request.raw_token,
            node_id=request.node_id,
            passcode=request.passcode,
            delivery_mode=request.delivery_mode,
            audit_context=build_audit_context(http_request),
        )
    except ApiError as exc:
        record_download_request(
            channel="external",
            outcome="denied" if exc.status_code < 500 else "error",
        )
        raise
    except Exception:
        record_download_request(channel="external", outcome="error")
        raise
    record_download_request(channel="external", outcome="allowed")
    return response
