from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

from performance.fixture import (
    BenchmarkFixture,
    _delete_and_purge_node,
    prepare_fixture,
    read_fixture,
    write_fixture,
)
from performance.profiles import get_profile
from performance.runner import _run_locust, _write_report


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


def test_profiles_keep_smoke_below_target_resource_budget() -> None:
    smoke = get_profile("smoke")
    assert smoke.fixture_folders == 100
    assert smoke.users == 2
    assert smoke.run_time == "20s"


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
    assert report["environment"]["locust_version"]
    assert report["environment"]["fixture_created_space"] is False
    by_name = {item["name"]: item for item in report["results"]}
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
