from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import build_audit_context, get_current_user
from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.modules.audit.repository import AuditRepository
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.auth.repository import AuthRepository
from app.modules.auth.service import AuthService
from app.modules.file.acl import FileAclService
from app.modules.file.repository import FileRepository
from app.modules.org.repository import OrgRepository
from app.modules.org.service import OrgService
from app.modules.permission.repository import PermissionRepository
from app.modules.permission.schemas import (
    AclEntryListResponse,
    AclEntryResponse,
    CreateAclEntryRequest,
    RemoveAclEntryResponse,
    UpdateAclEntryRequest,
)
from app.modules.permission.service import PermissionService
from app.modules.space.repository import SpaceRepository

router = APIRouter()


def get_file_acl_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> FileAclService:
    permission_repository = PermissionRepository(session)
    org_service = OrgService(repository=OrgRepository(session))
    return FileAclService(
        file_repository=FileRepository(session),
        permission_repository=permission_repository,
        permission_service=PermissionService(
            repository=permission_repository,
            org_service=org_service,
        ),
        space_repository=SpaceRepository(session),
        auth_service=AuthService(repository=AuthRepository(session), settings=settings),
        org_service=org_service,
        audit_service=AuditService(repository=AuditRepository(session)),
    )


@router.get("/{node_id}/acl", response_model=AclEntryListResponse)
async def list_node_acl_entries(
    node_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[FileAclService, Depends(get_file_acl_service)],
) -> AclEntryListResponse:
    return await service.list_acl_entries(current_user=current_user, node_id=node_id)


@router.post(
    "/{node_id}/acl",
    response_model=AclEntryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_node_acl_entry(
    http_request: Request,
    node_id: UUID,
    request: CreateAclEntryRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[FileAclService, Depends(get_file_acl_service)],
) -> AclEntryResponse:
    return await service.create_acl_entry(
        current_user=current_user,
        node_id=node_id,
        subject_type=request.subject_type,
        subject_id=request.subject_id,
        effect=request.effect,
        actions=list(request.actions),
        inherit=request.inherit,
        audit_context=build_audit_context(http_request),
    )


@router.patch("/{node_id}/acl/{entry_id}", response_model=AclEntryResponse)
async def update_node_acl_entry(
    http_request: Request,
    node_id: UUID,
    entry_id: UUID,
    request: UpdateAclEntryRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[FileAclService, Depends(get_file_acl_service)],
) -> AclEntryResponse:
    return await service.update_acl_entry(
        current_user=current_user,
        node_id=node_id,
        entry_id=entry_id,
        effect=request.effect,
        actions=list(request.actions),
        inherit=request.inherit,
        audit_context=build_audit_context(http_request),
    )


@router.delete("/{node_id}/acl/{entry_id}", response_model=RemoveAclEntryResponse)
async def remove_node_acl_entry(
    http_request: Request,
    node_id: UUID,
    entry_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[FileAclService, Depends(get_file_acl_service)],
) -> RemoveAclEntryResponse:
    return await service.remove_acl_entry(
        current_user=current_user,
        node_id=node_id,
        entry_id=entry_id,
        audit_context=build_audit_context(http_request),
    )
