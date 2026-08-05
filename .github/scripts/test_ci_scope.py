#!/usr/bin/env python3
"""Small regression suite for the CI scope router."""

from __future__ import annotations

import unittest

from ci_scope import scope_for_event, scope_for_paths


def enabled(*keys: str) -> dict[str, bool]:
    return {key: key in keys for key in (
        "backend",
        "frontend",
        "desktop",
        "installer",
        "rust_policy",
        "windows",
        "object_storage",
    )}


class CiScopeTests(unittest.TestCase):
    def test_backend_change(self) -> None:
        self.assertEqual(scope_for_paths(["backend/app/main.py"]), enabled("backend"))

    def test_frontend_change(self) -> None:
        self.assertEqual(
            scope_for_paths(["frontend/src/main.tsx"]),
            enabled("frontend"),
        )

    def test_frontend_contract_routes_to_backend_and_frontend(self) -> None:
        self.assertEqual(
            scope_for_paths(["frontend/openapi/openapi.json"]),
            enabled("backend", "frontend"),
        )

    def test_desktop_crate_source_skips_installer(self) -> None:
        self.assertEqual(
            scope_for_paths(["desktop/crates/drive-sync-engine/src/lib.rs"]),
            enabled("desktop"),
        )

    def test_desktop_crate_test_only_skips_installer(self) -> None:
        self.assertEqual(
            scope_for_paths(["desktop/crates/drive-sync-engine/tests/smoke.rs"]),
            enabled("desktop"),
        )

    def test_desktop_ui_change_skips_rust_job(self) -> None:
        self.assertEqual(
            scope_for_paths(["desktop/apps/drive-desktop/ui/app.js"]),
            enabled("installer"),
        )

    def test_desktop_tauri_config_change_skips_rust_job(self) -> None:
        self.assertEqual(
            scope_for_paths(["desktop/apps/drive-desktop/src-tauri/tauri.conf.json"]),
            enabled("installer"),
        )

    def test_desktop_app_rust_change_runs_rust_and_installer(self) -> None:
        self.assertEqual(
            scope_for_paths(["desktop/apps/drive-desktop/src-tauri/src/lib.rs"]),
            enabled("desktop", "installer"),
        )

    def test_update_signing_code_runs_rust_and_installer(self) -> None:
        self.assertEqual(
            scope_for_paths(["desktop/crates/drive-update/src/lib.rs"]),
            enabled("desktop", "installer"),
        )

    def test_desktop_app_manifest_routes_to_all_desktop_gates(self) -> None:
        self.assertEqual(
            scope_for_paths(["desktop/apps/drive-desktop/src-tauri/Cargo.toml"]),
            enabled("desktop", "installer", "rust_policy"),
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
            enabled("backend", "windows", "object_storage"),
        )

    def test_dev_compose_image_change_only_runs_image_policy(self) -> None:
        self.assertEqual(
            scope_for_paths(["backend/docker-compose.yml"]),
            enabled("object_storage"),
        )

    def test_workflow_change_only_runs_scope_router(self) -> None:
        self.assertEqual(
            scope_for_paths([".github/workflows/backend-ci.yml"]),
            enabled(),
        )

    def test_ci_script_change_only_runs_scope_router(self) -> None:
        self.assertEqual(
            scope_for_paths([".github/scripts/ci_scope.py"]),
            enabled(),
        )

    def test_docs_only_change_runs_no_expensive_gate(self) -> None:
        self.assertEqual(
            scope_for_paths(
                [
                    "backend/README.md",
                    "frontend/README.md",
                    "desktop/README.md",
                    "PROJECT_PLAN.md",
                    "PROJECT_PROGRESS.md",
                    "PROJECT_STAGE_STATUS.md",
                ]
            ),
            enabled(),
        )

    def test_release_notes_change_rebuilds_installer_artifact(self) -> None:
        self.assertEqual(
            scope_for_paths(["docs/release-v1.0.0.md"]),
            enabled("installer"),
        )

    def test_schedule_keeps_supply_chain_coverage(self) -> None:
        self.assertEqual(
            scope_for_event("schedule"),
            enabled("rust_policy", "object_storage"),
        )

    def test_manual_run_keeps_all_gates(self) -> None:
        self.assertEqual(
            scope_for_event("workflow_dispatch"),
            enabled(
                "backend",
                "frontend",
                "desktop",
                "installer",
                "rust_policy",
                "windows",
                "object_storage",
            ),
        )


if __name__ == "__main__":
    unittest.main()
