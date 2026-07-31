from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path

from performance.fixture import cleanup_fixture, prepare_fixture, read_fixture, write_fixture
from performance.profiles import get_profile


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="准备或清理 BE-029 性能 fixture")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--base-url", default=os.getenv("PERF_BASE_URL", "http://localhost:18080"))
    prepare.add_argument("--tenant-slug", default=os.getenv("PERF_TENANT_SLUG", "default"))
    prepare.add_argument("--username", default=os.getenv("PERF_USERNAME", "admin"))
    prepare.add_argument("--password", default=os.getenv("PERF_PASSWORD"))
    prepare.add_argument("--space-id")
    prepare.add_argument("--parent-id")
    prepare.add_argument("--create-space", action="store_true")
    prepare.add_argument("--folder-count", type=int)
    prepare.add_argument("--profile", choices=("smoke", "baseline", "target"), default="smoke")
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--timeout", type=float, default=30.0)

    cleanup = subparsers.add_parser("cleanup")
    cleanup.add_argument("--fixture", type=Path, required=True)
    cleanup.add_argument("--username", default=os.getenv("PERF_USERNAME", "admin"))
    cleanup.add_argument("--password", default=os.getenv("PERF_PASSWORD"))
    cleanup.add_argument("--timeout", type=float, default=30.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if not args.password:
        raise SystemExit("请通过 --password 或 PERF_PASSWORD 提供性能测试账号密码")
    if args.command == "prepare":
        profile = get_profile(args.profile)
        fixture = prepare_fixture(
            base_url=args.base_url,
            tenant_slug=args.tenant_slug,
            username=args.username,
            password=args.password,
            folder_count=args.folder_count or profile.fixture_folders,
            space_id=args.space_id,
            parent_id=args.parent_id,
            create_space=args.create_space,
            timeout_seconds=args.timeout,
        )
        write_fixture(fixture, args.output)
        print(json.dumps(asdict(fixture), ensure_ascii=False, indent=2))
        return 0

    fixture = read_fixture(args.fixture)
    removed_nodes = cleanup_fixture(
        fixture,
        username=args.username,
        password=args.password,
        timeout_seconds=args.timeout,
    )
    print(f"removed_nodes={removed_nodes}")
    return 0
