from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

TARGET_STATE_SCHEMA = "BE-029-target/1"
_RUN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,47}$")


@dataclass(frozen=True)
class TargetDataState:
    schema_version: str
    run_id: str
    tenant_slug: str
    username: str
    tenant_id: str
    actor_id: str
    opensearch_index: str
    search_term: str
    opensearch_target: int
    opensearch_completed: int
    audit_target: int
    audit_completed: int
    audit_deleted: int
    status: str
    created_at: str
    updated_at: str


def new_target_state(
    *,
    run_id: str,
    tenant_slug: str,
    username: str,
    tenant_id: UUID,
    actor_id: UUID,
    opensearch_target: int,
    audit_target: int,
    search_term: str,
) -> TargetDataState:
    normalized_run_id = validate_run_id(run_id)
    if opensearch_target < 0 or audit_target < 0:
        raise ValueError("目标数据量不能为负数")
    normalized_search_term = search_term.strip()
    if not normalized_search_term:
        raise ValueError("搜索基准词不能为空")
    now = datetime.now(UTC).isoformat()
    return TargetDataState(
        schema_version=TARGET_STATE_SCHEMA,
        run_id=normalized_run_id,
        tenant_slug=tenant_slug,
        username=username,
        tenant_id=str(tenant_id),
        actor_id=str(actor_id),
        opensearch_index=opensearch_index_for_run(normalized_run_id),
        search_term=normalized_search_term,
        opensearch_target=opensearch_target,
        opensearch_completed=0,
        audit_target=audit_target,
        audit_completed=0,
        audit_deleted=0,
        status="created",
        created_at=now,
        updated_at=now,
    )


def read_target_state(path: Path) -> TargetDataState:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("target state JSON 必须是对象")
    state = TargetDataState(**payload)
    if state.schema_version != TARGET_STATE_SCHEMA:
        raise ValueError(f"不支持的 target state schema: {state.schema_version}")
    validate_run_id(state.run_id)
    if state.opensearch_index != opensearch_index_for_run(state.run_id):
        raise ValueError("target state 中的 OpenSearch index 不符合安全命名规则")
    if state.audit_completed > state.audit_target:
        raise ValueError("target state 的 audit_completed 超过目标")
    if state.opensearch_completed > state.opensearch_target:
        raise ValueError("target state 的 opensearch_completed 超过目标")
    return state


def write_target_state(state: TargetDataState, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    updated = replace(state, updated_at=datetime.now(UTC).isoformat())
    temporary = path.with_name(f".{path.name}.{updated.run_id}.tmp")
    temporary.write_text(
        json.dumps(asdict(updated), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def update_target_state(state: TargetDataState, **changes: Any) -> TargetDataState:
    return replace(state, updated_at=datetime.now(UTC).isoformat(), **changes)


def validate_run_id(run_id: str) -> str:
    normalized = run_id.strip().lower()
    if _RUN_ID_RE.fullmatch(normalized) is None:
        raise ValueError("run_id 只能包含 3-48 位小写字母、数字和短横线")
    return normalized


def opensearch_index_for_run(run_id: str) -> str:
    return f"be029-{validate_run_id(run_id)}"


def audit_action_for_run(run_id: str) -> str:
    return f"performance.target.audit.{validate_run_id(run_id)}"


def deterministic_uuid(*, run_id: str, kind: str, sequence: int) -> UUID:
    if sequence < 0:
        raise ValueError("sequence 不能为负数")
    namespace = hashlib.blake2b(
        f"{validate_run_id(run_id)}:{kind}".encode(),
        digest_size=8,
    ).digest()
    value = (int.from_bytes(namespace, "big") << 64) | sequence
    return UUID(int=value, version=4)
