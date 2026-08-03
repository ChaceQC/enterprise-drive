from __future__ import annotations

import csv
import importlib.metadata
import json
import os
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from performance.fixture import BenchmarkFixture
from performance.profiles import TARGET_MIN_RPS_BY_SCENARIO, TARGET_P95_MS


def read_stats(path: Path) -> list[dict[str, Any]]:
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
                    "request_type": str(row.get("Type") or ""),
                    "name": name,
                    "request_count": request_count,
                    "failure_count": failures,
                    "failure_rate": round(failures / request_count, 6) if request_count else 0.0,
                    "average_ms": float(row.get("Average Response Time") or 0),
                    "min_ms": float(row.get("Min Response Time") or 0),
                    "max_ms": float(row.get("Max Response Time") or 0),
                    "p50_ms": float(row.get("Median Response Time") or 0),
                    "p95_ms": p95,
                    "p99_ms": float(row.get("99%") or 0),
                    "requests_per_second": float(row.get("Requests/s") or 0),
                    "target_p95_ms": target,
                    "target_min_rps": None,
                    "passed": failures == 0 and (target is None or p95 <= target),
                }
            )
    return results


def write_report(
    *,
    output_dir: Path,
    profile: str,
    scenario: str,
    fixture: BenchmarkFixture,
    users: int,
    spawn_rate: float,
    run_time: str,
    locust_exit_code: int,
    environment_snapshot: dict[str, Any] | None = None,
    complete_mode: str | None = None,
    complete_ready_count: int | None = None,
    warmup_seconds: float = 0.0,
) -> dict[str, Any]:
    results = read_stats(output_dir / "stats.csv")
    required_metrics = _apply_target_throughput_requirements(
        results=results,
        profile=profile,
        scenario=scenario,
    )
    present_metrics = {str(result["name"]) for result in results}
    missing_required_metrics = sorted(required_metrics - present_metrics)
    total_requests = sum(int(result["request_count"]) for result in results)
    total_failures = sum(int(result["failure_count"]) for result in results)
    http_requests = sum(
        int(result["request_count"]) for result in results if result["request_type"] != "BENCH"
    )
    derived_metrics = total_requests - http_requests
    snapshot = environment_snapshot or {}
    environment_complete = bool(snapshot.get("complete", True))
    report = {
        "schema_version": "BE-029/2",
        "profile": profile,
        "scenario": scenario,
        "base_url": fixture.base_url,
        "fixture_folder_count": len(fixture.folder_ids),
        "users": users,
        "spawn_rate": spawn_rate,
        "run_time": run_time,
        "locust_exit_code": locust_exit_code,
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": {
            "request_count": total_requests,
            "http_request_count": http_requests,
            "derived_metric_count": derived_metrics,
            "failure_count": total_failures,
            "failure_rate": (round(total_failures / total_requests, 6) if total_requests else 0.0),
            "missing_required_metrics": missing_required_metrics,
        },
        "workload": {
            "fixture_folder_count": len(fixture.folder_ids),
            "upload_init_cleanup_mode": (
                os.getenv("PERF_UPLOAD_INIT_CLEANUP", "abort")
                if scenario in {"upload_init", "mixed"}
                else None
            ),
            "multipart_size_bytes": (
                int(os.getenv("PERF_MULTIPART_SIZE_BYTES", "0"))
                if scenario == "upload_complete"
                else None
            ),
            "storage_warmup_mode": (
                os.getenv("PERF_STORAGE_WARMUP_MODE", "per_user")
                if scenario == "upload_complete"
                else None
            ),
            "complete_mode": complete_mode if scenario == "upload_complete" else None,
            "complete_ready_count": (
                complete_ready_count if scenario == "upload_complete" else None
            ),
            "warmup_seconds": warmup_seconds,
            "complete_quit_grace_seconds": (
                float(os.getenv("PERF_COMPLETE_QUIT_GRACE_SECONDS", "0.2"))
                if scenario == "upload_complete"
                else None
            ),
        },
        "environment": {
            "git_commit": _git_commit(),
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "locust_version": importlib.metadata.version("locust"),
            "cpu_count": os.cpu_count(),
            "rate_limit_mode": os.getenv("PERF_RATE_LIMIT_MODE", "not-recorded"),
            "fixture_created_space": fixture.created_space,
            **snapshot,
        },
        "results": results,
        "passed": bool(results)
        and locust_exit_code == 0
        and environment_complete
        and not missing_required_metrics
        and all(bool(result["passed"]) for result in results),
        "artifacts": {
            "stats_csv": "stats_stats.csv",
            "history_csv": "stats_stats_history.csv",
            "failures_csv": "stats_failures.csv",
            "exceptions_csv": "stats_exceptions.csv",
            "html": "report.html",
            "complete_queue": (
                "complete_queue.json"
                if scenario == "upload_complete" and complete_mode == "prepared"
                else None
            ),
            "complete_cleanup": (
                "complete_cleanup.json"
                if scenario == "upload_complete" and complete_mode == "prepared"
                else None
            ),
        },
    }
    (output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def _apply_target_throughput_requirements(
    *,
    results: list[dict[str, Any]],
    profile: str,
    scenario: str,
) -> set[str]:
    if profile != "target":
        return set()
    targets = TARGET_MIN_RPS_BY_SCENARIO.get(scenario, {})
    for result in results:
        minimum_rps = targets.get(str(result["name"]))
        result["target_min_rps"] = minimum_rps
        if minimum_rps is not None:
            result["passed"] = bool(result["passed"]) and (
                float(result["requests_per_second"]) >= minimum_rps
            )
    return set(targets)


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
