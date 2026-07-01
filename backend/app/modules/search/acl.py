from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.modules.permission.actions import (
    ACTION_DOWNLOAD,
    ACTION_LIST,
    ACTION_PREVIEW,
    ACTION_READ_META,
)
from app.modules.permission.constants import (
    ACL_EFFECT_ALLOW,
    ACL_EFFECT_DENY,
    ACL_SUBJECT_DEPARTMENT,
    ACL_SUBJECT_GROUP,
    ACL_SUBJECT_USER,
)
from app.modules.permission.models import AclEntry, SpaceMember

SEARCH_ACL_TOKEN_SPACE_PREFIX = "space"
SEARCH_VISIBLE_ACTIONS = frozenset(
    {
        ACTION_DOWNLOAD,
        ACTION_LIST,
        ACTION_PREVIEW,
        ACTION_READ_META,
    }
)


@dataclass(frozen=True)
class SearchAclTokenSet:
    allow_tokens: list[str]
    deny_tokens: list[str]


def user_acl_token(user_id: UUID) -> str:
    return f"{ACL_SUBJECT_USER}:{user_id}"


def department_acl_token(department_id: UUID) -> str:
    return f"{ACL_SUBJECT_DEPARTMENT}:{department_id}"


def group_acl_token(group_id: UUID) -> str:
    return f"{ACL_SUBJECT_GROUP}:{group_id}"


def space_role_acl_token(*, space_id: UUID, role: str) -> str:
    return f"{SEARCH_ACL_TOKEN_SPACE_PREFIX}:{space_id}:role:{role}"


def acl_entry_token(entry: AclEntry) -> str | None:
    if entry.subject_type == ACL_SUBJECT_USER:
        return user_acl_token(entry.subject_id)
    if entry.subject_type == ACL_SUBJECT_DEPARTMENT:
        return department_acl_token(entry.subject_id)
    if entry.subject_type == ACL_SUBJECT_GROUP:
        return group_acl_token(entry.subject_id)
    return None


def build_index_acl_tokens(
    *,
    space_members: list[SpaceMember],
    acl_entries: list[AclEntry],
) -> list[str]:
    return build_index_acl_token_set(
        space_members=space_members,
        acl_entries=acl_entries,
    ).allow_tokens


def build_index_acl_token_set(
    *,
    space_members: list[SpaceMember],
    acl_entries: list[AclEntry],
) -> SearchAclTokenSet:
    allow_tokens: set[str] = set()
    allow_tokens.update(
        space_role_acl_token(space_id=member.space_id, role=member.role) for member in space_members
    )
    deny_tokens: set[str] = set()
    for entry in acl_entries:
        if entry.effect != ACL_EFFECT_DENY or not _is_search_visible_acl(entry):
            continue
        token = acl_entry_token(entry)
        if token is not None:
            deny_tokens.add(token)
    for entry in acl_entries:
        if entry.effect != ACL_EFFECT_ALLOW or not _is_search_visible_acl(entry):
            continue
        token = acl_entry_token(entry)
        if token is not None and token not in deny_tokens:
            allow_tokens.add(token)
    return SearchAclTokenSet(allow_tokens=sorted(allow_tokens), deny_tokens=sorted(deny_tokens))


def build_query_acl_token_set(
    *,
    space_members: list[SpaceMember],
    user_id: UUID,
    department_ids: list[UUID],
    group_ids: list[UUID],
) -> SearchAclTokenSet:
    subject_tokens = {user_acl_token(user_id)}
    subject_tokens.update(department_acl_token(department_id) for department_id in department_ids)
    subject_tokens.update(group_acl_token(group_id) for group_id in group_ids)

    allow_tokens = set(subject_tokens)
    allow_tokens.update(
        space_role_acl_token(space_id=member.space_id, role=member.role) for member in space_members
    )
    return SearchAclTokenSet(allow_tokens=sorted(allow_tokens), deny_tokens=sorted(subject_tokens))


def _is_search_visible_acl(entry: AclEntry) -> bool:
    return any(action in SEARCH_VISIBLE_ACTIONS for action in entry.actions)
