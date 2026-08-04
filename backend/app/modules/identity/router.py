from __future__ import annotations

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import build_audit_context, get_current_user
from app.api.errors import ApiError
from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.infrastructure.identity.ldap import Ldap3ProviderAdapter
from app.infrastructure.identity.oidc import HttpOidcProviderAdapter
from app.infrastructure.identity.secrets import EnvironmentSecretResolver
from app.modules.audit.repository import AuditRepository
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.auth.repository import AuthRepository
from app.modules.auth.router import (
    _clear_session_cookie,
    _read_csrf_header,
    _read_session_cookie,
    _set_session_cookie,
)
from app.modules.auth.service import AuthService
from app.modules.identity.ldap_service import LdapIdentityService
from app.modules.identity.oidc_service import OidcIdentityService
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.schemas import (
    LdapConnectionTestResponse,
    LdapSourceCreateRequest,
    LdapSourceListResponse,
    LdapSourceResponse,
    LdapSourceUpdateRequest,
    LdapSyncConflictListResponse,
    LdapSyncRequest,
    LdapSyncRunListResponse,
    LdapSyncRunResponse,
    OidcIdentityLinkListResponse,
    OidcIdentityUnlinkResponse,
    OidcLogoutResponse,
    OidcProviderCreateRequest,
    OidcProviderListResponse,
    OidcProviderResponse,
    OidcProviderTestResponse,
    OidcProviderUpdateRequest,
    OidcStartResponse,
    PublicOidcProviderListResponse,
)
from app.workers.identity_tasks import enqueue_ldap_sync

router = APIRouter()
admin_router = APIRouter()


def get_oidc_identity_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> OidcIdentityService:
    auth_repository = AuthRepository(session)
    return OidcIdentityService(
        repository=IdentityRepository(session),
        auth_service=AuthService(repository=auth_repository, settings=settings),
        provider_adapter=HttpOidcProviderAdapter(
            timeout_seconds=float(getattr(settings, "identity_http_timeout_seconds", 10.0))
        ),
        secret_resolver=EnvironmentSecretResolver(),
        settings=settings,
        audit_service=AuditService(repository=AuditRepository(session)),
    )


def get_ldap_identity_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LdapIdentityService:
    return LdapIdentityService(
        repository=IdentityRepository(session),
        provider_adapter=Ldap3ProviderAdapter(
            timeout_seconds=float(getattr(settings, "identity_http_timeout_seconds", 10.0))
        ),
        secret_resolver=EnvironmentSecretResolver(),
        settings=settings,
        audit_service=AuditService(repository=AuditRepository(session)),
    )


def get_ldap_sync_enqueuer() -> Callable[[UUID], None]:
    return enqueue_ldap_sync


@router.get("/oidc/providers", response_model=PublicOidcProviderListResponse)
async def list_public_oidc_providers(
    service: Annotated[OidcIdentityService, Depends(get_oidc_identity_service)],
    tenant_slug: Annotated[str, Query(min_length=1, max_length=64)] = "default",
) -> PublicOidcProviderListResponse:
    return await service.list_public_providers(tenant_slug=tenant_slug)


@router.get("/oidc/{provider_slug}/start", response_model=OidcStartResponse)
async def start_oidc_login(
    http_request: Request,
    provider_slug: str,
    service: Annotated[OidcIdentityService, Depends(get_oidc_identity_service)],
    tenant_slug: Annotated[str, Query(min_length=1, max_length=64)] = "default",
    redirect_path: Annotated[str, Query(min_length=1, max_length=1024)] = "/",
) -> OidcStartResponse:
    callback_uri = str(http_request.url_for("oidc_callback", provider_slug=provider_slug))
    return await service.start_login(
        tenant_slug=tenant_slug,
        provider_slug=provider_slug,
        redirect_uri=callback_uri,
        redirect_path=redirect_path,
        audit_context=build_audit_context(http_request),
    )


@router.post("/oidc/{provider_slug}/bind/start", response_model=OidcStartResponse)
async def start_oidc_binding(
    http_request: Request,
    provider_slug: str,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[OidcIdentityService, Depends(get_oidc_identity_service)],
    redirect_path: Annotated[str, Query(min_length=1, max_length=1024)] = "/account",
) -> OidcStartResponse:
    callback_uri = str(http_request.url_for("oidc_callback", provider_slug=provider_slug))
    return await service.start_binding(
        current_user=current_user,
        provider_slug=provider_slug,
        redirect_uri=callback_uri,
        redirect_path=redirect_path,
        audit_context=build_audit_context(http_request),
    )


@router.get(
    "/oidc/{provider_slug}/callback",
    name="oidc_callback",
    response_class=RedirectResponse,
)
async def oidc_callback(
    http_request: Request,
    provider_slug: str,
    state: Annotated[str, Query(min_length=16, max_length=1024)],
    service: Annotated[OidcIdentityService, Depends(get_oidc_identity_service)],
    code: Annotated[str | None, Query(min_length=1, max_length=4096)] = None,
    error: Annotated[str | None, Query(max_length=256)] = None,
) -> RedirectResponse:
    if error is not None:
        raise ApiError(
            "OIDC_PROVIDER_ERROR",
            "OIDC provider 拒绝了登录请求",
            status_code=400,
            details={"provider_error": error},
        )
    if code is None:
        raise ApiError("OIDC_CODE_MISSING", "OIDC 登录回调缺少授权码", status_code=400)
    result = await service.handle_callback(
        provider_slug=provider_slug,
        state=state,
        code=code,
        audit_context=build_audit_context(http_request),
    )
    response = RedirectResponse(url=result.redirect_path, status_code=status.HTTP_303_SEE_OTHER)
    if result.issued_session is not None:
        _set_session_cookie(
            response=response,
            request=http_request,
            session_token=result.issued_session.session_token,
            csrf_token=result.issued_session.csrf_token,
        )
    return response


@router.get("/identity-links", response_model=OidcIdentityLinkListResponse)
async def list_identity_links(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[OidcIdentityService, Depends(get_oidc_identity_service)],
) -> OidcIdentityLinkListResponse:
    return await service.list_links(current_user=current_user)


@router.delete(
    "/identity-links/{link_id}",
    response_model=OidcIdentityUnlinkResponse,
)
async def unlink_identity(
    http_request: Request,
    link_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[OidcIdentityService, Depends(get_oidc_identity_service)],
) -> OidcIdentityUnlinkResponse:
    return await service.unlink(
        current_user=current_user,
        link_id=link_id,
        audit_context=build_audit_context(http_request),
    )


@router.post("/oidc/{provider_slug}/logout", response_model=OidcLogoutResponse)
async def oidc_logout(
    http_request: Request,
    response: Response,
    provider_slug: str,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[OidcIdentityService, Depends(get_oidc_identity_service)],
) -> OidcLogoutResponse:
    result = await service.build_logout(
        current_user=current_user,
        provider_slug=provider_slug,
        post_logout_redirect_uri=str(http_request.base_url),
        audit_context=build_audit_context(http_request),
    )
    session_token = _read_session_cookie(http_request)
    assert session_token is not None
    await service.auth_service.logout(
        session_token=session_token,
        csrf_token=_read_csrf_header(http_request),
        audit_context=build_audit_context(http_request),
    )
    _clear_session_cookie(response=response, request=http_request)
    return result


@admin_router.get("/oidc/providers", response_model=OidcProviderListResponse)
async def list_oidc_providers(
    http_request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[OidcIdentityService, Depends(get_oidc_identity_service)],
) -> OidcProviderListResponse:
    return await service.list_providers(
        current_user=current_user,
        audit_context=build_audit_context(http_request),
    )


@admin_router.post(
    "/oidc/providers",
    response_model=OidcProviderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_oidc_provider(
    http_request: Request,
    request: OidcProviderCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[OidcIdentityService, Depends(get_oidc_identity_service)],
) -> OidcProviderResponse:
    return await service.create_provider(
        current_user=current_user,
        request=request,
        audit_context=build_audit_context(http_request),
    )


@admin_router.patch(
    "/oidc/providers/{provider_id}",
    response_model=OidcProviderResponse,
)
async def update_oidc_provider(
    http_request: Request,
    provider_id: UUID,
    request: OidcProviderUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[OidcIdentityService, Depends(get_oidc_identity_service)],
) -> OidcProviderResponse:
    return await service.update_provider(
        current_user=current_user,
        provider_id=provider_id,
        request=request,
        audit_context=build_audit_context(http_request),
    )


@admin_router.post(
    "/oidc/providers/{provider_id}/test",
    response_model=OidcProviderTestResponse,
)
async def test_oidc_provider(
    http_request: Request,
    provider_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[OidcIdentityService, Depends(get_oidc_identity_service)],
) -> OidcProviderTestResponse:
    return await service.test_provider(
        current_user=current_user,
        provider_id=provider_id,
        audit_context=build_audit_context(http_request),
    )


@admin_router.get("/ldap/sources", response_model=LdapSourceListResponse)
async def list_ldap_sources(
    http_request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[LdapIdentityService, Depends(get_ldap_identity_service)],
) -> LdapSourceListResponse:
    return await service.list_sources(
        current_user=current_user,
        audit_context=build_audit_context(http_request),
    )


@admin_router.post(
    "/ldap/sources",
    response_model=LdapSourceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_ldap_source(
    http_request: Request,
    request: LdapSourceCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[LdapIdentityService, Depends(get_ldap_identity_service)],
) -> LdapSourceResponse:
    return await service.create_source(
        current_user=current_user,
        request=request,
        audit_context=build_audit_context(http_request),
    )


@admin_router.patch(
    "/ldap/sources/{source_id}",
    response_model=LdapSourceResponse,
)
async def update_ldap_source(
    http_request: Request,
    source_id: UUID,
    request: LdapSourceUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[LdapIdentityService, Depends(get_ldap_identity_service)],
) -> LdapSourceResponse:
    return await service.update_source(
        current_user=current_user,
        source_id=source_id,
        request=request,
        audit_context=build_audit_context(http_request),
    )


@admin_router.post(
    "/ldap/sources/{source_id}/test",
    response_model=LdapConnectionTestResponse,
)
async def test_ldap_source(
    http_request: Request,
    source_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[LdapIdentityService, Depends(get_ldap_identity_service)],
) -> LdapConnectionTestResponse:
    return await service.test_source(
        current_user=current_user,
        source_id=source_id,
        audit_context=build_audit_context(http_request),
    )


@admin_router.post(
    "/ldap/sources/{source_id}/sync",
    response_model=LdapSyncRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_ldap_sync(
    http_request: Request,
    source_id: UUID,
    request: LdapSyncRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[LdapIdentityService, Depends(get_ldap_identity_service)],
    enqueue: Annotated[Callable[[UUID], None], Depends(get_ldap_sync_enqueuer)],
) -> LdapSyncRunResponse:
    run = await service.request_sync(
        current_user=current_user,
        source_id=source_id,
        request=request,
        audit_context=build_audit_context(http_request),
    )
    enqueue(run.id)
    return run


@admin_router.get("/ldap/runs", response_model=LdapSyncRunListResponse)
async def list_ldap_sync_runs(
    http_request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[LdapIdentityService, Depends(get_ldap_identity_service)],
    source_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> LdapSyncRunListResponse:
    return await service.list_runs(
        current_user=current_user,
        source_id=source_id,
        limit=limit,
        audit_context=build_audit_context(http_request),
    )


@admin_router.get(
    "/ldap/runs/{run_id}/conflicts",
    response_model=LdapSyncConflictListResponse,
)
async def list_ldap_sync_conflicts(
    http_request: Request,
    run_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[LdapIdentityService, Depends(get_ldap_identity_service)],
) -> LdapSyncConflictListResponse:
    return await service.list_conflicts(
        current_user=current_user,
        run_id=run_id,
        audit_context=build_audit_context(http_request),
    )
