from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIRECTORY = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIRECTORY))

from check_openapi_breaking import (  # noqa: E402
    OpenApiDocument,
    find_breaking_changes,
    load_revision_document,
)


def _document(paths: dict, schemas: dict | None = None) -> OpenApiDocument:
    return OpenApiDocument(
        {
            "openapi": "3.1.0",
            "info": {"title": "fixture", "version": "1.0.0"},
            "paths": paths,
            "components": {"schemas": schemas or {}},
        }
    )


def _json_response(schema: dict) -> dict:
    return {
        "description": "ok",
        "content": {"application/json": {"schema": schema}},
    }


class OpenApiBreakingChangeTests(unittest.TestCase):
    def test_removed_path_is_breaking(self) -> None:
        base = _document(
            {"/removed": {"get": {"responses": {"200": _json_response({})}}}}
        )
        current = _document({})

        self.assertIn("path removed: /removed", find_breaking_changes(base, current))

    def test_removed_operation_is_breaking(self) -> None:
        base = _document(
            {
                "/items": {
                    "get": {"responses": {"200": _json_response({})}},
                    "post": {"responses": {"200": _json_response({})}},
                }
            }
        )
        current = _document(
            {"/items": {"get": {"responses": {"200": _json_response({})}}}}
        )

        self.assertIn(
            "POST /items operation removed",
            find_breaking_changes(base, current),
        )

    def test_removed_response_field_is_breaking(self) -> None:
        base = _document(
            {
                "/items": {
                    "get": {
                        "responses": {
                            "200": _json_response({"$ref": "#/components/schemas/Item"})
                        }
                    }
                }
            },
            {
                "Item": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                    },
                }
            },
        )
        current_payload = copy.deepcopy(base.payload)
        del current_payload["components"]["schemas"]["Item"]["properties"]["name"]
        current = OpenApiDocument(current_payload)

        self.assertIn(
            "GET /items response 200 application/json $ field removed: name",
            find_breaking_changes(base, current),
        )

    def test_added_required_request_field_is_breaking(self) -> None:
        request_schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "mode": {"type": "string"},
            },
            "required": ["name"],
        }
        base = _document(
            {
                "/items": {
                    "post": {
                        "requestBody": {
                            "content": {"application/json": {"schema": request_schema}}
                        },
                        "responses": {"200": _json_response({})},
                    }
                }
            }
        )
        current_payload = copy.deepcopy(base.payload)
        current_payload["paths"]["/items"]["post"]["requestBody"]["content"][
            "application/json"
        ]["schema"]["required"].append("mode")
        current = OpenApiDocument(current_payload)

        self.assertIn(
            "POST /items request application/json $ required field added: mode",
            find_breaking_changes(base, current),
        )

    def test_optional_request_and_response_additions_are_compatible(self) -> None:
        base = _document(
            {
                "/items": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"name": {"type": "string"}},
                                        "required": ["name"],
                                    }
                                }
                            }
                        },
                        "responses": {
                            "200": _json_response(
                                {
                                    "type": "object",
                                    "properties": {"id": {"type": "string"}},
                                }
                            )
                        },
                    }
                }
            }
        )
        current_payload = copy.deepcopy(base.payload)
        request_properties = current_payload["paths"]["/items"]["post"]["requestBody"][
            "content"
        ]["application/json"]["schema"]["properties"]
        request_properties["note"] = {"type": "string"}
        response_properties = current_payload["paths"]["/items"]["post"]["responses"][
            "200"
        ]["content"]["application/json"]["schema"]["properties"]
        response_properties["name"] = {"type": "string"}
        current = OpenApiDocument(current_payload)

        self.assertEqual(find_breaking_changes(base, current), [])

    def test_loads_baseline_from_git_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            baseline = repository / "frontend" / "openapi" / "openapi.json"
            baseline.parent.mkdir(parents=True)
            baseline.write_text(
                json.dumps(
                    {
                        "openapi": "3.1.0",
                        "info": {"title": "fixture", "version": "1.0.0"},
                        "paths": {"/ping": {}},
                    }
                ),
                encoding="utf-8",
            )
            for arguments in (
                ("init",),
                ("config", "user.email", "ci@example.invalid"),
                ("config", "user.name", "CI"),
                ("add", "frontend/openapi/openapi.json"),
                ("commit", "-m", "baseline"),
            ):
                subprocess.run(
                    ["git", *arguments],
                    cwd=repository,
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                )

            loaded = load_revision_document(repository, "HEAD")

        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertIn("/ping", loaded.payload["paths"])


if __name__ == "__main__":
    unittest.main()
