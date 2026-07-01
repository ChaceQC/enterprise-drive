from __future__ import annotations

from uuid import UUID

from app.api.errors import ApiError
from app.core.config import Settings
from app.infrastructure.search.base import SearchHit, SearchIndexAdapter, SearchQuery
from app.modules.auth.models import User
from app.modules.org.service import OrgService
from app.modules.permission.actions import ACTION_READ_META
from app.modules.permission.service import PermissionService
from app.modules.search.acl import build_query_acl_token_set
from app.modules.search.cursor import decode_search_cursor, encode_search_cursor
from app.modules.search.repository import SearchRepository
from app.modules.search.schemas import SearchFileItem, SearchFilesResponse


class SearchService:
    def __init__(
        self,
        *,
        repository: SearchRepository,
        index_adapter: SearchIndexAdapter,
        permission_service: PermissionService,
        org_service: OrgService,
        settings: Settings,
    ) -> None:
        self.repository = repository
        self.index_adapter = index_adapter
        self.permission_service = permission_service
        self.org_service = org_service
        self.settings = settings

    async def search_files(
        self,
        *,
        current_user: User,
        query: str,
        limit: int,
        cursor: str | None,
    ) -> SearchFilesResponse:
        normalized_query = query.strip()
        if not normalized_query:
            raise ApiError("SEARCH_QUERY_EMPTY", "搜索关键词不能为空", status_code=422)
        decoded_cursor = decode_search_cursor(self.settings, cursor)
        if decoded_cursor is not None and decoded_cursor.query != normalized_query:
            raise ApiError("CURSOR_INVALID", "分页游标无效", status_code=400)
        token_set = build_query_acl_token_set(
            space_members=await self.permission_service.list_user_space_members(
                tenant_id=current_user.tenant_id,
                user_id=current_user.id,
            ),
            user_id=current_user.id,
            department_ids=await self.org_service.list_user_department_ids(
                tenant_id=current_user.tenant_id,
                user_id=current_user.id,
            ),
            group_ids=await self.org_service.list_user_group_ids(
                tenant_id=current_user.tenant_id,
                user_id=current_user.id,
            ),
        )
        result = await self.index_adapter.search_files(
            SearchQuery(
                tenant_id=str(current_user.tenant_id),
                query=normalized_query,
                acl_tokens=token_set.allow_tokens,
                deny_acl_tokens=token_set.deny_tokens,
                limit=limit + 1,
                search_after=decoded_cursor.sort_values if decoded_cursor else None,
            )
        )
        items: list[SearchFileItem] = []
        last_included_sort_values: list[object] | None = None
        for hit in result.hits:
            item = await self._visible_item(current_user=current_user, hit=hit)
            if item is not None:
                items.append(item)
                if len(items) <= limit:
                    last_included_sort_values = hit.sort_values
        page_items = items[:limit]
        next_cursor = None
        if len(items) > limit and last_included_sort_values:
            next_cursor = encode_search_cursor(
                self.settings,
                query=normalized_query,
                sort_values=last_included_sort_values,
            )
        elif len(result.hits) > limit:
            last_hit = result.hits[-1]
            if last_hit.sort_values:
                next_cursor = encode_search_cursor(
                    self.settings,
                    query=normalized_query,
                    sort_values=last_hit.sort_values,
                )
        return SearchFilesResponse(
            query=normalized_query,
            total=len(page_items),
            items=page_items,
            next_cursor=next_cursor,
        )

    async def _visible_item(
        self,
        *,
        current_user: User,
        hit: SearchHit,
    ) -> SearchFileItem | None:
        node_id = UUID(hit.node_id)
        space_id = UUID(hit.space_id)
        node_path_ids = await self.repository.get_node_path_ids(
            tenant_id=current_user.tenant_id,
            space_id=space_id,
            node_id=node_id,
        )
        if node_path_ids is None:
            return None
        allowed = await self.permission_service.can_access_node(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            space_id=space_id,
            action=ACTION_READ_META,
            node_path_ids=node_path_ids,
        )
        if not allowed:
            return None
        return SearchFileItem(
            node_id=node_id,
            space_id=space_id,
            name=hit.name,
            mime_type=hit.mime_type,
            size_bytes=hit.size_bytes,
            updated_at=hit.updated_at,
            score=hit.score,
            highlights=hit.highlights,
        )
