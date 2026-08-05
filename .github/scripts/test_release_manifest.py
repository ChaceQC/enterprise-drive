#!/usr/bin/env python3
"""Focused regression tests for the release artifact manifest."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from release_manifest import (
    DEFAULT_CHECKSUMS_NAME,
    DEFAULT_MANIFEST_NAME,
    RequiredArtifact,
    build_manifest,
    verify_manifest,
    write_manifest,
)


class ReleaseManifestTests(unittest.TestCase):
    def test_builds_and_verifies_deterministic_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            artifact_dir = Path(temporary_directory)
            (artifact_dir / "enterprise-drive-1.0.0-setup.exe").write_bytes(
                b"installer"
            )
            (artifact_dir / "openapi.json").write_text("{}", encoding="utf-8")

            manifest = build_manifest(
                input_dir=artifact_dir,
                version="1.0.0",
                git_commit="a2ac96a",
                generated_at="2026-08-05T00:00:00+00:00",
                requirements=[
                    RequiredArtifact("windows_installer", "*-setup.exe"),
                    RequiredArtifact("openapi", "openapi.json"),
                ],
                excluded_names={DEFAULT_MANIFEST_NAME, DEFAULT_CHECKSUMS_NAME},
            )
            manifest_path, checksums_path = write_manifest(
                input_dir=artifact_dir,
                manifest=manifest,
            )

            self.assertEqual(manifest["artifact_count"], 2)
            self.assertEqual(
                manifest["roles"]["windows_installer"],
                ["enterprise-drive-1.0.0-setup.exe"],
            )
            self.assertEqual(
                json.loads(manifest_path.read_text(encoding="utf-8"))["tag"],
                "v1.0.0",
            )
            self.assertEqual(
                len(checksums_path.read_text(encoding="utf-8").splitlines()), 2
            )
            verify_manifest(artifact_dir, manifest_path)

    def test_rejects_missing_required_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            artifact_dir = Path(temporary_directory)
            (artifact_dir / "openapi.json").write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "windows_installer"):
                build_manifest(
                    input_dir=artifact_dir,
                    version="1.0.0",
                    git_commit="a2ac96a",
                    requirements=[
                        RequiredArtifact("windows_installer", "*-setup.exe"),
                    ],
                )

    def test_detects_tampered_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            artifact_dir = Path(temporary_directory)
            artifact = artifact_dir / "openapi.json"
            artifact.write_text("{}", encoding="utf-8")
            manifest = build_manifest(
                input_dir=artifact_dir,
                version="1.0.0",
                git_commit="a2ac96a",
                requirements=[RequiredArtifact("openapi", "openapi.json")],
            )
            manifest_path, _ = write_manifest(
                input_dir=artifact_dir,
                manifest=manifest,
            )
            artifact.write_text("[]", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                verify_manifest(artifact_dir, manifest_path)

    def test_detects_tampered_checksums(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            artifact_dir = Path(temporary_directory)
            (artifact_dir / "openapi.json").write_text("{}", encoding="utf-8")
            manifest = build_manifest(
                input_dir=artifact_dir,
                version="1.0.0",
                git_commit="a2ac96a",
                requirements=[RequiredArtifact("openapi", "openapi.json")],
            )
            manifest_path, checksums_path = write_manifest(
                input_dir=artifact_dir,
                manifest=manifest,
            )
            checksums_path.write_text(
                "0" * 64 + "  openapi.json\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError,
                "checksums do not match",
            ):
                verify_manifest(artifact_dir, manifest_path)

    def test_rejects_absolute_and_drive_qualified_artifact_paths(self) -> None:
        unsafe_paths = (
            "/outside.bin",
            r"C:\outside.bin",
            "C:/outside.bin",
            r"\\server\share\outside.bin",
        )
        for unsafe_path in unsafe_paths:
            with (
                self.subTest(path=unsafe_path),
                tempfile.TemporaryDirectory() as temporary_directory,
            ):
                artifact_dir = Path(temporary_directory)
                manifest_path = artifact_dir / DEFAULT_MANIFEST_NAME
                manifest_path.write_text(
                    json.dumps(
                        {
                            "artifacts": [
                                {
                                    "path": unsafe_path,
                                    "size": 0,
                                    "sha256": "",
                                }
                            ]
                        }
                    ),
                    encoding="utf-8",
                )

                with self.assertRaisesRegex(ValueError, "unsafe artifact path"):
                    verify_manifest(artifact_dir, manifest_path)

    def test_rejects_case_insensitive_duplicate_artifact_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            artifact_dir = Path(temporary_directory)
            artifact = artifact_dir / "openapi.json"
            artifact.write_text("{}", encoding="utf-8")
            manifest = build_manifest(
                input_dir=artifact_dir,
                version="1.0.0",
                git_commit="a2ac96a",
                requirements=[RequiredArtifact("openapi", "openapi.json")],
            )
            duplicate = dict(manifest["artifacts"][0])
            duplicate["path"] = "OPENAPI.JSON"
            manifest["artifacts"].append(duplicate)
            manifest_path = artifact_dir / DEFAULT_MANIFEST_NAME
            manifest_path.write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError,
                "case-insensitive duplicate artifact path",
            ):
                verify_manifest(artifact_dir, manifest_path)


if __name__ == "__main__":
    unittest.main()
