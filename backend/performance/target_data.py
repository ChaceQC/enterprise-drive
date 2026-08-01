from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import Settings
from performance.target_audit import (
    connect_database,
    count_target_audit_rows,
    delete_target_audit_rows,
    generate_audit_rows,
    resolve_identity,
)
from performance.target_opensearch import (
    build_opensearch_client,
    count_target_documents,
    delete_target_index,
    generate_opensearch_documents,
)
from performance.target_state import (
    TargetDataState,
    new_target_state,
    read_target_state,
    update_target_state,
    validate_run_id,
    write_target_state,
)

_LARGE_TARGET_THRESHOLD = 100_000


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="准备、检查和清理 BE-029 target 数据")
    parser.add_argument("--state", type=Path, required=True, help="target state JSON 路径")
    parser.add_argument(
        "--database-url",
        default=os.getenv("DRIVE_DATABASE_URL") or Settings().database_url,
    )
    parser.add_argument(
        "--opensearch-url",
        default=os.getenv("DRIVE_OPENSEARCH_URL") or Settings().opensearch_url,
    )
    parser.add_argument("--tenant-slug", default=os.getenv("PERF_TENANT_SLUG", "default"))
    parser.add_argument("--username", default=os.getenv("PERF_USERNAME", "admin"))
    parser.add_argument("--run-id")
    parser.add_argument("--opensearch-docs", type=int, default=1_000_000)
    parser.add_argument("--audit-rows", type=int, default=10_000_000)
    parser.add_argument("--search-term", default="be029-anchor")
    parser.add_argument("--opensearch-batch-size", type=int, default=1_000)
    parser.add_argument("--audit-batch-size", type=int, default=10_000)
    parser.add_argument("--max-batches", type=int, default=0)
    parser.add_argument("--throttle-seconds", type=float, default=0.05)
    parser.add_argument(
        "--confirm-large-target",
        action="store_true",
        help="确认允许生成大于 100,000 条的目标数据",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare", help="分阶段生成或恢复 target 数据")
    prepare.add_argument("--phase", choices=("opensearch", "audit", "all"), default="all")
    subparsers.add_parser("status", help="读取 state 并查询真实数据量")
    cleanup = subparsers.add_parser("cleanup", help="只清理当前 state 所属数据")
    cleanup.add_argument("--confirm-run-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    state_path = args.state.resolve()
    if args.command == "prepare":
        result = asyncio.run(_prepare(args, state_path))
    elif args.command == "status":
        result = asyncio.run(_status(args, state_path))
    else:
        result = asyncio.run(_cleanup(args, state_path))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


async def _prepare(args: argparse.Namespace, state_path: Path) -> dict[str, Any]:
    if state_path.exists():
        state = read_target_state(state_path)
    else:
        run_id = args.run_id or _default_run_id()
        _validate_large_target(
            opensearch_docs=args.opensearch_docs,
            audit_rows=args.audit_rows,
            confirmed=args.confirm_large_target,
        )
        async with await connect_database(args.database_url) as connection:
            tenant_id, actor_id = await resolve_identity(
                connection,
                tenant_slug=args.tenant_slug,
                username=args.username,
            )
        state = new_target_state(
            run_id=run_id,
            tenant_slug=args.tenant_slug,
            username=args.username,
            tenant_id=tenant_id,
            actor_id=actor_id,
            opensearch_target=args.opensearch_docs,
            audit_target=args.audit_rows,
            search_term=args.search_term,
        )
        write_target_state(state, state_path)

    if args.run_id is not None and state.run_id != validate_run_id(args.run_id):
        raise ValueError("传入的 --run-id 与现有 state 不一致")
    if args.command != "prepare":
        raise AssertionError("unreachable")

    phase = args.phase
    opensearch_result: dict[str, Any] | None = None
    audit_result: dict[str, Any] | None = None
    if phase in {"opensearch", "all"}:
        client = build_opensearch_client(args.opensearch_url)
        state, opensearch_generation = generate_opensearch_documents(
            client=client,
            state=state,
            state_path=state_path,
            batch_size=args.opensearch_batch_size,
            max_batches=args.max_batches,
            throttle_seconds=args.throttle_seconds,
        )
        opensearch_result = asdict(opensearch_generation)
    if phase in {"audit", "all"}:
        async with await connect_database(args.database_url) as connection:
            state, audit_generation = await generate_audit_rows(
                connection=connection,
                state=state,
                state_path=state_path,
                batch_size=args.audit_batch_size,
                max_batches=args.max_batches,
                throttle_seconds=args.throttle_seconds,
            )
        audit_result = asdict(audit_generation)
    state = _set_ready_if_complete(state)
    write_target_state(state, state_path)
    return {
        "command": "prepare",
        "state": asdict(state),
        "opensearch": opensearch_result,
        "audit": audit_result,
    }


async def _status(args: argparse.Namespace, state_path: Path) -> dict[str, Any]:
    state = read_target_state(state_path)
    client = build_opensearch_client(args.opensearch_url)
    async with await connect_database(args.database_url) as connection:
        audit_count = await count_target_audit_rows(connection=connection, state=state)
    opensearch_count = count_target_documents(client=client, state=state)
    return {
        "command": "status",
        "state": asdict(state),
        "observed": {
            "opensearch_count": opensearch_count,
            "audit_count": audit_count,
        },
    }


async def _cleanup(args: argparse.Namespace, state_path: Path) -> dict[str, Any]:
    state = read_target_state(state_path)
    if validate_run_id(args.confirm_run_id) != state.run_id:
        raise ValueError("--confirm-run-id 与 state.run_id 不一致")
    client = build_opensearch_client(args.opensearch_url)
    index_deleted = delete_target_index(client=client, state=state)
    async with await connect_database(args.database_url) as connection:
        state, deleted, audit_completed = await delete_target_audit_rows(
            connection=connection,
            state=state,
            state_path=state_path,
            batch_size=args.audit_batch_size,
            max_batches=args.max_batches,
            throttle_seconds=args.throttle_seconds,
        )
    state = update_target_state(
        state,
        status="cleaned" if audit_completed else "cleanup-paused",
    )
    write_target_state(state, state_path)
    return {
        "command": "cleanup",
        "state": asdict(state),
        "index_deleted": index_deleted,
        "audit_deleted": deleted,
        "audit_cleanup_completed": audit_completed,
    }


def _set_ready_if_complete(state: TargetDataState) -> TargetDataState:
    if (
        state.opensearch_completed >= state.opensearch_target
        and state.audit_completed >= state.audit_target
    ):
        return update_target_state(state, status="ready")
    return state


def _validate_large_target(*, opensearch_docs: int, audit_rows: int, confirmed: bool) -> None:
    if opensearch_docs < 0 or audit_rows < 0:
        raise ValueError("目标数据量不能为负数")
    if max(opensearch_docs, audit_rows) >= _LARGE_TARGET_THRESHOLD and not confirmed:
        raise ValueError(
            "大规模 target 需要显式 --confirm-large-target；建议先用 --max-batches 分阶段运行"
        )


def _default_run_id() -> str:
    return "be029-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


if __name__ == "__main__":
    raise SystemExit(main())
