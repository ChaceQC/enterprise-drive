from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

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
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--keep-fixture", action="store_true")
    parser.add_argument("--no-prepare", action="store_true")
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
    users = args.users or profile.users
    spawn_rate = args.spawn_rate or profile.spawn_rate
    run_time = args.run_time or profile.run_time
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    fixture_path = (args.fixture or output_dir / "fixture.json").resolve()
    fixture: BenchmarkFixture
    prepared_here = False

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

    env = os.environ.copy()
    env.update(
        {
            "PERF_FIXTURE_PATH": str(fixture_path),
            "PERF_SCENARIO": scenario,
            "PERF_TENANT_SLUG": args.tenant_slug,
            "PERF_USERNAME": args.username,
            "PERF_PASSWORD": args.password,
            "PYTHONUTF8": "1",
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
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["passed"] else 1
    finally:
        if prepared_here and not args.keep_fixture:
            cleanup_fixture(
                fixture,
                username=args.username,
                password=args.password,
            )


if __name__ == "__main__":
    raise SystemExit(main())
