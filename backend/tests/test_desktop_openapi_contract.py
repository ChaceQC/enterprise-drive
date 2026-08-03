from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.main import create_app
from tests.helpers import settings as settings

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = REPOSITORY_ROOT / "desktop" / "contracts" / "sprint7-openapi.json"
SPRINT8_CONTRACT_PATH = REPOSITORY_ROOT / "desktop" / "contracts" / "sprint8-openapi.json"


def _operation_keys(openapi: dict[str, Any]) -> set[tuple[str, str]]:
    methods = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
    return {
        (method.upper(), path)
        for path, item in openapi["paths"].items()
        for method in item
        if method in methods
    }


def test_sprint7_contract_operations_and_schema_properties(
    settings: Settings,
) -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    openapi = create_app(settings).openapi()

    assert openapi["info"]["version"] == contract["version"]
    expected_operations = {(method, path) for method, path in contract["operations"]}
    assert expected_operations <= _operation_keys(openapi)

    schemas = openapi["components"]["schemas"]
    for schema_name, properties in contract["required_schema_properties"].items():
        assert schema_name in schemas
        available = set(schemas[schema_name]["properties"])
        assert set(properties) <= available


def test_sprint8_version_target_contract(
    settings: Settings,
) -> None:
    contract = json.loads(SPRINT8_CONTRACT_PATH.read_text(encoding="utf-8"))
    openapi = create_app(settings).openapi()

    assert openapi["info"]["version"] == contract["version"]
    expected_operations = {(method, path) for method, path in contract["operations"]}
    assert expected_operations <= _operation_keys(openapi)

    schemas = openapi["components"]["schemas"]
    for schema_name, properties in contract["required_schema_properties"].items():
        assert schema_name in schemas
        available = set(schemas[schema_name]["properties"])
        assert set(properties) <= available
