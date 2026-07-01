from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import build_audit_context, get_current_user
from app.db.session import get_db_session
from app.modules.audit.repository import AuditRepository
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.file.repository import FileRepository
from app.modules.org.repository import OrgRepository
from app.modules.org.service import OrgService
from app.modules.permission.repository import PermissionRepository
from app.modules.permission.service import PermissionService
from app.modules.share.repository import ShareRepository
from app.modules.share.schemas import (
    CreateShareRequest,
    CreateShareResponse,
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
