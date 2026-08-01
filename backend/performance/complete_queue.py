from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
from collections import deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any

import httpx

from performance.fixture import BenchmarkFixture

COMPLETE_QUEUE_SCHEMA = "BE-029-complete/1"


@dataclass(frozen=True)
class PreparedCompleteItem:
    session_id: str
    etag: str
    size_bytes: int


@dataclass(frozen=True)
class PreparedCompleteQueue:
    schema_version: str
    base_url: str
    tenant_slug: str
    space_id: str
    parent_id: str
    size_bytes: int
    items: list[PreparedCompleteItem]
    created_at: str


@dataclass
class CompleteQueueRuntime:
    items: deque[PreparedCompleteItem]
    lock: Lock
    total: int
    finished: int = 0
    quit_requested: bool = False


@lru_cache(maxsize=4)
def load_complete_queue_runtime(queue_path: str) -> CompleteQueueRuntime:
    queue = read_complete_queue(Path(queue_path))
    return CompleteQueueRuntime(
        items=deque(queue.items),
        lock=Lock(),
        total=len(queue.items),
    )


def take_prepared_complete_item(queue_path: str) -> PreparedCompleteItem | None:
    runtime = load_complete_queue_runtime(queue_path)
    with runtime.lock:
        return runtime.items.popleft() if runtime.items else None


def mark_prepared_complete_item_finished(queue_path: str) -> bool:
    runtime = load_complete_queue_runtime(queue_path)
    with runtime.lock:
        runtime.finished += 1
        if runtime.finished >= runtime.total and not runtime.quit_requested:
            runtime.quit_requested = True
            return True
        return False


def prepare_complete_queue(
    *,
    fixture: BenchmarkFixture,
    session_token: str,
    csrf_token: str,
    count: int,
    size_bytes: int,
    concurrency: int,
    timeout_seconds: float = 45.0,
) -> PreparedCompleteQueue:
    if count < 1:
        raise ValueError("complete ready count 必须大于 0")
    if size_bytes < 1:
        raise ValueError("multipart size 必须大于 0")
    if concurrency < 1:
        raise ValueError("complete prepare concurrency 必须大于 0")
    return asyncio.run(
        _prepare_complete_queue(
            fixture=fixture,
            session_token=session_token,
            csrf_token=csrf_token,
            count=count,
            size_bytes=size_bytes,
            concurrency=concurrency,
            timeout_seconds=timeout_seconds,
        )
    )


async def _prepare_complete_queue(
    *,
    fixture: BenchmarkFixture,
    session_token: str,
    csrf_token: str,
    count: int,
    size_bytes: int,
    concurrency: int,
    timeout_seconds: float,
) -> PreparedCompleteQueue:
    timeout = httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 10.0))
    limits = httpx.Limits(
        max_connections=max(concurrency * 2, 20),
        max_keepalive_connections=max(concurrency, 10),
    )
    cookies = {
        "drive_session": session_token,
        "drive_csrf": csrf_token,
    }
    headers = {
        "X-CSRF-Token": csrf_token,
        "X-Drive-Transfer-Protocol": "DTP/1",
    }
    semaphore = asyncio.Semaphore(concurrency)
    run_prefix = f"perf-complete-{secrets.token_hex(6)}"

    async with (
        httpx.AsyncClient(
            base_url=fixture.base_url,
            cookies=cookies,
            timeout=timeout,
            limits=limits,
            trust_env=False,
        ) as api_client,
        httpx.AsyncClient(
            timeout=timeout,
            limits=limits,
            trust_env=False,
        ) as storage_client,
    ):

        async def prepare_one(index: int) -> PreparedCompleteItem:
            session_id: str | None = None
            async with semaphore:
                content = secrets.token_bytes(min(size_bytes, 32))
                content += b"\x00" * (size_bytes - len(content))
                digest = hashlib.sha256(content).hexdigest()
                try:
                    init_response = await api_client.post(
                        "/api/v1/uploads/init",
                        headers=headers,
                        json={
                            "space_id": fixture.space_id,
                            "parent_id": fixture.parent_id,
                            "file_name": f"{run_prefix}-{index:06d}-{digest[:12]}.bin",
                            "size_bytes": size_bytes,
                            "content_hash": digest,
                            "hash_algo": "sha256",
                            "mime_type": "application/octet-stream",
                            "conflict_policy": "fail",
                        },
                    )
                    _raise_for_status(init_response, stage="init")
                    init_payload = init_response.json()
                    if init_payload.get("mode") != "multipart":
                        raise RuntimeError("complete 预置 init 未创建 multipart 会话")
                    session_id = str(init_payload["session_id"])

                    presign_response = await api_client.post(
                        f"/api/v1/uploads/{session_id}/parts/1/presign",
                        headers=headers,
                    )
                    _raise_for_status(presign_response, stage="presign")
                    presign_payload = presign_response.json()
                    upload_headers = presign_payload.get("headers")
                    if not isinstance(upload_headers, dict):
                        upload_headers = {}
                    upload_response = await storage_client.put(
                        str(presign_payload["upload_url"]),
                        content=content,
                        headers={str(key): str(value) for key, value in upload_headers.items()},
                    )
                    _raise_for_status(upload_response, stage="storage PUT")
                    etag = str(upload_response.headers.get("etag") or "").strip('"')
                    if not etag:
                        raise RuntimeError("complete 预置分片响应缺少 ETag")
                    return PreparedCompleteItem(
                        session_id=session_id,
                        etag=etag,
                        size_bytes=size_bytes,
                    )
                except Exception:
                    if session_id is not None:
                        await _abort_session(
                            api_client=api_client,
                            session_id=session_id,
                            headers=headers,
                        )
                    raise

        results = await asyncio.gather(
            *(prepare_one(index) for index in range(count)),
            return_exceptions=True,
        )
        items = [result for result in results if isinstance(result, PreparedCompleteItem)]
        errors = [result for result in results if isinstance(result, BaseException)]
        if errors:
            queue = _build_queue(fixture=fixture, size_bytes=size_bytes, items=items)
            await _cleanup_complete_queue(
                queue=queue,
                session_token=session_token,
                csrf_token=csrf_token,
                concurrency=concurrency,
                timeout_seconds=timeout_seconds,
            )
            raise RuntimeError(
                f"complete 预置失败: prepared={len(items)} errors={len(errors)} first={errors[0]!r}"
            )

    return _build_queue(fixture=fixture, size_bytes=size_bytes, items=items)


def cleanup_complete_queue(
    *,
    queue: PreparedCompleteQueue,
    session_token: str,
    csrf_token: str,
    concurrency: int,
    timeout_seconds: float = 45.0,
) -> dict[str, Any]:
    if concurrency < 1:
        raise ValueError("complete cleanup concurrency 必须大于 0")
    return asyncio.run(
        _cleanup_complete_queue(
            queue=queue,
            session_token=session_token,
            csrf_token=csrf_token,
            concurrency=concurrency,
            timeout_seconds=timeout_seconds,
        )
    )


async def _cleanup_complete_queue(
    *,
    queue: PreparedCompleteQueue,
    session_token: str,
    csrf_token: str,
    concurrency: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    timeout = httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 10.0))
    headers = {
        "X-CSRF-Token": csrf_token,
        "X-Drive-Transfer-Protocol": "DTP/1",
    }
    semaphore = asyncio.Semaphore(concurrency)
    summary: dict[str, Any] = {
        "schema_version": COMPLETE_QUEUE_SCHEMA,
        "prepared": len(queue.items),
        "completed_nodes_purged": 0,
        "sessions_aborted": 0,
        "sessions_missing": 0,
        "errors": [],
    }
    async with httpx.AsyncClient(
        base_url=queue.base_url,
        cookies={
            "drive_session": session_token,
            "drive_csrf": csrf_token,
        },
        timeout=timeout,
        limits=httpx.Limits(
            max_connections=max(concurrency * 2, 20),
            max_keepalive_connections=max(concurrency, 10),
        ),
        trust_env=False,
    ) as api_client:

        async def cleanup_one(item: PreparedCompleteItem) -> None:
            async with semaphore:
                try:
                    status_payload = await _read_status(
                        api_client=api_client,
                        session_id=item.session_id,
                        headers=headers,
                    )
                    if status_payload is None:
                        summary["sessions_missing"] += 1
                        return
                    if status_payload.get("status") == "completed":
                        node_id = status_payload.get("completed_node_id")
                        if node_id:
                            await _delete_and_purge_node(
                                api_client=api_client,
                                node_id=str(node_id),
                                csrf_token=csrf_token,
                            )
                            summary["completed_nodes_purged"] += 1
                        return
                    await _abort_session(
                        api_client=api_client,
                        session_id=item.session_id,
                        headers=headers,
                    )
                    summary["sessions_aborted"] += 1
                except Exception as exc:
                    if len(summary["errors"]) < 20:
                        summary["errors"].append(
                            {
                                "session_id": item.session_id,
                                "error": repr(exc),
                            }
                        )

        await asyncio.gather(*(cleanup_one(item) for item in queue.items))
    summary["clean"] = not summary["errors"]
    return summary


async def _read_status(
    *,
    api_client: httpx.AsyncClient,
    session_id: str,
    headers: dict[str, str],
) -> dict[str, Any] | None:
    for _ in range(10):
        response = await api_client.get(
            f"/api/v1/uploads/{session_id}",
            headers=headers,
        )
        if response.status_code == 404:
            return None
        _raise_for_status(response, stage="status")
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("complete status 返回的 JSON 不是对象")
        if payload.get("status") != "completing":
            return {str(key): value for key, value in payload.items()}
        await asyncio.sleep(0.2)
    raise RuntimeError(f"complete cleanup 等待会话结束超时: {session_id}")


async def _abort_session(
    *,
    api_client: httpx.AsyncClient,
    session_id: str,
    headers: dict[str, str],
) -> None:
    response = await api_client.post(
        f"/api/v1/uploads/{session_id}/abort",
        headers=headers,
    )
    if response.status_code not in (200, 404):
        _raise_for_status(response, stage="abort")


async def _delete_and_purge_node(
    *,
    api_client: httpx.AsyncClient,
    node_id: str,
    csrf_token: str,
) -> None:
    headers = {"X-CSRF-Token": csrf_token}
    delete_response = await api_client.delete(
        f"/api/v1/files/{node_id}",
        headers=headers,
    )
    if delete_response.status_code not in (200, 404):
        _raise_for_status(delete_response, stage="delete")
    purge_response = await api_client.delete(
        f"/api/v1/files/{node_id}/purge",
        headers=headers,
    )
    if purge_response.status_code not in (200, 404):
        _raise_for_status(purge_response, stage="purge")


def _build_queue(
    *,
    fixture: BenchmarkFixture,
    size_bytes: int,
    items: list[PreparedCompleteItem],
) -> PreparedCompleteQueue:
    return PreparedCompleteQueue(
        schema_version=COMPLETE_QUEUE_SCHEMA,
        base_url=fixture.base_url,
        tenant_slug=fixture.tenant_slug,
        space_id=fixture.space_id,
        parent_id=fixture.parent_id,
        size_bytes=size_bytes,
        items=items,
        created_at=datetime.now(UTC).isoformat(),
    )


def _raise_for_status(response: httpx.Response, *, stage: str) -> None:
    if response.is_error:
        raise RuntimeError(
            f"complete {stage} 失败: status={response.status_code} body={response.text[:500]}"
        )


def write_complete_queue(queue: PreparedCompleteQueue, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(queue), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_complete_queue(path: Path) -> PreparedCompleteQueue:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != COMPLETE_QUEUE_SCHEMA:
        raise ValueError("complete queue schema 不受支持")
    return PreparedCompleteQueue(
        schema_version=COMPLETE_QUEUE_SCHEMA,
        base_url=str(payload["base_url"]),
        tenant_slug=str(payload["tenant_slug"]),
        space_id=str(payload["space_id"]),
        parent_id=str(payload["parent_id"]),
        size_bytes=int(payload["size_bytes"]),
        items=[
            PreparedCompleteItem(
                session_id=str(item["session_id"]),
                etag=str(item["etag"]),
                size_bytes=int(item["size_bytes"]),
            )
            for item in payload["items"]
        ],
        created_at=str(payload["created_at"]),
    )


def write_cleanup_summary(summary: dict[str, Any], path: Path) -> None:
    path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
