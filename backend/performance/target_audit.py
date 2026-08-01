from __future__ import annotations

import json
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from performance.target_state import (
    TargetDataState,
    audit_action_for_run,
    deterministic_uuid,
    update_target_state,
    write_target_state,
)

_INSERT_COUNT_RE = re.compile(r"^INSERT \d+ (\d+)$")
_DELETE_COUNT_RE = re.compile(r"^DELETE (\d+)$")
_STAGE_TABLE = "be029_audit_stage"


@dataclass(frozen=True)
class AuditGenerationResult:
    attempted: int
    inserted: int
    total_count: int
    elapsed_seconds: float
    completed: bool


async def connect_database(database_url: str) -> asyncpg.Connection:
    return await asyncpg.connect(_normalize_database_url(database_url), command_timeout=180)


@asynccontextmanager
async def database_connection(database_url: str) -> AsyncIterator[asyncpg.Connection]:
    connection = await connect_database(database_url)
    try:
        yield connection
    finally:
        await connection.close()


async def resolve_identity(
    connection: asyncpg.Connection,
    *,
    tenant_slug: str,
    username: str,
) -> tuple[UUID, UUID]:
    row = await connection.fetchrow(
        """
        SELECT t.id AS tenant_id, u.id AS actor_id
        FROM tenants AS t
        JOIN users AS u ON u.tenant_id = t.id
        WHERE t.slug = $1 AND u.username = $2
        """,
        tenant_slug,
        username,
    )
    if row is None:
        raise ValueError(f"找不到 tenant/user: {tenant_slug}/{username}")
    return UUID(str(row["tenant_id"])), UUID(str(row["actor_id"]))


async def generate_audit_rows(
    *,
    connection: asyncpg.Connection,
    state: TargetDataState,
    state_path: Path,
    batch_size: int,
    max_batches: int,
    throttle_seconds: float,
) -> tuple[TargetDataState, AuditGenerationResult]:
    if batch_size <= 0:
        raise ValueError("审计 batch_size 必须大于 0")
    if max_batches < 0:
        raise ValueError("max_batches 不能为负数")
    if throttle_seconds < 0:
        raise ValueError("throttle_seconds 不能为负数")

    await _create_stage_table(connection)
    started = time.perf_counter()
    attempted = 0
    inserted = 0
    batches = 0
    current = update_target_state(state, status="audit-generating")
    write_target_state(current, state_path)

    while current.audit_completed < current.audit_target:
        if max_batches and batches >= max_batches:
            break
        start = current.audit_completed
        stop = min(start + batch_size, current.audit_target)
        records = _audit_records(state=current, start=start, stop=stop)
        async with connection.transaction():
            await connection.execute(f"TRUNCATE TABLE {_STAGE_TABLE}")
            await connection.copy_records_to_table(
                _STAGE_TABLE,
                records=records,
                columns=(
                    "id",
                    "tenant_id",
                    "actor_id",
                    "actor_type",
                    "action",
                    "resource_type",
                    "resource_id",
                    "result",
                    "risk_level",
                    "request_id",
                    "ip",
                    "user_agent",
                    "metadata_json",
                    "created_at",
                ),
            )
            command = await connection.execute(
                f"""
                INSERT INTO audit_logs (
                    id, tenant_id, actor_id, actor_type, action, resource_type,
                    resource_id, result, risk_level, request_id, ip, user_agent,
                    metadata_json, created_at
                )
                SELECT id, tenant_id, actor_id, actor_type, action, resource_type,
                       resource_id, result, risk_level, request_id, ip, user_agent,
                       metadata_json, created_at
                FROM {_STAGE_TABLE}
                ON CONFLICT (id) DO NOTHING
                """
            )
        inserted += _parse_count(command, _INSERT_COUNT_RE)
        attempted += stop - start
        batches += 1
        current = update_target_state(current, audit_completed=stop)
        write_target_state(current, state_path)
        if throttle_seconds:
            await _sleep(throttle_seconds)

    total_count = await count_target_audit_rows(connection=connection, state=current)
    completed = current.audit_completed >= current.audit_target
    current = update_target_state(current, status="ready" if completed else "audit-paused")
    write_target_state(current, state_path)
    return current, AuditGenerationResult(
        attempted=attempted,
        inserted=inserted,
        total_count=total_count,
        elapsed_seconds=round(time.perf_counter() - started, 6),
        completed=completed,
    )


async def count_target_audit_rows(
    *,
    connection: asyncpg.Connection,
    state: TargetDataState,
) -> int:
    value = await connection.fetchval(
        "SELECT count(*) FROM audit_logs WHERE tenant_id = $1 AND action = $2",
        UUID(state.tenant_id),
        audit_action_for_run(state.run_id),
    )
    return int(value or 0)


async def delete_target_audit_rows(
    *,
    connection: asyncpg.Connection,
    state: TargetDataState,
    state_path: Path,
    batch_size: int,
    max_batches: int,
    throttle_seconds: float,
) -> tuple[TargetDataState, int, bool]:
    if batch_size <= 0:
        raise ValueError("清理 batch_size 必须大于 0")
    if max_batches < 0:
        raise ValueError("max_batches 不能为负数")
    if throttle_seconds < 0:
        raise ValueError("throttle_seconds 不能为负数")

    deleted = 0
    batches = 0
    current = update_target_state(state, status="audit-cleaning")
    write_target_state(current, state_path)
    while True:
        if max_batches and batches >= max_batches:
            break
        async with connection.transaction():
            command = await connection.execute(
                """
                DELETE FROM audit_logs
                WHERE id IN (
                    SELECT id
                    FROM audit_logs
                    WHERE tenant_id = $1 AND action = $2
                    LIMIT $3
                )
                """,
                UUID(current.tenant_id),
                audit_action_for_run(current.run_id),
                batch_size,
            )
        removed = _parse_count(command, _DELETE_COUNT_RE)
        deleted += removed
        batches += 1
        current = update_target_state(current, audit_deleted=current.audit_deleted + removed)
        write_target_state(current, state_path)
        if removed == 0:
            break
        if throttle_seconds:
            await _sleep(throttle_seconds)
    remaining = await count_target_audit_rows(connection=connection, state=current)
    completed = remaining == 0
    current = update_target_state(current, status="cleaned" if completed else "cleanup-paused")
    write_target_state(current, state_path)
    return current, deleted, completed


async def _create_stage_table(connection: asyncpg.Connection) -> None:
    await connection.execute(
        f"""
        CREATE TEMP TABLE IF NOT EXISTS {_STAGE_TABLE} (
            id uuid NOT NULL,
            tenant_id uuid NOT NULL,
            actor_id uuid,
            actor_type varchar(32) NOT NULL,
            action varchar(128) NOT NULL,
            resource_type varchar(64) NOT NULL,
            resource_id uuid,
            result varchar(32) NOT NULL,
            risk_level varchar(32) NOT NULL,
            request_id varchar(128),
            ip varchar(64),
            user_agent text,
            metadata_json jsonb NOT NULL,
            created_at timestamptz NOT NULL
        ) ON COMMIT PRESERVE ROWS
        """
    )


def _audit_records(
    *,
    state: TargetDataState,
    start: int,
    stop: int,
) -> list[tuple[Any, ...]]:
    action = audit_action_for_run(state.run_id)
    tenant_id = UUID(state.tenant_id)
    actor_id = UUID(state.actor_id)
    base_time = datetime.fromisoformat(state.created_at)
    records: list[tuple[Any, ...]] = []
    for sequence in range(start, stop):
        resource_id = deterministic_uuid(
            run_id=state.run_id,
            kind="audit-resource",
            sequence=sequence,
        )
        created_at = base_time - timedelta(seconds=sequence % (365 * 24 * 60 * 60))
        records.append(
            (
                deterministic_uuid(run_id=state.run_id, kind="audit", sequence=sequence),
                tenant_id,
                actor_id,
                "user",
                action,
                "file",
                resource_id,
                ("allowed", "denied", "error")[sequence % 3],
                ("low", "medium", "high")[sequence % 3],
                f"be029:{state.run_id}:{sequence:012d}",
                f"192.0.2.{(sequence % 250) + 1}",
                "be029-target-generator/1",
                json.dumps(
                    {
                        "benchmark_run_id": state.run_id,
                        "sequence": sequence,
                        "synthetic": True,
                    },
                    separators=(",", ":"),
                ),
                created_at,
            )
        )
    return records


def _parse_count(command: str, pattern: re.Pattern[str]) -> int:
    match = pattern.fullmatch(command.strip())
    if match is None:
        raise RuntimeError(f"无法解析 PostgreSQL 命令结果: {command}")
    return int(match.group(1))


async def _sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)


def _normalize_database_url(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
