from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


HTTP_METHODS = frozenset(
    {"delete", "get", "head", "options", "patch", "post", "put", "trace"}
)
FRONTEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = FRONTEND_ROOT.parent
DEFAULT_OPENAPI_PATH = FRONTEND_ROOT / "openapi" / "openapi.json"
DEFAULT_REVISION_PATH = "frontend/openapi/openapi.json"


class OpenApiDocument:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = payload

    def resolve(self, value: Any) -> Any:
        current = value
        seen: set[str] = set()
        while isinstance(current, Mapping) and "$ref" in current:
            reference = current["$ref"]
            if not isinstance(reference, str) or not reference.startswith("#/"):
                raise ValueError(
                    f"Only local OpenAPI references are supported: {reference!r}"
                )
            if reference in seen:
                raise ValueError(f"Circular OpenAPI reference alias: {reference}")
            seen.add(reference)
            current = _resolve_json_pointer(self.payload, reference)
        return current


def _resolve_json_pointer(document: Any, reference: str) -> Any:
    current = document
    for raw_token in reference[2:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if token not in current:
                raise ValueError(f"OpenAPI reference does not exist: {reference}")
            current = current[token]
            continue
        if isinstance(current, Sequence) and not isinstance(current, (str, bytes)):
            try:
                current = current[int(token)]
            except (IndexError, ValueError) as exc:
                raise ValueError(
                    f"OpenAPI reference does not exist: {reference}"
                ) from exc
            continue
        raise ValueError(f"OpenAPI reference does not exist: {reference}")
    return current


def _load_json_text(text: str, label: str) -> OpenApiDocument:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError(f"{label} must contain a JSON object")
    if not isinstance(payload.get("paths"), Mapping):
        raise ValueError(f"{label} does not contain an OpenAPI paths object")
    return OpenApiDocument(payload)


def load_document(path: Path) -> OpenApiDocument:
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError(f"OpenAPI file does not exist: {resolved}")
    return _load_json_text(resolved.read_text(encoding="utf-8"), str(resolved))


def _run_git(repo_root: Path, arguments: Sequence[str], *, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "git command failed"
        raise ValueError(detail)
    return result.stdout


def _resolve_revision(repo_root: Path, revision: str) -> str:
    requested = revision.strip()
    if not requested:
        raise ValueError("A base revision is required")
    if requested.startswith("-"):
        raise ValueError("A base revision may not start with '-'.")
    if set(requested) == {"0"}:
        requested = "HEAD^"
    resolved = _run_git(
        repo_root,
        ["rev-parse", "--verify", f"{requested}^{{commit}}"],
    ).strip()
    if not resolved or any(
        character not in "0123456789abcdefABCDEF" for character in resolved
    ):
        raise ValueError(f"Git did not resolve a commit SHA for {requested!r}")
    return resolved


def _normalise_revision_path(path: str) -> str:
    candidate = path.replace("\\", "/").strip("/")
    parts = candidate.split("/")
    if (
        not candidate
        or Path(candidate).is_absolute()
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ValueError(f"Unsafe repository-relative OpenAPI path: {path!r}")
    return candidate


def load_revision_document(
    repo_root: Path,
    revision: str,
    revision_path: str = DEFAULT_REVISION_PATH,
    *,
    allow_missing: bool = False,
) -> OpenApiDocument | None:
    root = repo_root.resolve()
    path = _normalise_revision_path(revision_path)
    commit = _resolve_revision(root, revision)
    object_name = f"{commit}:{path}"
    exists = subprocess.run(
        ["git", "cat-file", "-e", object_name],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if exists.returncode != 0:
        if allow_missing:
            return None
        raise ValueError(f"OpenAPI baseline does not exist at {commit}:{path}")
    text = _run_git(root, ["show", object_name])
    return _load_json_text(text, f"{commit}:{path}")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return value
    return ()


def _object_shape(
    document: OpenApiDocument,
    schema: Any,
    seen: set[int] | None = None,
) -> tuple[dict[str, Any], set[str]]:
    resolved = document.resolve(schema)
    if not isinstance(resolved, Mapping):
        return {}, set()
    visited = set() if seen is None else seen
    identity = id(resolved)
    if identity in visited:
        return {}, set()
    visited.add(identity)

    properties: dict[str, Any] = {}
    required: set[str] = set()
    for branch in _sequence(resolved.get("allOf")):
        branch_properties, branch_required = _object_shape(document, branch, visited)
        properties.update(branch_properties)
        required.update(branch_required)

    for name, value in _mapping(resolved.get("properties")).items():
        if isinstance(name, str):
            properties[name] = value
    required.update(
        value for value in _sequence(resolved.get("required")) if isinstance(value, str)
    )
    return properties, required


def _schema_variants(document: OpenApiDocument, schema: Any) -> list[Any]:
    resolved = document.resolve(schema)
    if not isinstance(resolved, Mapping):
        return [resolved]
    for keyword in ("oneOf", "anyOf"):
        branches = [
            branch
            for branch in _sequence(resolved.get(keyword))
            if _mapping(document.resolve(branch)).get("type") != "null"
        ]
        if branches:
            return branches
    return [schema]


def _schema_signature(document: OpenApiDocument, schema: Any) -> tuple[Any, ...]:
    resolved = document.resolve(schema)
    if not isinstance(resolved, Mapping):
        return ("unknown",)
    properties, _ = _object_shape(document, schema)
    if properties:
        return ("object", *sorted(properties))
    schema_type = resolved.get("type")
    if schema_type == "array":
        return ("array", *_schema_signature(document, resolved.get("items")))
    return (schema_type, resolved.get("format"))


def _match_variants(
    base_document: OpenApiDocument,
    current_document: OpenApiDocument,
    base_variants: Sequence[Any],
    current_variants: Sequence[Any],
) -> list[tuple[Any, Any]]:
    available = list(current_variants)
    pairs: list[tuple[Any, Any]] = []
    for base_variant in base_variants:
        signature = _schema_signature(base_document, base_variant)
        match_index = next(
            (
                index
                for index, candidate in enumerate(available)
                if _schema_signature(current_document, candidate) == signature
            ),
            0 if available else -1,
        )
        if match_index < 0:
            continue
        pairs.append((base_variant, available.pop(match_index)))
    return pairs


def _compare_response_schema(
    base_document: OpenApiDocument,
    current_document: OpenApiDocument,
    base_schema: Any,
    current_schema: Any,
    location: str,
    changes: list[str],
    seen: set[tuple[int, int]],
    *,
    expand_variants: bool = True,
) -> None:
    if expand_variants:
        base_variants = _schema_variants(base_document, base_schema)
        current_variants = _schema_variants(current_document, current_schema)
        if len(base_variants) > 1 or len(current_variants) > 1:
            for base_variant, current_variant in _match_variants(
                base_document,
                current_document,
                base_variants,
                current_variants,
            ):
                _compare_response_schema(
                    base_document,
                    current_document,
                    base_variant,
                    current_variant,
                    location,
                    changes,
                    seen,
                    expand_variants=False,
                )
            return

    base_resolved = base_document.resolve(base_schema)
    current_resolved = current_document.resolve(current_schema)
    pair = (id(base_resolved), id(current_resolved))
    if pair in seen:
        return
    seen.add(pair)

    base_properties, _ = _object_shape(base_document, base_schema)
    current_properties, _ = _object_shape(current_document, current_schema)
    for name in sorted(base_properties.keys() - current_properties.keys()):
        changes.append(f"{location} field removed: {name}")
    for name in sorted(base_properties.keys() & current_properties.keys()):
        _compare_response_schema(
            base_document,
            current_document,
            base_properties[name],
            current_properties[name],
            f"{location}.{name}",
            changes,
            seen,
        )

    base_items = _mapping(base_resolved).get("items")
    current_items = _mapping(current_resolved).get("items")
    if base_items is not None and current_items is None:
        changes.append(f"{location} array item schema removed")
    elif base_items is not None:
        _compare_response_schema(
            base_document,
            current_document,
            base_items,
            current_items,
            f"{location}[]",
            changes,
            seen,
        )


def _compare_required_request_schema(
    base_document: OpenApiDocument,
    current_document: OpenApiDocument,
    base_schema: Any,
    current_schema: Any,
    location: str,
    changes: list[str],
    seen: set[tuple[int, int]],
    *,
    expand_variants: bool = True,
) -> None:
    if expand_variants:
        base_variants = _schema_variants(base_document, base_schema)
        current_variants = _schema_variants(current_document, current_schema)
        if len(base_variants) > 1 or len(current_variants) > 1:
            for base_variant, current_variant in _match_variants(
                base_document,
                current_document,
                base_variants,
                current_variants,
            ):
                _compare_required_request_schema(
                    base_document,
                    current_document,
                    base_variant,
                    current_variant,
                    location,
                    changes,
                    seen,
                    expand_variants=False,
                )
            return

    base_resolved = base_document.resolve(base_schema)
    current_resolved = current_document.resolve(current_schema)
    pair = (id(base_resolved), id(current_resolved))
    if pair in seen:
        return
    seen.add(pair)

    base_properties, base_required = _object_shape(base_document, base_schema)
    current_properties, current_required = _object_shape(
        current_document,
        current_schema,
    )
    for name in sorted(current_required - base_required):
        changes.append(f"{location} required field added: {name}")
    for name in sorted(base_properties.keys() & current_properties.keys()):
        _compare_required_request_schema(
            base_document,
            current_document,
            base_properties[name],
            current_properties[name],
            f"{location}.{name}",
            changes,
            seen,
        )

    base_items = _mapping(base_resolved).get("items")
    current_items = _mapping(current_resolved).get("items")
    if base_items is not None and current_items is not None:
        _compare_required_request_schema(
            base_document,
            current_document,
            base_items,
            current_items,
            f"{location}[]",
            changes,
            seen,
        )


def _parameter_map(
    document: OpenApiDocument,
    path_item: Mapping[str, Any],
    operation: Mapping[str, Any],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    parameters: dict[tuple[str, str], Mapping[str, Any]] = {}
    for raw_parameter in (
        *_sequence(path_item.get("parameters")),
        *_sequence(operation.get("parameters")),
    ):
        parameter = document.resolve(raw_parameter)
        if not isinstance(parameter, Mapping):
            continue
        name = parameter.get("name")
        location = parameter.get("in")
        if isinstance(name, str) and isinstance(location, str):
            parameters[(location, name)] = parameter
    return parameters


def _compare_required_parameters(
    base_document: OpenApiDocument,
    current_document: OpenApiDocument,
    base_path_item: Mapping[str, Any],
    current_path_item: Mapping[str, Any],
    base_operation: Mapping[str, Any],
    current_operation: Mapping[str, Any],
    operation_label: str,
    changes: list[str],
) -> None:
    base_parameters = _parameter_map(
        base_document,
        base_path_item,
        base_operation,
    )
    current_parameters = _parameter_map(
        current_document,
        current_path_item,
        current_operation,
    )
    for key, current_parameter in sorted(current_parameters.items()):
        if not bool(current_parameter.get("required")):
            continue
        base_parameter = base_parameters.get(key)
        if base_parameter is None or not bool(base_parameter.get("required")):
            location, name = key
            changes.append(
                f"{operation_label} required {location} parameter added: {name}"
            )


def _compare_request_body(
    base_document: OpenApiDocument,
    current_document: OpenApiDocument,
    base_operation: Mapping[str, Any],
    current_operation: Mapping[str, Any],
    operation_label: str,
    changes: list[str],
) -> None:
    base_body = base_document.resolve(base_operation.get("requestBody", {}))
    current_body = current_document.resolve(current_operation.get("requestBody", {}))
    base_body_mapping = _mapping(base_body)
    current_body_mapping = _mapping(current_body)
    if not current_body_mapping:
        return
    if bool(current_body_mapping.get("required")) and not bool(
        base_body_mapping.get("required")
    ):
        changes.append(f"{operation_label} request body became required")

    base_content = _mapping(base_body_mapping.get("content"))
    current_content = _mapping(current_body_mapping.get("content"))
    for media_type, current_media in current_content.items():
        current_schema = _mapping(current_media).get("schema")
        if current_schema is None:
            continue
        base_schema = _mapping(base_content.get(media_type)).get("schema", {})
        _compare_required_request_schema(
            base_document,
            current_document,
            base_schema,
            current_schema,
            f"{operation_label} request {media_type} $",
            changes,
            set(),
        )


def _compare_responses(
    base_document: OpenApiDocument,
    current_document: OpenApiDocument,
    base_operation: Mapping[str, Any],
    current_operation: Mapping[str, Any],
    operation_label: str,
    changes: list[str],
) -> None:
    base_responses = _mapping(base_operation.get("responses"))
    current_responses = _mapping(current_operation.get("responses"))
    for status, raw_base_response in base_responses.items():
        if status not in current_responses:
            changes.append(f"{operation_label} response removed: {status}")
            continue
        base_response = _mapping(base_document.resolve(raw_base_response))
        current_response = _mapping(current_document.resolve(current_responses[status]))
        base_content = _mapping(base_response.get("content"))
        current_content = _mapping(current_response.get("content"))
        for media_type, base_media in base_content.items():
            if media_type not in current_content:
                changes.append(
                    f"{operation_label} response {status} media type removed: "
                    f"{media_type}"
                )
                continue
            base_schema = _mapping(base_media).get("schema")
            current_schema = _mapping(current_content[media_type]).get("schema")
            if base_schema is None:
                continue
            if current_schema is None:
                changes.append(
                    f"{operation_label} response {status} {media_type} schema removed"
                )
                continue
            _compare_response_schema(
                base_document,
                current_document,
                base_schema,
                current_schema,
                f"{operation_label} response {status} {media_type} $",
                changes,
                set(),
            )


def find_breaking_changes(
    base_document: OpenApiDocument,
    current_document: OpenApiDocument,
) -> list[str]:
    changes: list[str] = []
    base_paths = _mapping(base_document.payload.get("paths"))
    current_paths = _mapping(current_document.payload.get("paths"))
    for path, raw_base_path_item in base_paths.items():
        if path not in current_paths:
            changes.append(f"path removed: {path}")
            continue
        base_path_item = _mapping(base_document.resolve(raw_base_path_item))
        current_path_item = _mapping(current_document.resolve(current_paths[path]))
        for method in sorted(HTTP_METHODS & base_path_item.keys()):
            operation_label = f"{method.upper()} {path}"
            if method not in current_path_item:
                changes.append(f"{operation_label} operation removed")
                continue
            base_operation = _mapping(base_document.resolve(base_path_item[method]))
            current_operation = _mapping(
                current_document.resolve(current_path_item[method])
            )
            _compare_required_parameters(
                base_document,
                current_document,
                base_path_item,
                current_path_item,
                base_operation,
                current_operation,
                operation_label,
                changes,
            )
            _compare_request_body(
                base_document,
                current_document,
                base_operation,
                current_operation,
                operation_label,
                changes,
            )
            _compare_responses(
                base_document,
                current_document,
                base_operation,
                current_operation,
                operation_label,
                changes,
            )
    return sorted(set(changes))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare a base OpenAPI archive with the current archive and reject "
            "backward-incompatible removals or new required request inputs."
        )
    )
    base = parser.add_mutually_exclusive_group()
    base.add_argument("--base-file", type=Path)
    base.add_argument("--base-revision")
    parser.add_argument("--base-path", default=DEFAULT_REVISION_PATH)
    parser.add_argument("--current", type=Path, default=DEFAULT_OPENAPI_PATH)
    parser.add_argument("--repo-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument(
        "--allow-missing-base",
        action="store_true",
        help="Allow the first revision that introduces the OpenAPI archive.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        current_document = load_document(args.current)
        base_revision = args.base_revision or os.environ.get(
            "OPENAPI_BASE_REVISION",
            "",
        )
        if args.base_file is not None:
            base_document = load_document(args.base_file)
            base_label = str(args.base_file.resolve())
        elif base_revision:
            base_document = load_revision_document(
                args.repo_root,
                base_revision,
                args.base_path,
                allow_missing=args.allow_missing_base,
            )
            base_label = f"{base_revision}:{args.base_path}"
        else:
            try:
                base_revision = _resolve_revision(args.repo_root, "HEAD^")
            except ValueError:
                if not args.allow_missing_base:
                    parser.error(
                        "provide --base-file, --base-revision, or OPENAPI_BASE_REVISION"
                    )
                base_revision = ""
            if base_revision:
                base_document = load_revision_document(
                    args.repo_root,
                    base_revision,
                    args.base_path,
                    allow_missing=args.allow_missing_base,
                )
                base_label = f"{base_revision}:{args.base_path}"
            else:
                base_document = None
                base_label = f"HEAD^:{args.base_path}"

        if base_document is None:
            print(
                f"OpenAPI baseline is not present at {base_label}; bootstrap accepted."
            )
            return 0
        changes = find_breaking_changes(base_document, current_document)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        print(f"OpenAPI compatibility check failed: {exc}", file=sys.stderr)
        return 2

    if changes:
        print(
            f"OpenAPI breaking changes detected against {base_label}:",
            file=sys.stderr,
        )
        for change in changes:
            print(f"- {change}", file=sys.stderr)
        return 1
    print(f"OpenAPI compatibility check passed against {base_label}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
