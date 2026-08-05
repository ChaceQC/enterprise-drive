#!/usr/bin/env python3
"""Build and verify deterministic SHA-256 manifests for release artifacts."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import mimetypes
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

VERSION_PATTERN = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)$"
)
DEFAULT_MANIFEST_NAME = "release-manifest.json"
DEFAULT_CHECKSUMS_NAME = "SHA256SUMS"


@dataclass(frozen=True)
class RequiredArtifact:
    role: str
    pattern: str


def parse_required_artifact(value: str) -> RequiredArtifact:
    role, separator, pattern = value.partition("=")
    if not separator or not role.strip() or not pattern.strip():
        raise ValueError("required artifacts must use ROLE=GLOB")
    if "/" in role or "\\" in role:
        raise ValueError("artifact roles may not contain path separators")
    return RequiredArtifact(
        role=role.strip(), pattern=pattern.replace("\\", "/").strip()
    )


def validate_version(version: str) -> str:
    if VERSION_PATTERN.fullmatch(version) is None:
        raise ValueError(f"release version must use X.Y.Z: {version!r}")
    return version


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def collect_artifacts(
    input_dir: Path,
    *,
    excluded_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    root = input_dir.resolve()
    if not root.is_dir():
        raise ValueError(f"release artifact directory does not exist: {root}")
    excluded = excluded_names or set()
    artifacts: list[dict[str, Any]] = []
    casefolded_paths: set[str] = set()
    for path in sorted(
        root.rglob("*"), key=lambda candidate: candidate.as_posix().casefold()
    ):
        if path.is_symlink():
            raise ValueError(
                f"release artifacts may not contain symbolic links: {path}"
            )
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in excluded:
            continue
        folded = relative.casefold()
        if folded in casefolded_paths:
            raise ValueError(f"case-insensitive duplicate artifact path: {relative}")
        casefolded_paths.add(folded)
        media_type = mimetypes.guess_type(relative)[0] or "application/octet-stream"
        artifacts.append(
            {
                "path": relative,
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
                "media_type": media_type,
            }
        )
    if not artifacts:
        raise ValueError(f"release artifact directory is empty: {root}")
    return artifacts


def match_required_artifacts(
    artifacts: list[dict[str, Any]],
    requirements: list[RequiredArtifact],
) -> dict[str, list[str]]:
    paths = [str(artifact["path"]) for artifact in artifacts]
    matched: dict[str, list[str]] = {}
    for requirement in requirements:
        matches = sorted(
            path for path in paths if fnmatch.fnmatchcase(path, requirement.pattern)
        )
        if not matches:
            raise ValueError(
                f"required release artifact is missing: {requirement.role}={requirement.pattern}"
            )
        matched[requirement.role] = matches
    return matched


def build_manifest(
    *,
    input_dir: Path,
    version: str,
    git_commit: str,
    requirements: list[RequiredArtifact],
    generated_at: str | None = None,
    excluded_names: set[str] | None = None,
) -> dict[str, Any]:
    release_version = validate_version(version)
    commit = git_commit.strip()
    if not re.fullmatch(r"[0-9a-fA-F]{7,64}", commit):
        raise ValueError(
            "git commit must be a 7 to 64 character hexadecimal identifier"
        )
    artifacts = collect_artifacts(input_dir, excluded_names=excluded_names)
    roles = match_required_artifacts(artifacts, requirements)
    timestamp = generated_at or datetime.now(UTC).isoformat()
    return {
        "schema_version": "REL-005/1",
        "version": release_version,
        "tag": f"v{release_version}",
        "git_commit": commit.lower(),
        "generated_at": timestamp,
        "artifact_count": len(artifacts),
        "roles": roles,
        "artifacts": artifacts,
    }


def render_checksums(manifest: dict[str, Any]) -> str:
    return "".join(
        f"{artifact['sha256']}  {artifact['path']}\n"
        for artifact in manifest["artifacts"]
    )


def write_manifest(
    *,
    input_dir: Path,
    manifest: dict[str, Any],
    manifest_name: str = DEFAULT_MANIFEST_NAME,
    checksums_name: str = DEFAULT_CHECKSUMS_NAME,
) -> tuple[Path, Path]:
    manifest_path = input_dir / manifest_name
    checksums_path = input_dir / checksums_name
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    checksums_path.write_text(
        render_checksums(manifest),
        encoding="utf-8",
        newline="\n",
    )
    return manifest_path, checksums_path


def _validate_manifest_artifact_path(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(
            f"release manifest contains an unsafe artifact path: {value!r}"
        )
    posix_path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if (
        "\\" in value
        or posix_path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or bool(windows_path.root)
        or ".." in posix_path.parts
        or posix_path.as_posix() != value
    ):
        raise ValueError(
            f"release manifest contains an unsafe artifact path: {value!r}"
        )
    return value


def verify_manifest(input_dir: Path, manifest_path: Path) -> None:
    root = input_dir.resolve()
    resolved_manifest_path = manifest_path.resolve()
    try:
        resolved_manifest_path.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            f"release manifest must be inside the artifact directory: {manifest_path}"
        ) from exc
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError(f"release manifest is missing: {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("artifacts"), list):
        raise ValueError("release manifest does not contain an artifacts list")
    declared_paths: set[str] = set()
    declared_casefolded_paths: dict[str, str] = {}
    declared_artifacts: list[tuple[dict[str, Any], str]] = []
    for artifact in payload["artifacts"]:
        if not isinstance(artifact, dict):
            raise ValueError("release manifest contains an invalid artifact entry")
        relative = _validate_manifest_artifact_path(artifact.get("path"))
        folded = relative.casefold()
        previous = declared_casefolded_paths.get(folded)
        if previous is not None:
            raise ValueError(
                "release manifest contains a case-insensitive duplicate "
                f"artifact path: {previous!r}, {relative!r}"
            )
        declared_casefolded_paths[folded] = relative
        declared_paths.add(relative)
        declared_artifacts.append((artifact, relative))

    for artifact, relative in declared_artifacts:
        path = root.joinpath(*PurePosixPath(relative).parts)
        resolved_path = path.resolve()
        try:
            resolved_path.relative_to(root)
        except ValueError as exc:
            raise ValueError(
                f"release manifest contains an unsafe artifact path: {relative!r}"
            ) from exc
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"release artifact is missing: {relative}")
        if path.stat().st_size != int(artifact.get("size", -1)):
            raise ValueError(f"release artifact size mismatch: {relative}")
        if sha256_file(path) != str(artifact.get("sha256", "")).lower():
            raise ValueError(f"release artifact SHA-256 mismatch: {relative}")

    actual_paths: set[str] = set()
    actual_casefolded_paths: dict[str, str] = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(
                f"release artifacts may not contain symbolic links: {path}"
            )
        if not path.is_file() or path.resolve() == manifest_path.resolve():
            continue
        relative = path.relative_to(root).as_posix()
        if relative == DEFAULT_CHECKSUMS_NAME:
            continue
        folded = relative.casefold()
        previous = actual_casefolded_paths.get(folded)
        if previous is not None:
            raise ValueError(
                "release artifact inventory contains a case-insensitive duplicate "
                f"path: {previous!r}, {relative!r}"
            )
        actual_casefolded_paths[folded] = relative
        actual_paths.add(relative)
    if actual_paths != declared_paths:
        missing = sorted(declared_paths - actual_paths)
        unexpected = sorted(actual_paths - declared_paths)
        raise ValueError(
            f"release artifact inventory mismatch: missing={missing}, unexpected={unexpected}"
        )

    checksums_path = root / DEFAULT_CHECKSUMS_NAME
    if checksums_path.is_symlink() or not checksums_path.is_file():
        raise ValueError(f"release checksums are missing: {checksums_path}")
    expected_checksums = render_checksums(payload)
    actual_checksums = checksums_path.read_text(encoding="utf-8")
    if actual_checksums != expected_checksums:
        raise ValueError("release checksums do not match the release manifest")


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--input-dir", type=Path, required=True)
    build_parser.add_argument("--version", required=True)
    build_parser.add_argument("--git-commit", required=True)
    build_parser.add_argument("--generated-at")
    build_parser.add_argument("--require", action="append", default=[])

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--input-dir", type=Path, required=True)
    verify_parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(DEFAULT_MANIFEST_NAME),
    )

    args = parser.parse_args()
    try:
        if args.command == "build":
            requirements = [parse_required_artifact(value) for value in args.require]
            excluded = {DEFAULT_MANIFEST_NAME, DEFAULT_CHECKSUMS_NAME}
            manifest = build_manifest(
                input_dir=args.input_dir,
                version=args.version,
                git_commit=args.git_commit,
                requirements=requirements,
                generated_at=args.generated_at,
                excluded_names=excluded,
            )
            manifest_path, checksums_path = write_manifest(
                input_dir=args.input_dir,
                manifest=manifest,
            )
            print(f"Release manifest written: {manifest_path}")
            print(f"Release checksums written: {checksums_path}")
            return 0

        manifest_path = args.manifest
        if not manifest_path.is_absolute():
            manifest_path = args.input_dir / manifest_path
        verify_manifest(args.input_dir, manifest_path)
        print(f"Release manifest verified: {manifest_path}")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
