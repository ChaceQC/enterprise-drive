from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from app.api.errors import ApiError
from app.core.config import Settings
from app.core.pagination import decode_page_cursor, encode_page_cursor
from app.modules.audit.schemas import AuditContext, AuditEvent
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.file.repository import FileRepository
from app.modules.space.models import Space
from app.modules.space.repository import SpaceRepository
from app.modules.space.schemas import CreateSpaceResponse, SpaceListResponse, SpaceResponse


class SpaceService:
    def __init__(
        self,
        *,
        repository: SpaceRepository,
        file_repository: FileRepository,
        settings: Settings,
        audit_service: AuditService | None = None,
    ) -> None:
        self.repository = repository
        self.file_repository = file_repository
        self.settings = settings
        self.audit_service = audit_service

    async def create_space(
        self,
        *,
        current_user: User,
        slug: str,
        name: str,
        space_type: str,
        audit_context: AuditContext | None = None,
    ) -> CreateSpaceResponse:
        normalized_slug = slug.lower()
        display_name = name.strip()
        if not display_name:
            raise ApiError("SPACE_NAME_INVALID", "空间名称不能为空", status_code=422)

        existing_space = await self.repository.get_space_by_slug(
            tenant_id=current_user.tenant_id,
            slug=normalized_slug,
        )
        if existing_space is not None:
            raise ApiError("SPACE_SLUG_EXISTS", "空间标识已存在", status_code=409)

        try:
            space = await self.repository.create_space(
                tenant_id=current_user.tenant_id,
                owner_id=current_user.id,
                slug=normalized_slug,
                name=display_name,
                space_type=space_type,
            )
            root_node = await self.file_repository.create_node(
                tenant_id=current_user.tenant_id,
                space_id=space.id,
                parent_id=None,
                owner_id=current_user.id,
                node_type="folder",
                name="root",
                normalized_name="root",
            )
            await self._record_created(
                current_user=current_user,
                space=space,
                audit_context=audit_context,
            )
            await self.repository.commit()
        except IntegrityError as exc:
            await self.repository.rollback()
            raise ApiError("SPACE_SLUG_EXISTS", "空间标识已存在", status_code=409) from exc

        return CreateSpaceResponse(
            **SpaceResponse.model_validate(space).model_dump(),
            root_node_id=root_node.id,
        )

    async def list_spaces(
        self,
        *,
        current_user: User,
        cursor: str | None,
        page_size: int,
    ) -> SpaceListResponse:
        decoded_cursor = decode_page_cursor(self.settings, cursor)
        spaces = await self.repository.list_owned_active_spaces(
            tenant_id=current_user.tenant_id,
            owner_id=current_user.id,
            limit=page_size + 1,
            cursor=decoded_cursor,
        )
        items = spaces[:page_size]
        next_cursor = None
        if len(spaces) > page_size and items:
            last_item = items[-1]
            next_cursor = encode_page_cursor(
                self.settings,
                created_at=last_item.created_at,
                item_id=last_item.id,
            )
        return SpaceListResponse(
            items=[SpaceResponse.model_validate(space) for space in items],
            next_cursor=next_cursor,
        )

    async def _record_created(
        self,
        *,
        current_user: User,
        space: Space,
        audit_context: AuditContext | None,
    ) -> None:
        if self.audit_service is None:
            return
        await self.audit_service.record(
            event=AuditEvent(
                tenant_id=current_user.tenant_id,
                actor_id=current_user.id,
                action="space.created",
                resource_type="space",
                resource_id=space.id,
                result="allowed",
                metadata={"slug": space.slug, "space_type": space.space_type},
            ),
            context=audit_context or AuditContext(),
        )
