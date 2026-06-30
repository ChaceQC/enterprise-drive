from __future__ import annotations

from app.modules.permission.actions import PERMISSION_ACTIONS
from app.modules.permission.constants import ACL_EFFECTS


def validate_acl_entry(*, effect: str, actions: list[str]) -> None:
    if effect not in ACL_EFFECTS:
        raise ValueError(f"unsupported acl effect: {effect}")
    if not actions:
        raise ValueError("acl actions cannot be empty")
    unsupported_actions = set(actions) - PERMISSION_ACTIONS
    if unsupported_actions:
        raise ValueError(f"unsupported acl actions: {sorted(unsupported_actions)}")
