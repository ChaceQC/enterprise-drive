from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import build_audit_context, get_current_user
from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.modules.admin.organization import AdminOrganizationService
from app.modules.admin.organization_repository import AdminOrganizationRepository
from app.modules.admin.organization_schemas import (
    AdminDepartmentCreateRequest,
    AdminDepartmentListResponse,
    AdminDepartmentResponse,
    AdminDepartmentUpdateRequest,
    AdminGroupCreateRequest,
    AdminGroupListResponse,
    AdminGroupResponse,
    AdminGroupUpdateRequest,
    AdminOrganizationMemberListResponse,
    AdminOrganizationMemberRemovalResponse,
    AdminOrganizationMemberRequest,
    AdminOrganizationMemberResponse,
    AdminUserCreateRequest,
    AdminUserListResponse,
    AdminUserPasswordResetRequest,
    AdminUserResponse,
    AdminUserUnlockRequest,
    AdminUserUpdateRequest,
    OrganizationStatus,
)
from app.modules.audit.repository import AuditRepository
from app.modules.audit.service import AuditService
from app.modules.auth.models import User

router = APIRouter()


def get_admin_organization_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AdminOrganizationService:
    return AdminOrganizationService(
        repository=AdminOrganizationRepository(session),
        audit_service=AuditService(repository=AuditRepository(session)),
        settings=settings,
    )


@router.get("/users", response_model=AdminUserListResponse)
async def list_admin_users(
    http_request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        AdminOrganizationService,
        Depends(get_admin_organization_service),
    ],
    is_active: Annotated[bool | None, Query()] = None,
    is_super_admin: Annotated[bool | None, Query()] = None,
    q: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
    cursor: Annotated[str | None, Query(min_length=1)] = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AdminUserListResponse:
    return await service.list_users(
        current_user=current_user,
        is_active=is_active,
        is_super_admin=is_super_admin,
        query=q,
        cursor=cursor,
        page_size=page_size,
        audit_context=build_audit_context(http_request),
    )


@router.post(
    "/users",
    response_model=AdminUserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_admin_user(
    http_request: Request,
    request: AdminUserCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        AdminOrganizationService,
        Depends(get_admin_organization_service),
    ],
) -> AdminUserResponse:
    return await service.create_user(
        current_user=current_user,
        request=request,
        audit_context=build_audit_context(http_request),
    )


@router.get("/users/{user_id}", response_model=AdminUserResponse)
async def get_admin_user(
    http_request: Request,
    user_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        AdminOrganizationService,
        Depends(get_admin_organization_service),
    ],
) -> AdminUserResponse:
    return await service.get_user(
        current_user=current_user,
        user_id=user_id,
        audit_context=build_audit_context(http_request),
    )


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
async def update_admin_user(
    http_request: Request,
    user_id: UUID,
    request: AdminUserUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        AdminOrganizationService,
        Depends(get_admin_organization_service),
    ],
) -> AdminUserResponse:
    return await service.update_user(
        current_user=current_user,
        user_id=user_id,
        request=request,
        audit_context=build_audit_context(http_request),
    )


@router.delete("/users/{user_id}", response_model=AdminUserResponse)
async def deactivate_admin_user(
    http_request: Request,
    user_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        AdminOrganizationService,
        Depends(get_admin_organization_service),
    ],
    expected_version: Annotated[int, Query(ge=1)],
) -> AdminUserResponse:
    return await service.deactivate_user(
        current_user=current_user,
        user_id=user_id,
        expected_version=expected_version,
        audit_context=build_audit_context(http_request),
    )


@router.post("/users/{user_id}/password-reset", response_model=AdminUserResponse)
async def reset_admin_user_password(
    http_request: Request,
    user_id: UUID,
    request: AdminUserPasswordResetRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        AdminOrganizationService,
        Depends(get_admin_organization_service),
    ],
) -> AdminUserResponse:
    return await service.reset_user_password(
        current_user=current_user,
        user_id=user_id,
        request=request,
        audit_context=build_audit_context(http_request),
    )


@router.post("/users/{user_id}/unlock", response_model=AdminUserResponse)
async def unlock_admin_user(
    http_request: Request,
    user_id: UUID,
    request: AdminUserUnlockRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        AdminOrganizationService,
        Depends(get_admin_organization_service),
    ],
) -> AdminUserResponse:
    return await service.unlock_user(
        current_user=current_user,
        user_id=user_id,
        request=request,
        audit_context=build_audit_context(http_request),
    )


@router.get("/departments", response_model=AdminDepartmentListResponse)
async def list_admin_departments(
    http_request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        AdminOrganizationService,
        Depends(get_admin_organization_service),
    ],
    organization_status: Annotated[OrganizationStatus | None, Query(alias="status")] = None,
    parent_id: Annotated[UUID | None, Query()] = None,
    root_only: Annotated[bool, Query()] = False,
    q: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
    cursor: Annotated[str | None, Query(min_length=1)] = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AdminDepartmentListResponse:
    return await service.list_departments(
        current_user=current_user,
        status=organization_status,
        parent_id=parent_id,
        root_only=root_only,
        query=q,
        cursor=cursor,
        page_size=page_size,
        audit_context=build_audit_context(http_request),
    )


@router.post(
    "/departments",
    response_model=AdminDepartmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_admin_department(
    http_request: Request,
    request: AdminDepartmentCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        AdminOrganizationService,
        Depends(get_admin_organization_service),
    ],
) -> AdminDepartmentResponse:
    return await service.create_department(
        current_user=current_user,
        request=request,
        audit_context=build_audit_context(http_request),
    )


@router.get("/departments/{department_id}", response_model=AdminDepartmentResponse)
async def get_admin_department(
    http_request: Request,
    department_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        AdminOrganizationService,
        Depends(get_admin_organization_service),
    ],
) -> AdminDepartmentResponse:
    return await service.get_department(
        current_user=current_user,
        department_id=department_id,
        audit_context=build_audit_context(http_request),
    )


@router.patch("/departments/{department_id}", response_model=AdminDepartmentResponse)
async def update_admin_department(
    http_request: Request,
    department_id: UUID,
    request: AdminDepartmentUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        AdminOrganizationService,
        Depends(get_admin_organization_service),
    ],
) -> AdminDepartmentResponse:
    return await service.update_department(
        current_user=current_user,
        department_id=department_id,
        request=request,
        audit_context=build_audit_context(http_request),
    )


@router.delete("/departments/{department_id}", response_model=AdminDepartmentResponse)
async def deactivate_admin_department(
    http_request: Request,
    department_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        AdminOrganizationService,
        Depends(get_admin_organization_service),
    ],
    expected_version: Annotated[int, Query(ge=1)],
) -> AdminDepartmentResponse:
    return await service.deactivate_department(
        current_user=current_user,
        department_id=department_id,
        expected_version=expected_version,
        audit_context=build_audit_context(http_request),
    )


@router.get(
    "/departments/{department_id}/members",
    response_model=AdminOrganizationMemberListResponse,
)
async def list_admin_department_members(
    http_request: Request,
    department_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        AdminOrganizationService,
        Depends(get_admin_organization_service),
    ],
    is_active: Annotated[bool | None, Query()] = None,
    q: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
    cursor: Annotated[str | None, Query(min_length=1)] = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AdminOrganizationMemberListResponse:
    return await service.list_department_members(
        current_user=current_user,
        department_id=department_id,
        is_active=is_active,
        query=q,
        cursor=cursor,
        page_size=page_size,
        audit_context=build_audit_context(http_request),
    )


@router.post(
    "/departments/{department_id}/members",
    response_model=AdminOrganizationMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_admin_department_member(
    http_request: Request,
    department_id: UUID,
    request: AdminOrganizationMemberRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        AdminOrganizationService,
        Depends(get_admin_organization_service),
    ],
) -> AdminOrganizationMemberResponse:
    return await service.add_department_member(
        current_user=current_user,
        department_id=department_id,
        user_id=request.user_id,
        expected_version=request.expected_version,
        audit_context=build_audit_context(http_request),
    )


@router.delete(
    "/departments/{department_id}/members/{user_id}",
    response_model=AdminOrganizationMemberRemovalResponse,
)
async def remove_admin_department_member(
    http_request: Request,
    department_id: UUID,
    user_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        AdminOrganizationService,
        Depends(get_admin_organization_service),
    ],
    expected_version: Annotated[int, Query(ge=1)],
) -> AdminOrganizationMemberRemovalResponse:
    return await service.remove_department_member(
        current_user=current_user,
        department_id=department_id,
        user_id=user_id,
        expected_version=expected_version,
        audit_context=build_audit_context(http_request),
    )


@router.get("/groups", response_model=AdminGroupListResponse)
async def list_admin_groups(
    http_request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        AdminOrganizationService,
        Depends(get_admin_organization_service),
    ],
    organization_status: Annotated[OrganizationStatus | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
    cursor: Annotated[str | None, Query(min_length=1)] = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AdminGroupListResponse:
    return await service.list_groups(
        current_user=current_user,
        status=organization_status,
        query=q,
        cursor=cursor,
        page_size=page_size,
        audit_context=build_audit_context(http_request),
    )


@router.post(
    "/groups",
    response_model=AdminGroupResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_admin_group(
    http_request: Request,
    request: AdminGroupCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        AdminOrganizationService,
        Depends(get_admin_organization_service),
    ],
) -> AdminGroupResponse:
    return await service.create_group(
        current_user=current_user,
        request=request,
        audit_context=build_audit_context(http_request),
    )


@router.get("/groups/{group_id}", response_model=AdminGroupResponse)
async def get_admin_group(
    http_request: Request,
    group_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        AdminOrganizationService,
        Depends(get_admin_organization_service),
    ],
) -> AdminGroupResponse:
    return await service.get_group(
        current_user=current_user,
        group_id=group_id,
        audit_context=build_audit_context(http_request),
    )


@router.patch("/groups/{group_id}", response_model=AdminGroupResponse)
async def update_admin_group(
    http_request: Request,
    group_id: UUID,
    request: AdminGroupUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        AdminOrganizationService,
        Depends(get_admin_organization_service),
    ],
) -> AdminGroupResponse:
    return await service.update_group(
        current_user=current_user,
        group_id=group_id,
        request=request,
        audit_context=build_audit_context(http_request),
    )


@router.delete("/groups/{group_id}", response_model=AdminGroupResponse)
async def deactivate_admin_group(
    http_request: Request,
    group_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        AdminOrganizationService,
        Depends(get_admin_organization_service),
    ],
    expected_version: Annotated[int, Query(ge=1)],
) -> AdminGroupResponse:
    return await service.deactivate_group(
        current_user=current_user,
        group_id=group_id,
        expected_version=expected_version,
        audit_context=build_audit_context(http_request),
    )


@router.get(
    "/groups/{group_id}/members",
    response_model=AdminOrganizationMemberListResponse,
)
async def list_admin_group_members(
    http_request: Request,
    group_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        AdminOrganizationService,
        Depends(get_admin_organization_service),
    ],
    is_active: Annotated[bool | None, Query()] = None,
    q: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
    cursor: Annotated[str | None, Query(min_length=1)] = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AdminOrganizationMemberListResponse:
    return await service.list_group_members(
        current_user=current_user,
        group_id=group_id,
        is_active=is_active,
        query=q,
        cursor=cursor,
        page_size=page_size,
        audit_context=build_audit_context(http_request),
    )


@router.post(
    "/groups/{group_id}/members",
    response_model=AdminOrganizationMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_admin_group_member(
    http_request: Request,
    group_id: UUID,
    request: AdminOrganizationMemberRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        AdminOrganizationService,
        Depends(get_admin_organization_service),
    ],
) -> AdminOrganizationMemberResponse:
    return await service.add_group_member(
        current_user=current_user,
        group_id=group_id,
        user_id=request.user_id,
        expected_version=request.expected_version,
        audit_context=build_audit_context(http_request),
    )


@router.delete(
    "/groups/{group_id}/members/{user_id}",
    response_model=AdminOrganizationMemberRemovalResponse,
)
async def remove_admin_group_member(
    http_request: Request,
    group_id: UUID,
    user_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[
        AdminOrganizationService,
        Depends(get_admin_organization_service),
    ],
    expected_version: Annotated[int, Query(ge=1)],
) -> AdminOrganizationMemberRemovalResponse:
    return await service.remove_group_member(
        current_user=current_user,
        group_id=group_id,
        user_id=user_id,
        expected_version=expected_version,
        audit_context=build_audit_context(http_request),
    )
