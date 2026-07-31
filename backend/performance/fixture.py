from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx


@dataclass(frozen=True)
class BenchmarkFixture:
    schema_version: str
    base_url: str
    tenant_slug: str
    space_id: str
    parent_id: str
    fixture_root_id: str | None
    folder_ids: list[str]
    search_query: str
    created_space: bool
    created_at: str


def _csrf_token(client: httpx.Client, response: httpx.Response) -> str:
    token = response.cookies.get("drive_csrf") or client.cookies.get("drive_csrf")
    if not token:
        raise RuntimeError("登录响应没有 drive_csrf cookie")
    return str(token)


def _login(client: httpx.Client, tenant_slug: str, username: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={
            "tenant_slug": tenant_slug,
            "username": username,
            "password": password,
        },
    )
    response.raise_for_status()
    return _csrf_token(client, response)


def _request_json(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    response = client.request(method, path, headers=headers, **kwargs)
    if response.is_error:
        raise RuntimeError(
            f"{method} {path} failed: status={response.status_code} body={response.text[:500]}"
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"{method} {path} 返回的 JSON 不是对象")
    return payload


def list_spaces(
    client: httpx.Client,
    *,
    tenant_slug: str,
    username: str,
    password: str,
) -> list[dict[str, Any]]:
    _login(client, tenant_slug, username, password)
    response = client.get("/api/v1/spaces", params={"page_size": 100})
    response.raise_for_status()
    payload = response.json()
    items = payload.get("items")
    if not isinstance(items, list):
        raise RuntimeError("空间列表响应缺少 items")
    return [item for item in items if isinstance(item, dict)]


def prepare_fixture(
    *,
    base_url: str,
    tenant_slug: str,
    username: str,
    password: str,
    folder_count: int,
    space_id: str | None = None,
    parent_id: str | None = None,
    create_space: bool = False,
    timeout_seconds: float = 30.0,
) -> BenchmarkFixture:
    if folder_count < 1:
        raise ValueError("folder_count 必须大于 0")
    normalized_base_url = base_url.rstrip("/")
    search_query = f"perf{secrets.token_hex(4)}"
    with httpx.Client(base_url=normalized_base_url, timeout=timeout_seconds) as client:
        csrf = _login(client, tenant_slug, username, password)
        if create_space and space_id:
            raise ValueError("--create-space 不能与 --space-id 同时使用")
        if create_space:
            selected = _request_json(
                client,
                "POST",
                "/api/v1/spaces",
                headers={"X-CSRF-Token": csrf},
                json={
                    "slug": f"perf-{secrets.token_hex(6)}",
                    "name": "BE-029 性能基准",
                    "space_type": "team",
                },
            )
            spaces = [selected]
        elif space_id:
            spaces = [
                item
                for item in list_spaces(
                    client,
                    tenant_slug=tenant_slug,
                    username=username,
                    password=password,
                )
                if str(item.get("id")) == space_id
            ]
        else:
            spaces = list_spaces(
                client,
                tenant_slug=tenant_slug,
                username=username,
                password=password,
            )
        if not spaces:
            raise RuntimeError("没有可用空间；请先创建空间或传入 --space-id")
        selected = spaces[0]
        selected_space_id = str(selected["id"])
        selected_parent_id = parent_id or str(selected.get("root_node_id") or "")
        if not selected_parent_id:
            root_response = _request_json(
                client,
                "GET",
                "/api/v1/files",
                params={"space_id": selected_space_id, "page_size": 1},
            )
            selected_parent_id = str(root_response.get("parent_id") or "")
        if not selected_parent_id:
            raise RuntimeError("无法从空间文件列表解析 root_node_id，请显式传入 --parent-id")

        fixture_root_id: str | None = None
        folder_ids: list[str] = []
        try:
            fixture_root = _request_json(
                client,
                "POST",
                "/api/v1/files/folders",
                headers={"X-CSRF-Token": csrf},
                json={
                    "space_id": selected_space_id,
                    "parent_id": selected_parent_id,
                    "name": f"{search_query}-root",
                },
            )
            fixture_root_id = str(fixture_root["id"])
            for index in range(folder_count):
                payload = _request_json(
                    client,
                    "POST",
                    "/api/v1/files/folders",
                    headers={"X-CSRF-Token": csrf},
                    json={
                        "space_id": selected_space_id,
                        "parent_id": fixture_root_id,
                        "name": f"{search_query}-folder-{index:06d}",
                    },
                )
                folder_ids.append(str(payload["id"]))
        except Exception as prepare_error:
            if fixture_root_id is not None:
                try:
                    _delete_and_purge_node(
                        client,
                        node_id=fixture_root_id,
                        csrf=csrf,
                    )
                except Exception as cleanup_error:
                    raise RuntimeError(
                        "准备性能 fixture 失败，且自动清理已创建根目录失败: "
                        f"prepare={prepare_error!r} cleanup={cleanup_error!r}"
                    ) from prepare_error
            raise

    if fixture_root_id is None:
        raise RuntimeError("性能 fixture 根目录未创建")

    return BenchmarkFixture(
        schema_version="BE-029/1",
        base_url=normalized_base_url,
        tenant_slug=tenant_slug,
        space_id=selected_space_id,
        parent_id=selected_parent_id,
        fixture_root_id=fixture_root_id,
        folder_ids=folder_ids,
        search_query=search_query,
        created_space=create_space,
        created_at=datetime.now(UTC).isoformat(),
    )


def cleanup_fixture(
    fixture: BenchmarkFixture,
    *,
    username: str,
    password: str,
    timeout_seconds: float = 30.0,
) -> int:
    with httpx.Client(base_url=fixture.base_url, timeout=timeout_seconds) as client:
        csrf = _login(client, fixture.tenant_slug, username, password)
        if fixture.fixture_root_id:
            return _delete_and_purge_node(
                client,
                node_id=fixture.fixture_root_id,
                csrf=csrf,
            )

        removed = 0
        for node_id in reversed(fixture.folder_ids):
            removed += _delete_and_purge_node(
                client,
                node_id=node_id,
                csrf=csrf,
            )
    return removed


def _delete_and_purge_node(
    client: httpx.Client,
    *,
    node_id: str,
    csrf: str,
) -> int:
    headers = {"X-CSRF-Token": csrf}
    delete_response = client.delete(f"/api/v1/files/{node_id}", headers=headers)
    if delete_response.status_code not in (200, 404):
        raise RuntimeError(
            f"删除性能 fixture 失败: node={node_id} status={delete_response.status_code} "
            f"body={delete_response.text[:500]}"
        )

    purge_response = client.delete(f"/api/v1/files/{node_id}/purge", headers=headers)
    if purge_response.status_code == 404:
        return 0
    if purge_response.status_code != 200:
        raise RuntimeError(
            f"彻底清理性能 fixture 失败: node={node_id} status={purge_response.status_code} "
            f"body={purge_response.text[:500]}"
        )
    payload = purge_response.json()
    return int(payload.get("purged_count") or 0)


def write_fixture(fixture: BenchmarkFixture, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(fixture), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_fixture(path: Path) -> BenchmarkFixture:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("fixture JSON 必须是对象")
    return BenchmarkFixture(
        schema_version=str(payload["schema_version"]),
        base_url=str(payload["base_url"]),
        tenant_slug=str(payload["tenant_slug"]),
        space_id=str(payload["space_id"]),
        parent_id=str(payload["parent_id"]),
        fixture_root_id=(
            str(payload["fixture_root_id"]) if payload.get("fixture_root_id") else None
        ),
        folder_ids=[str(value) for value in payload["folder_ids"]],
        search_query=str(payload["search_query"]),
        created_space=bool(payload.get("created_space", False)),
        created_at=str(payload["created_at"]),
    )


def main(argv: list[str] | None = None) -> int:
    from performance.fixture_cli import main as cli_main

    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
