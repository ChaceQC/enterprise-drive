from __future__ import annotations

import argparse
import csv
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from performance.fixture import (
    BenchmarkFixture,
    cleanup_fixture,
    prepare_fixture,
    read_fixture,
    write_fixture,
)
from performance.profiles import TARGET_P95_MS, get_profile


def _git_commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(__file__).resolve().parents[2],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


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
        choices=("mixed", "login", "auth_me", "list", "search", "upload_init", "audit"),
    )
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--folder-count", type=int)
    parser.add_argument("--users", type=int)
    parser.add_argument("--spawn-rate", type=float)
    parser.add_argument("--run-time")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--keep-fixture", action="store_true")
    parser.add_argument("--no-prepare", action="store_true")
    return parser


def _read_stats(path: Path, scenario: str) -> list[dict[str, Any]]:
    if not path.exists() and path.name == "stats.csv":
        locust_stats_path = path.with_name("stats_stats.csv")
        if locust_stats_path.exists():
            path = locust_stats_path
    if not path.exists():
        return []
    results: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            name = str(row.get("Name") or "")
            if name == "Aggregated":
                continue
            request_count = int(row.get("Request Count") or 0)
            failures = int(row.get("Failure Count") or 0)
            p95 = float(row.get("95%") or 0)
            target = TARGET_P95_MS.get(name)
            results.append(
                {
                    "name": name,
                    "request_count": request_count,
                    "failure_count": failures,
                    "failure_rate": round(failures / request_count, 6) if request_count else 0.0,
                    "p95_ms": p95,
                    "p99_ms": float(row.get("99%") or 0),
                    "requests_per_second": float(row.get("Requests/s") or 0),
                    "target_p95_ms": target,
                    "passed": failures == 0 and (target is None or p95 <= target),
                }
            )
    return results


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


def _write_report(
    *,
    output_dir: Path,
    profile: str,
    scenario: str,
    fixture: BenchmarkFixture,
    users: int,
    spawn_rate: float,
    run_time: str,
    locust_exit_code: int,
) -> dict[str, Any]:
    results = _read_stats(output_dir / "stats.csv", scenario)
    report = {
        "schema_version": "BE-029/1",
        "profile": profile,
        "scenario": scenario,
        "base_url": fixture.base_url,
        "fixture_folder_count": len(fixture.folder_ids),
        "users": users,
        "spawn_rate": spawn_rate,
        "run_time": run_time,
        "locust_exit_code": locust_exit_code,
        "generated_at": datetime.now(UTC).isoformat(),
        "environment": {
            "git_commit": _git_commit(),
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "locust_version": importlib.metadata.version("locust"),
            "cpu_count": os.cpu_count(),
            "rate_limit_mode": os.getenv("PERF_RATE_LIMIT_MODE", "not-recorded"),
            "fixture_created_space": fixture.created_space,
        },
        "results": results,
        "passed": bool(results)
        and locust_exit_code == 0
        and all(bool(result["passed"]) for result in results),
        "artifacts": {
            "stats_csv": "stats_stats.csv",
            "history_csv": "stats_stats_history.csv",
            "failures_csv": "stats_failures.csv",
            "exceptions_csv": "stats_exceptions.csv",
            "html": "report.html",
        },
    }
    (output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if not args.password:
        raise SystemExit("请通过 --password 或 PERF_PASSWORD 提供性能测试账号密码")
    profile = get_profile(args.profile)
    scenario = args.scenario or profile.default_scenario
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
        report = _write_report(
            output_dir=output_dir,
            profile=args.profile,
            scenario=scenario,
            fixture=fixture,
            users=users,
            spawn_rate=spawn_rate,
            run_time=run_time,
            locust_exit_code=completed.returncode,
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
