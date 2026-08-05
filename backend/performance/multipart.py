from __future__ import annotations

import time
from contextlib import suppress
from typing import Any
from urllib.parse import urlsplit

import requests


def parse_server_timing(header: str) -> dict[str, float]:
    timings: dict[str, float] = {}
    for entry in header.split(","):
        parts = [part.strip() for part in entry.split(";") if part.strip()]
        if not parts:
            continue
        name = parts[0]
        for parameter in parts[1:]:
            key, separator, value = parameter.partition("=")
            if key == "dur" and separator:
                with suppress(ValueError):
                    timings[name] = float(value)
                break
    return timings


def upload_presigned_part(
    *,
    client: requests.Session,
    upload_url: str,
    content: bytes,
    headers: dict[str, str],
    timeout_seconds: float,
) -> str:
    started = time.perf_counter()
    response: requests.Response | None = None
    error: Exception | None = None
    try:
        response = client.put(
            upload_url,
            data=content,
            headers=headers,
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        etag = str(response.headers.get("etag") or "").strip('"')
        if not etag:
            raise RuntimeError("对象存储分片响应缺少 ETag")
        return etag
    except Exception as exc:
        error = exc
        raise
    finally:
        _fire_request_event(
            request_type="PUT",
            name="upload_part_transfer",
            response_time=(time.perf_counter() - started) * 1000,
            response_length=len(response.content) if response is not None else 0,
            exception=error,
            context={},
        )


def warm_storage_connection(
    *,
    client: requests.Session,
    upload_url: str,
    timeout_seconds: float,
) -> None:
    parsed = urlsplit(upload_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("预签名上传 URL 缺少有效 origin")
    probe_url = f"{parsed.scheme}://{parsed.netloc}/"
    started = time.perf_counter()
    response: requests.Response | None = None
    error: Exception | None = None
    try:
        response = client.get(
            probe_url,
            timeout=timeout_seconds,
            allow_redirects=False,
        )
        if response.status_code not in {200, 403}:
            response.raise_for_status()
            raise RuntimeError(f"对象存储预热探针返回非预期 HTTP {response.status_code}")
    except Exception as exc:
        error = exc
        raise
    finally:
        _fire_request_event(
            request_type="GET",
            name="upload_storage_warmup",
            response_time=(time.perf_counter() - started) * 1000,
            response_length=len(response.content) if response is not None else 0,
            exception=error,
            context={},
        )


def record_complete_timing(
    *,
    response_time_ms: float,
    server_timing_header: str,
    context: dict[str, Any] | None,
) -> None:
    timings = parse_server_timing(server_timing_header)
    storage_complete_ms = timings.get("storage_complete")
    if storage_complete_ms is None:
        _fire_request_event(
            request_type="BENCH",
            name="upload_complete_api_without_storage_merge",
            response_time=response_time_ms,
            response_length=0,
            exception=RuntimeError("complete 响应缺少 storage_complete Server-Timing"),
            context=context or {},
        )
        return
    _fire_request_event(
        request_type="BENCH",
        name="upload_complete_storage_merge",
        response_time=storage_complete_ms,
        response_length=0,
        exception=None,
        context=context or {},
    )
    phase_metric_names = {
        "pre_storage": "upload_complete_pre_storage",
        "hash_validation": "upload_complete_hash_validation",
        "final_object": "upload_complete_final_object",
        "db_finalize": "upload_complete_db_finalize",
        "temp_delete": "upload_complete_temp_delete",
    }
    for phase, metric_name in phase_metric_names.items():
        phase_ms = timings.get(phase)
        if phase_ms is None:
            continue
        _fire_request_event(
            request_type="BENCH",
            name=metric_name,
            response_time=phase_ms,
            response_length=0,
            exception=None,
            context=context or {},
        )
    measured_server_ms = sum(timings.values())
    _fire_request_event(
        request_type="BENCH",
        name="upload_complete_unattributed",
        response_time=max(response_time_ms - measured_server_ms, 0.0),
        response_length=0,
        exception=None,
        context=context or {},
    )
    _fire_request_event(
        request_type="BENCH",
        name="upload_complete_api_without_storage_merge",
        response_time=max(response_time_ms - storage_complete_ms, 0.0),
        response_length=0,
        exception=None,
        context=context or {},
    )


def _fire_request_event(**kwargs: Any) -> None:
    from locust import events

    events.request.fire(**kwargs)  # type: ignore[no-untyped-call]
