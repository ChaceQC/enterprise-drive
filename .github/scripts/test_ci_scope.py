#!/usr/bin/env python3
"""Small regression suite for the CI scope router."""

from __future__ import annotations

import unittest

from ci_scope import scope_for_event, scope_for_paths


def enabled(*keys: str) -> dict[str, bool]:
    return {key: key in keys for key in (
        "backend",
        "desktop",
        "installer",
        "rust_policy",
        "windows",
        "minio",
    )}


class CiScopeTests(unittest.TestCase):
    def test_backend_change(self) -> None:
        self.assertEqual(scope_for_paths(["backend/app/main.py"]), enabled("backend"))

    def test_desktop_crate_change_skips_installer_on_pr_routing(self) -> None:
        self.assertEqual(
            scope_for_paths(["desktop/crates/drive-sync-engine/src/lib.rs"]),
            enabled("desktop"),
        )

    def test_desktop_contract_routes_to_backend(self) -> None:
        self.assertEqual(
            scope_for_paths(["desktop/contracts/sprint8-openapi.json"]),
            enabled("backend"),
        )

    def test_desktop_manifest_routes_to_all_desktop_gates(self) -> None:
        self.assertEqual(
            scope_for_paths(["desktop/Cargo.lock"]),
            enabled("desktop", "installer", "rust_policy"),
        )

    def test_windows_script_change(self) -> None:
        self.assertEqual(
            scope_for_paths(["deploy/windows/manage.ps1"]),
            enabled("windows"),
        )

    def test_compose_change_routes_to_runtime_and_image_gates(self) -> None:
        self.assertEqual(
            scope_for_paths(["compose.windows.yml"]),
            enabled("backend", "windows", "minio"),
        )

    def test_dev_compose_image_change_only_runs_image_policy(self) -> None:
        self.assertEqual(
            scope_for_paths(["backend/docker-compose.yml"]),
            enabled("minio"),
        )

    def test_workflow_change_runs_every_gate(self) -> None:
        self.assertEqual(
            scope_for_paths([".github/workflows/backend-ci.yml"]),
            enabled("backend", "desktop", "installer", "rust_policy", "windows", "minio"),
        )

    def test_docs_only_change_runs_no_expensive_gate(self) -> None:
        self.assertEqual(scope_for_paths(["desktop/README.md"]), enabled())

    def test_schedule_keeps_supply_chain_coverage(self) -> None:
        self.assertEqual(scope_for_event("schedule"), enabled("rust_policy", "minio"))


if __name__ == "__main__":
    unittest.main()
