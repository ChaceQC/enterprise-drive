from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BenchmarkProfile:
    name: str
    fixture_folders: int
    users: int
    spawn_rate: float
    run_time: str
    default_scenario: str


PROFILES: dict[str, BenchmarkProfile] = {
    "smoke": BenchmarkProfile(
        name="smoke",
        fixture_folders=100,
        users=2,
        spawn_rate=2.0,
        run_time="20s",
        default_scenario="mixed",
    ),
    "baseline": BenchmarkProfile(
        name="baseline",
        fixture_folders=1_000,
        users=10,
        spawn_rate=2.0,
        run_time="60s",
        default_scenario="mixed",
    ),
    "target": BenchmarkProfile(
        name="target",
        fixture_folders=10_000,
        users=50,
        spawn_rate=5.0,
        run_time="300s",
        default_scenario="mixed",
    ),
}


TARGET_P95_MS: dict[str, float] = {
    "file_list_permission_batch": 500.0,
    "upload_init": 300.0,
    "upload_complete_api_without_storage_merge": 800.0,
    "search": 800.0,
    "admin_audit": 1_000.0,
}

TARGET_MIN_RPS_BY_SCENARIO: dict[str, dict[str, float]] = {
    "upload_init": {"upload_init": 100.0},
    "upload_complete": {"upload_complete_end_to_end": 50.0},
}

TARGET_REQUIRED_METRICS_BY_SCENARIO: dict[str, frozenset[str]] = {
    "mixed": frozenset(
        {
            "file_list_permission_batch",
            "search",
            "upload_init",
            "admin_audit",
        }
    ),
    "login": frozenset({"auth_login"}),
    "auth_me": frozenset({"auth_me"}),
    "list": frozenset({"file_list_permission_batch"}),
    "search": frozenset({"search"}),
    "upload_init": frozenset({"upload_init"}),
    "upload_complete": frozenset(
        {
            "upload_complete_api_without_storage_merge",
            "upload_complete_end_to_end",
        }
    ),
    "audit": frozenset({"admin_audit"}),
}


def get_profile(name: str) -> BenchmarkProfile:
    try:
        return PROFILES[name]
    except KeyError as exc:
        available = ", ".join(sorted(PROFILES))
        raise ValueError(f"未知性能基准 profile: {name}（可选：{available}）") from exc
