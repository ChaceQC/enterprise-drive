from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

from performance.complete_queue import (
    COMPLETE_QUEUE_SCHEMA,
    PreparedCompleteItem,
    PreparedCompleteQueue,
    load_complete_queue_runtime,
    mark_prepared_complete_item_finished,
    read_complete_queue,
    take_prepared_complete_item,
    write_complete_queue,
)
from performance.fixture import (
    BenchmarkFixture,
    _delete_and_purge_node,
    prepare_fixture,
    read_fixture,
    write_fixture,
)
from performance.multipart import parse_server_timing
from performance.profiles import get_profile
from performance.runner import (
    _prepare_benchmark_session,
    _resolve_complete_ready_count,
    _run_locust,
    _write_report,
)


def _fixture() -> BenchmarkFixture:
    return BenchmarkFixture(
        schema_version="BE-029/1",
        base_url="http://localhost:18080",
        tenant_slug="default",
        space_id="space-id",
        parent_id="root-id",
        fixture_root_id="fixture-root-id",
        folder_ids=["node-1", "node-2"],
        search_query="perf1234",
        created_space=False,
        created_at="2026-07-31T00:00:00+00:00",
    )


def _write_performance_stat(path: Path, row: dict[str, str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "Type",
                "Name",
                "Request Count",
                "Failure Count",
                "Median Response Time",
                "Average Response Time",
                "Min Response Time",
                "Max Response Time",
                "Requests/s",
                "95%",
                "99%",
            ],
        )
        writer.writeheader()
        writer.writerow(row)


def test_profiles_keep_smoke_below_target_resource_budget() -> None:
    smoke = get_profile("smoke")
    assert smoke.fixture_folders == 100
    assert smoke.users == 2
    assert smoke.run_time == "20s"


def test_server_timing_parser_extracts_upload_complete_phases() -> None:
    timings = parse_server_timing(
        "storage_complete;dur=12.5, hash_validation;dur=3.25, final_object;dur=8"
    )

    assert timings == {
        "storage_complete": 12.5,
        "hash_validation": 3.25,
        "final_object": 8.0,
    }


def test_fixture_round_trip_uses_utf8_json(tmp_path: Path) -> None:
    path = tmp_path / "fixture.json"
    fixture = _fixture()

    write_fixture(fixture, path)

    assert read_fixture(path) == fixture
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == "BE-029/1"


def test_report_marks_each_request_against_p95_target(tmp_path: Path) -> None:
    stats_path = tmp_path / "stats_stats.csv"
    with stats_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "Type",
                "Name",
                "Request Count",
                "Failure Count",
                "Median Response Time",
                "Average Response Time",
                "Min Response Time",
                "Max Response Time",
                "Average Content Size",
                "Requests/s",
                "Failures/s",
                "95%",
                "99%",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "Type": "GET",
                "Name": "file_list_permission_batch",
                "Request Count": "10",
                "Failure Count": "0",
                "Median Response Time": "50",
                "Average Response Time": "70",
                "Min Response Time": "20",
                "Max Response Time": "150",
                "Average Content Size": "1024",
                "Requests/s": "2",
                "Failures/s": "0",
                "95%": "150",
                "99%": "180",
            }
        )
        writer.writerow(
            {
                "Type": "GET",
                "Name": "search",
                "Request Count": "10",
                "Failure Count": "0",
                "Median Response Time": "500",
                "Average Response Time": "700",
                "Min Response Time": "200",
                "Max Response Time": "900",
                "Average Content Size": "1024",
                "Requests/s": "2",
                "Failures/s": "0",
                "95%": "900",
                "99%": "950",
            }
        )

    report = _write_report(
        output_dir=tmp_path,
        profile="smoke",
        scenario="mixed",
        fixture=_fixture(),
        users=2,
        spawn_rate=2.0,
        run_time="20s",
        locust_exit_code=0,
    )

    assert report["passed"] is False
    assert report["schema_version"] == "BE-029/2"
    assert report["summary"]["request_count"] == 20
    assert report["summary"]["http_request_count"] == 20
    assert report["summary"]["derived_metric_count"] == 0
    assert report["summary"]["failure_rate"] == 0.0
    assert report["environment"]["locust_version"]
    assert report["environment"]["fixture_created_space"] is False
    assert report["workload"]["upload_init_cleanup_mode"] == "abort"
    assert report["workload"]["storage_warmup_mode"] is None
    assert report["workload"]["complete_mode"] is None
    assert report["workload"]["complete_ready_count"] is None
    assert report["workload"]["warmup_seconds"] == 0.0
    assert report["workload"]["complete_quit_grace_seconds"] is None
    by_name = {item["name"]: item for item in report["results"]}
    assert by_name["file_list_permission_batch"]["p50_ms"] == 50.0
    assert by_name["file_list_permission_batch"]["passed"] is True
    assert by_name["search"]["passed"] is False


def test_locust_stderr_is_forwarded_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    completed = _run_locust(
        [
            sys.executable,
            "-c",
            "import sys; print('locust-stdout'); print('locust-stderr', file=sys.stderr)",
        ],
        env=os.environ.copy(),
    )

    captured = capsys.readouterr()
    assert completed.returncode == 0
    assert "locust-stdout" in captured.out
    assert "locust-stderr" in captured.out
    assert captured.err == ""


def test_runner_prepares_shared_cookie_session(monkeypatch: pytest.MonkeyPatch) -> None:
    real_client = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/auth/login"
        return httpx.Response(
            200,
            headers=[
                ("Set-Cookie", "drive_session=session-token; Path=/; HttpOnly"),
                ("Set-Cookie", "drive_csrf=csrf-token; Path=/"),
            ],
        )

    def client_factory(*args: Any, **kwargs: Any) -> httpx.Client:
        return real_client(
            *args,
            **kwargs,
            transport=httpx.MockTransport(handler),
        )

    monkeypatch.setattr("performance.runner.httpx.Client", client_factory)

    session = _prepare_benchmark_session(
        base_url="http://benchmark.test",
        tenant_slug="default",
        username="admin",
        password="password",
    )

    assert session.session_token == "session-token"
    assert session.csrf_token == "csrf-token"


def test_complete_queue_round_trip_and_atomic_consumption(
    tmp_path: Path,
) -> None:
    path = tmp_path / "complete_queue.json"
    queue = PreparedCompleteQueue(
        schema_version=COMPLETE_QUEUE_SCHEMA,
        base_url="http://benchmark.test",
        tenant_slug="default",
        space_id="space-id",
        parent_id="parent-id",
        size_bytes=1024,
        items=[
            PreparedCompleteItem(
                session_id="session-1",
                etag="etag-1",
                size_bytes=1024,
            ),
            PreparedCompleteItem(
                session_id="session-2",
                etag="etag-2",
                size_bytes=1024,
            ),
        ],
        created_at="2026-08-01T00:00:00+00:00",
    )
    write_complete_queue(queue, path)
    assert read_complete_queue(path) == queue

    load_complete_queue_runtime.cache_clear()
    assert take_prepared_complete_item(str(path)) == queue.items[0]
    assert take_prepared_complete_item(str(path)) == queue.items[1]
    assert take_prepared_complete_item(str(path)) is None
    assert mark_prepared_complete_item_finished(str(path)) is False
    assert mark_prepared_complete_item_finished(str(path)) is True
    assert mark_prepared_complete_item_finished(str(path)) is False
    load_complete_queue_runtime.cache_clear()


def test_target_complete_ready_count_must_be_explicit() -> None:
    with pytest.raises(SystemExit, match="必须显式提供"):
        _resolve_complete_ready_count(profile="target", users=16, requested=None)
    assert _resolve_complete_ready_count(profile="smoke", users=2, requested=None) == 100
    assert _resolve_complete_ready_count(profile="target", users=16, requested=200) == 200
    with pytest.raises(SystemExit, match="必须不少于"):
        _resolve_complete_ready_count(profile="target", users=16, requested=15)


def test_target_upload_init_requires_100_rps(tmp_path: Path) -> None:
    stats_path = tmp_path / "stats_stats.csv"
    with stats_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "Type",
                "Name",
                "Request Count",
                "Failure Count",
                "Median Response Time",
                "Average Response Time",
                "Min Response Time",
                "Max Response Time",
                "Requests/s",
                "95%",
                "99%",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "Type": "POST",
                "Name": "upload_init",
                "Request Count": "1000",
                "Failure Count": "0",
                "Median Response Time": "100",
                "Average Response Time": "120",
                "Min Response Time": "50",
                "Max Response Time": "280",
                "Requests/s": "99.9",
                "95%": "250",
                "99%": "270",
            }
        )

    report = _write_report(
        output_dir=tmp_path,
        profile="target",
        scenario="upload_init",
        fixture=_fixture(),
        users=100,
        spawn_rate=20.0,
        run_time="60s",
        locust_exit_code=0,
    )

    result = report["results"][0]
    assert result["target_min_rps"] == 100.0
    assert result["passed"] is False
    assert report["summary"]["missing_required_metrics"] == []
    assert report["passed"] is False


def test_target_mixed_requires_each_gate_metric(tmp_path: Path) -> None:
    _write_performance_stat(
        tmp_path / "stats_stats.csv",
        {
            "Type": "GET",
            "Name": "auth_me",
            "Request Count": "100",
            "Failure Count": "0",
            "Median Response Time": "20",
            "Average Response Time": "20",
            "Min Response Time": "10",
            "Max Response Time": "30",
            "Requests/s": "100",
            "95%": "25",
            "99%": "30",
        },
    )

    report = _write_report(
        output_dir=tmp_path,
        profile="target",
        scenario="mixed",
        fixture=_fixture(),
        users=50,
        spawn_rate=5.0,
        run_time="300s",
        locust_exit_code=0,
    )

    assert report["summary"]["missing_required_metrics"] == [
        "admin_audit",
        "file_list_permission_batch",
        "search",
        "upload_init",
    ]
    assert report["passed"] is False


def test_target_required_metric_requires_at_least_one_sample(tmp_path: Path) -> None:
    _write_performance_stat(
        tmp_path / "stats_stats.csv",
        {
            "Type": "GET",
            "Name": "file_list_permission_batch",
            "Request Count": "0",
            "Failure Count": "0",
            "Median Response Time": "0",
            "Average Response Time": "0",
            "Min Response Time": "0",
            "Max Response Time": "0",
            "Requests/s": "0",
            "95%": "0",
            "99%": "0",
        },
    )

    report = _write_report(
        output_dir=tmp_path,
        profile="target",
        scenario="list",
        fixture=_fixture(),
        users=50,
        spawn_rate=5.0,
        run_time="300s",
        locust_exit_code=0,
    )

    assert report["summary"]["missing_required_metrics"] == ["file_list_permission_batch"]
    assert report["passed"] is False


def test_target_upload_complete_requires_end_to_end_metric(tmp_path: Path) -> None:
    stats_path = tmp_path / "stats_stats.csv"
    with stats_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "Type",
                "Name",
                "Request Count",
                "Failure Count",
                "Median Response Time",
                "Average Response Time",
                "Min Response Time",
                "Max Response Time",
                "Requests/s",
                "95%",
                "99%",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "Type": "BENCH",
                "Name": "upload_complete_api_without_storage_merge",
                "Request Count": "100",
                "Failure Count": "0",
                "Median Response Time": "100",
                "Average Response Time": "120",
                "Min Response Time": "50",
                "Max Response Time": "280",
                "Requests/s": "60",
                "95%": "250",
                "99%": "270",
            }
        )

    report = _write_report(
        output_dir=tmp_path,
        profile="target",
        scenario="upload_complete",
        fixture=_fixture(),
        users=100,
        spawn_rate=20.0,
        run_time="60s",
        locust_exit_code=0,
    )

    assert report["summary"]["missing_required_metrics"] == ["upload_complete_end_to_end"]
    assert report["passed"] is False


def test_fixture_cleanup_soft_deletes_before_single_purge() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/purge"):
            return httpx.Response(200, json={"purged_count": 101})
        return httpx.Response(200, json={"deleted_count": 101})

    with httpx.Client(
        base_url="http://fixture.test",
        transport=httpx.MockTransport(handler),
    ) as client:
        removed = _delete_and_purge_node(
            client,
            node_id="fixture-root-id",
            csrf="csrf-token",
        )

    assert removed == 101
    assert calls == [
        ("DELETE", "/api/v1/files/fixture-root-id"),
        ("DELETE", "/api/v1/files/fixture-root-id/purge"),
    ]


def test_partial_fixture_prepare_cleans_created_root(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    folder_creates = 0
    real_client = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal folder_creates
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/v1/auth/login":
            return httpx.Response(
                200,
                headers={"Set-Cookie": "drive_csrf=csrf-token; Path=/"},
            )
        if request.url.path == "/api/v1/spaces":
            return httpx.Response(
                201,
                json={"id": "space-id", "root_node_id": "space-root-id"},
            )
        if request.url.path == "/api/v1/files/folders":
            folder_creates += 1
            if folder_creates == 1:
                return httpx.Response(201, json={"id": "fixture-root-id"})
            if folder_creates == 2:
                return httpx.Response(201, json={"id": "child-id"})
            return httpx.Response(500, text="fixture child failed")
        if request.url.path == "/api/v1/files/fixture-root-id":
            return httpx.Response(200, json={"deleted_count": 2})
        if request.url.path == "/api/v1/files/fixture-root-id/purge":
            return httpx.Response(200, json={"purged_count": 2})
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    def client_factory(*args: Any, **kwargs: Any) -> httpx.Client:
        return real_client(
            *args,
            **kwargs,
            transport=httpx.MockTransport(handler),
        )

    monkeypatch.setattr("performance.fixture.httpx.Client", client_factory)

    with pytest.raises(RuntimeError, match="fixture child failed"):
        prepare_fixture(
            base_url="http://fixture.test",
            tenant_slug="default",
            username="admin",
            password="password",
            folder_count=2,
            create_space=True,
        )

    assert calls[-2:] == [
        ("DELETE", "/api/v1/files/fixture-root-id"),
        ("DELETE", "/api/v1/files/fixture-root-id/purge"),
    ]
