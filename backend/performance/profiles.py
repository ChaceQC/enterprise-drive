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
    "search": 800.0,
    "admin_audit": 1_000.0,
}


def get_profile(name: str) -> BenchmarkProfile:
    try:
        return PROFILES[name]
    except KeyError as exc:
        available = ", ".join(sorted(PROFILES))
        raise ValueError(f"未知性能基准 profile: {name}（可选：{available}）") from exc
