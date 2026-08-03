from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from performance.complete_queue import (
    PreparedCompleteQueue,
    cleanup_complete_queue,
    prepare_complete_queue,
    write_cleanup_summary,
    write_complete_queue,
)
from performance.environment import collect_environment_snapshot
from performance.fixture import (
    BenchmarkFixture,
    cleanup_fixture,
    prepare_fixture,
    read_fixture,
    write_fixture,
)
from performance.profiles import get_profile
from performance.report import write_report


@dataclass(frozen=True)
class PreparedBenchmarkSession:
    session_token: str
    csrf_token: str


def _write_report(**kwargs: Any) -> dict[str, Any]:
    return write_report(**kwargs)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="运行 BE-029 Locust 性能基准")
    parser.add_argument("--base-url", default=os.getenv("PERF_BASE_URL", "http://localhost:18080"))
    parser.add_argument("--tenant-slug", default=os.getenv("PERF_TENANT_SLUG", "default"))
    parser.add_argument("--username", default=os.getenv("PERF_USERNAME", "admin"))
    parser.add_argument("--password", default=os.getenv("PERF_PASSWORD"))
    parser.add_argument("--space-id")
    parser.add_argument("--parent-id")
    parser.add_argument("--create-space", action="store_true")
    parser.add_argument("--profile", choices=("smoke", "baseline", "target"), default="smoke")
    parser.add_argument(
        "--scenario",
        choices=(
            "mixed",
            "login",
            "auth_me",
            "list",
            "search",
            "upload_init",
            "upload_complete",
            "audit",
        ),
    )
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--folder-count", type=int)
    parser.add_argument("--users", type=int)
    parser.add_argument("--spawn-rate", type=float)
    parser.add_argument("--run-time")
    parser.add_argument(
        "--warmup-seconds",
        type=float,
        default=float(os.getenv("PERF_WARMUP_SECONDS", "0")),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--keep-fixture", action="store_true")
    parser.add_argument("--no-prepare", action="store_true")
    parser.add_argument("--complete-ready-count", type=int)
    parser.add_argument(
        "--complete-concurrency",
        type=int,
        default=int(os.getenv("PERF_COMPLETE_CONCURRENCY", "24")),
    )
    parser.add_argument(
        "--complete-prepare-concurrency",
        type=int,
        default=int(os.getenv("PERF_COMPLETE_PREPARE_CONCURRENCY", "24")),
    )
    parser.add_argument(
        "--complete-cleanup-concurrency",
        type=int,
        default=int(os.getenv("PERF_COMPLETE_CLEANUP_CONCURRENCY", "24")),
    )
    parser.add_argument("--keep-complete-queue", action="store_true")
    parser.add_argument("--docker-compose-project")
    parser.add_argument("--target-state", type=Path)
    parser.add_argument("--postgres-user", default=os.getenv("POSTGRES_USER", "drive"))
    parser.add_argument(
        "--postgres-database",
        default=os.getenv("POSTGRES_DB", "enterprise_drive"),
    )
    return parser


def _run_locust(
    command: list[str],
    *,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    for output in (completed.stdout, completed.stderr):
        if output:
            print(output, end="" if output.endswith("\n") else "\n")
    return completed


def _prepare_benchmark_session(
    *,
    base_url: str,
    tenant_slug: str,
    username: str,
    password: str,
    timeout_seconds: float = 30.0,
) -> PreparedBenchmarkSession:
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout_seconds) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={
                "tenant_slug": tenant_slug,
                "username": username,
                "password": password,
            },
        )
        if response.status_code != 200:
            raise RuntimeError(f"性能基准预登录失败: status={response.status_code}")
        session_token = response.cookies.get("drive_session") or client.cookies.get("drive_session")
        csrf_token = response.cookies.get("drive_csrf") or client.cookies.get("drive_csrf")
    if not session_token or not csrf_token:
        raise RuntimeError("性能基准预登录响应缺少 session 或 CSRF cookie")
    return PreparedBenchmarkSession(
        session_token=str(session_token),
        csrf_token=str(csrf_token),
    )


def _logout_benchmark_session(
    *,
    base_url: str,
    session: PreparedBenchmarkSession,
    timeout_seconds: float = 30.0,
) -> None:
    with httpx.Client(
        base_url=base_url.rstrip("/"),
        timeout=timeout_seconds,
        cookies={
            "drive_session": session.session_token,
            "drive_csrf": session.csrf_token,
        },
    ) as client:
        response = client.post(
            "/api/v1/auth/logout",
            headers={"X-CSRF-Token": session.csrf_token},
        )
    if response.status_code != 200:
        print(f"性能基准预登录会话清理失败: status={response.status_code}")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if not args.password:
        raise SystemExit("请通过 --password 或 PERF_PASSWORD 提供性能测试账号密码")
    profile = get_profile(args.profile)
    scenario = args.scenario or profile.default_scenario
    if args.profile == "target" and not args.docker_compose_project:
        raise SystemExit("--profile target 必须提供 --docker-compose-project")
    if args.profile == "target" and scenario in {"search", "audit"} and args.target_state is None:
        raise SystemExit("target 搜索/审计场景必须提供 --target-state")
    if args.warmup_seconds < 0:
        raise SystemExit("--warmup-seconds 不能为负数")
    users = args.users or profile.users
    spawn_rate = args.spawn_rate or profile.spawn_rate
    run_time = args.run_time or profile.run_time
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    fixture_path = (args.fixture or output_dir / "fixture.json").resolve()
    fixture: BenchmarkFixture
    prepared_here = False
    prepared_session: PreparedBenchmarkSession | None = None
    prepared_complete_queue: PreparedCompleteQueue | None = None

    if args.no_prepare:
        fixture = read_fixture(fixture_path)
    else:
        fixture = prepare_fixture(
            base_url=args.base_url,
            tenant_slug=args.tenant_slug,
            username=args.username,
            password=args.password,
            folder_count=args.folder_count or profile.fixture_folders,
            space_id=args.space_id,
            parent_id=args.parent_id,
            create_space=args.create_space,
        )
        write_fixture(fixture, fixture_path)
        prepared_here = True

    if scenario != "login":
        prepared_session = _prepare_benchmark_session(
            base_url=fixture.base_url,
            tenant_slug=args.tenant_slug,
            username=args.username,
            password=args.password,
        )
    if scenario == "upload_complete":
        complete_ready_count = _resolve_complete_ready_count(
            profile=args.profile,
            users=users,
            requested=args.complete_ready_count,
        )
        if prepared_session is None:
            raise RuntimeError("upload_complete 缺少预登录会话")
        prepared_complete_queue = prepare_complete_queue(
            fixture=fixture,
            session_token=prepared_session.session_token,
            csrf_token=prepared_session.csrf_token,
            count=complete_ready_count,
            size_bytes=int(os.getenv("PERF_MULTIPART_SIZE_BYTES", str(64 * 1024))),
            concurrency=args.complete_prepare_concurrency,
        )
        complete_queue_path = output_dir / "complete_queue.json"
        write_complete_queue(prepared_complete_queue, complete_queue_path)

    env = os.environ.copy()
    env.update(
        {
            "PERF_FIXTURE_PATH": str(fixture_path),
            "PERF_SCENARIO": scenario,
            "PERF_TENANT_SLUG": args.tenant_slug,
            "PERF_USERNAME": args.username,
            "PERF_PASSWORD": args.password,
            "PERF_WARMUP_SECONDS": str(args.warmup_seconds),
            "PYTHONUTF8": "1",
        }
    )
    if prepared_session is not None:
        env.update(
            {
                "PERF_SESSION_TOKEN": prepared_session.session_token,
                "PERF_CSRF_TOKEN": prepared_session.csrf_token,
            }
        )
    if prepared_complete_queue is not None:
        env.update(
            {
                "PERF_COMPLETE_QUEUE_PATH": str(output_dir / "complete_queue.json"),
                "PERF_COMPLETE_QUEUE_COUNT": str(len(prepared_complete_queue.items)),
                "PERF_COMPLETE_CONCURRENCY": str(args.complete_concurrency),
            }
        )
    locustfile = Path(__file__).with_name("locustfile.py")
    command = [
        sys.executable,
        "-X",
        "utf8",
        "-m",
        "locust",
        "-f",
        str(locustfile),
        "--headless",
        "--host",
        fixture.base_url,
        "--users",
        str(users),
        "--spawn-rate",
        str(spawn_rate),
        "--run-time",
        run_time,
        "--csv",
        str(output_dir / "stats"),
        "--html",
        str(output_dir / "report.html"),
        "--exit-code-on-error",
        "1",
    ]
    try:
        completed = _run_locust(command, env=env)
        environment_snapshot = collect_environment_snapshot(
            output_dir=output_dir,
            compose_project=args.docker_compose_project,
            target_state_path=args.target_state,
            postgres_user=args.postgres_user,
            postgres_database=args.postgres_database,
        )
        report = _write_report(
            output_dir=output_dir,
            profile=args.profile,
            scenario=scenario,
            fixture=fixture,
            users=users,
            spawn_rate=spawn_rate,
            run_time=run_time,
            locust_exit_code=completed.returncode,
            environment_snapshot=environment_snapshot,
            complete_mode=("prepared" if prepared_complete_queue is not None else None),
            complete_ready_count=(
                len(prepared_complete_queue.items) if prepared_complete_queue is not None else None
            ),
            warmup_seconds=args.warmup_seconds,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["passed"] else 1
    finally:
        if (
            prepared_complete_queue is not None
            and prepared_session is not None
            and not args.keep_complete_queue
        ):
            cleanup_summary = cleanup_complete_queue(
                queue=prepared_complete_queue,
                session_token=prepared_session.session_token,
                csrf_token=prepared_session.csrf_token,
                concurrency=args.complete_cleanup_concurrency,
            )
            write_cleanup_summary(
                cleanup_summary,
                output_dir / "complete_cleanup.json",
            )
            if not cleanup_summary["clean"]:
                raise RuntimeError(
                    f"complete queue 清理失败: errors={len(cleanup_summary['errors'])}"
                )
        if prepared_session is not None:
            _logout_benchmark_session(
                base_url=fixture.base_url,
                session=prepared_session,
            )
        if prepared_here and not args.keep_fixture:
            cleanup_fixture(
                fixture,
                username=args.username,
                password=args.password,
            )


def _resolve_complete_ready_count(
    *,
    profile: str,
    users: int,
    requested: int | None,
) -> int:
    if requested is None:
        if profile == "target":
            raise SystemExit("target upload_complete 必须显式提供 --complete-ready-count")
        return max(users * 20, 100)
    if requested < users:
        raise SystemExit("--complete-ready-count 必须不少于 --users")
    return requested


if __name__ == "__main__":
    raise SystemExit(main())
