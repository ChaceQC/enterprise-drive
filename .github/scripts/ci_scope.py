#!/usr/bin/env python3
"""Resolve the smallest CI scope for a changed revision.

The workflow still has one entry point, but expensive jobs are selected by
the files that changed.  This keeps the routing logic testable outside of
GitHub Actions and gives scheduled/manual runs explicit semantics.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from collections.abc import Iterable, Sequence
from pathlib import Path

SCOPE_KEYS = (
    "backend",
    "frontend",
    "desktop",
    "installer",
    "rust_policy",
    "windows",
    "minio",
)

WORKFLOW_PATH = ".github/workflows/backend-ci.yml"
SCOPE_SCRIPT_PREFIX = ".github/scripts/"


def _empty_scope() -> dict[str, bool]:
    return {key: False for key in SCOPE_KEYS}


def _all_scope() -> dict[str, bool]:
    return {key: True for key in SCOPE_KEYS}


def _normalise(path: str) -> str:
    normalised = path.replace("\\", "/")
    while normalised.startswith("./"):
        normalised = normalised[2:]
    return normalised


def scope_for_event(event_name: str) -> dict[str, bool]:
    """Return the explicit scope for events that do not carry a diff."""

    if event_name == "schedule":
        scope = _empty_scope()
        scope["minio"] = True
        scope["rust_policy"] = True
        return scope
    if event_name == "workflow_dispatch":
        return _all_scope()
    return _empty_scope()


def scope_for_paths(paths: Iterable[str]) -> dict[str, bool]:
    """Map changed repository paths to CI jobs.

    ``desktop/contracts`` is consumed by backend contract tests but does not
    require a Rust build.  Library source changes run Rust validation without
    rebuilding the installer; Tauri app/package/signing changes select the
    installer.  Rust dependency policy is intentionally limited to dependency
    and toolchain configuration and is also covered by the scheduled run.
    """

    scope = _empty_scope()
    for raw_path in paths:
        path = _normalise(raw_path)
        if not path:
            continue

        if path == WORKFLOW_PATH or path.startswith(SCOPE_SCRIPT_PREFIX):
            # ``changes`` 已经执行路由器回归；CI 定义或路由器本身变化
            # 不代表业务代码变化，避免每次改 workflow 都重新编译桌面端。
            continue

        if (
            (
                path.startswith("backend/")
                and path != "backend/docker-compose.yml"
            )
            or path.startswith("deploy/monitoring/")
            or path.startswith("deploy/windows/nginx/")
            or path in {"compose.windows.yml", ".env.windows.example"}
        ):
            scope["backend"] = True

        if path.startswith("frontend/"):
            scope["frontend"] = True
            if path.startswith("frontend/openapi/"):
                scope["backend"] = True

        if path.startswith("deploy/windows/") and not path.startswith(
            "deploy/windows/nginx/"
        ):
            scope["windows"] = True

        if path == "backend/docker-compose.yml":
            scope["minio"] = True

        if path in {"compose.windows.yml", ".env.windows.example"}:
            scope["windows"] = True
            scope["minio"] = True

        if path.startswith("desktop/contracts/"):
            scope["backend"] = True
            continue

        if path == "desktop/deny.toml":
            scope["rust_policy"] = True
            continue

        if path in {
            "desktop/Cargo.toml",
            "desktop/Cargo.lock",
            "desktop/rust-toolchain.toml",
        }:
            scope["desktop"] = True
            scope["installer"] = True
            scope["rust_policy"] = True
            continue

        if path.startswith("desktop/.cargo/"):
            scope["desktop"] = True
            scope["installer"] = True
            scope["rust_policy"] = True
            continue

        if path.startswith("desktop/signing/") or path == "desktop/update-public-key.txt":
            scope["installer"] = True
            continue

        if path.startswith("desktop/apps/"):
            if path.endswith(".rs"):
                scope["desktop"] = True
            if path.endswith("Cargo.toml"):
                scope["rust_policy"] = True
                scope["desktop"] = True
            # Tauri UI, generated schemas, capabilities, icons and config are
            # consumed only by the installer build; a separate Rust job would
            # compile the same application again.
            scope["installer"] = True
            continue

        if path.startswith("desktop/crates/"):
            if path.endswith("Cargo.toml"):
                scope["desktop"] = True
                scope["installer"] = True
                scope["rust_policy"] = True
                continue
            if "/tests/" in path or "/benches/" in path:
                scope["desktop"] = True
                continue
            if path.endswith(".rs") or path.endswith("build.rs"):
                scope["desktop"] = True
                if path.startswith("desktop/crates/drive-update/"):
                    scope["installer"] = True
                continue

        if path.startswith("desktop/scripts/"):
            # Icon/helper scripts do not participate in the CI build unless
            # their generated assets are changed; keep this path lightweight.
            continue

    return scope


def _git_paths(
    *,
    event_name: str,
    before: str,
    base: str,
    head: str,
    repo_root: Path,
) -> list[str]:
    """Read changed paths for a push or pull_request event."""

    if event_name == "pull_request":
        if not base or not head:
            raise ValueError("pull_request requires both base and head SHAs")
        command = ["diff", "--name-only", f"{base}...{head}"]
    else:
        if not head:
            raise ValueError("push requires a head SHA")
        if not before or set(before) == {"0"}:
            command = ["ls-tree", "-r", "--name-only", head]
        else:
            command = ["diff", "--name-only", before, head]

    result = subprocess.run(
        ["git", *command],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def resolve_scope(
    *,
    event_name: str,
    before: str = "",
    base: str = "",
    head: str = "",
    paths: Sequence[str] | None = None,
    repo_root: Path | None = None,
) -> dict[str, bool]:
    if event_name in {"schedule", "workflow_dispatch"}:
        return scope_for_event(event_name)
    if paths is None:
        paths = _git_paths(
            event_name=event_name,
            before=before,
            base=base,
            head=head,
            repo_root=repo_root or Path.cwd(),
        )
    return scope_for_paths(paths)


def _write_outputs(scope: dict[str, bool], output_path: str | None) -> None:
    values = [f"{key}={'true' if scope[key] else 'false'}" for key in SCOPE_KEYS]
    enabled = [key for key in SCOPE_KEYS if scope[key]]
    values.append(f"summary={','.join(enabled) if enabled else 'none'}")
    if output_path:
        with open(output_path, "a", encoding="utf-8", newline="\n") as output:
            output.write("\n".join(values))
            output.write("\n")
    else:
        print("\n".join(values))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", default=os.environ.get("EVENT_NAME", "push"))
    parser.add_argument("--before", default=os.environ.get("BEFORE_SHA", ""))
    parser.add_argument("--base", default=os.environ.get("BASE_SHA", ""))
    parser.add_argument("--head", default=os.environ.get("HEAD_SHA", ""))
    parser.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    parser.add_argument("--paths", nargs="*")
    args = parser.parse_args()

    try:
        scope = resolve_scope(
            event_name=args.event,
            before=args.before,
            base=args.base,
            head=args.head,
            paths=args.paths,
        )
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        parser.error(str(exc))
    _write_outputs(scope, args.github_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
