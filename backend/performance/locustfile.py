from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import urlsplit

import requests
from gevent import spawn_later  # type: ignore[import-untyped]
from gevent.lock import Semaphore as GeventSemaphore  # type: ignore[import-untyped]
from locust import HttpUser, between, events, task
from locust.exception import StopUser

from performance.complete_queue import (
    PreparedCompleteItem,
    mark_prepared_complete_item_finished,
    take_prepared_complete_item,
)
from performance.multipart import (
    record_complete_timing,
    upload_presigned_part,
    warm_storage_connection,
)

logging.getLogger("httpx").setLevel(logging.WARNING)

_WARMED_STORAGE_ORIGINS: set[str] = set()
_STORAGE_WARMUP_LOCK = Lock()
_STATS_RESET_LOCK = Lock()
_STATS_RESET_SCHEDULED = False
_DEFAULT_WAIT_TIME = between(0.1, 0.3)
_COMPLETE_SEMAPHORE: GeventSemaphore | None = None
if os.getenv("PERF_COMPLETE_QUEUE_PATH"):
    _COMPLETE_SEMAPHORE = GeventSemaphore(max(1, int(os.getenv("PERF_COMPLETE_CONCURRENCY", "24"))))


@lru_cache(maxsize=4)
def _load_fixture_cached(fixture_path: str) -> dict[str, Any]:
    payload = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("性能 fixture JSON 必须是对象")
    return payload


def _load_fixture() -> dict[str, Any]:
    fixture_path = os.getenv("PERF_FIXTURE_PATH")
    if not fixture_path:
        raise RuntimeError("PERF_FIXTURE_PATH 未设置")
    return _load_fixture_cached(fixture_path)


def _take_prepared_complete_item() -> PreparedCompleteItem | None:
    queue_path = os.getenv("PERF_COMPLETE_QUEUE_PATH")
    if not queue_path:
        return None
    return take_prepared_complete_item(queue_path)


class BenchmarkUser(HttpUser):
    def wait_time(self) -> float:
        if self.scenario == "upload_complete" and os.getenv("PERF_COMPLETE_QUEUE_PATH"):
            return 0.0
        return float(_DEFAULT_WAIT_TIME(self))

    def on_start(self) -> None:
        try:
            self.fixture = _load_fixture()
            self.scenario = os.getenv("PERF_SCENARIO", "mixed")
            self.tenant_slug = os.getenv("PERF_TENANT_SLUG", self.fixture["tenant_slug"])
            self.username = os.environ["PERF_USERNAME"]
            self.password = os.environ["PERF_PASSWORD"]
            self.csrf_token = ""
            self.storage_client: requests.Session | None = None
            self.storage_client_warmed = False
            self.fixture_list_parent_id = str(
                self.fixture.get("fixture_root_id") or self.fixture["parent_id"]
            )
            if self.scenario != "login" and not self._use_prepared_session() and not self._login():
                raise StopUser()
        except (KeyError, OSError, ValueError, RuntimeError) as exc:
            raise StopUser() from exc

    def on_stop(self) -> None:
        storage_client = getattr(self, "storage_client", None)
        if storage_client is not None:
            storage_client.close()

    def _login(self) -> bool:
        with self.client.post(
            "/api/v1/auth/login",
            json={
                "tenant_slug": self.tenant_slug,
                "username": self.username,
                "password": self.password,
            },
            name="auth_login",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"login status={response.status_code}")
                return False
            self.csrf_token = (
                response.cookies.get("drive_csrf") or self.client.cookies.get("drive_csrf") or ""
            )
            if not self.csrf_token:
                response.failure("login response missing drive_csrf")
                return False
            return True

    def _use_prepared_session(self) -> bool:
        session_token = os.getenv("PERF_SESSION_TOKEN")
        csrf_token = os.getenv("PERF_CSRF_TOKEN")
        if session_token is None and csrf_token is None:
            return False
        if not session_token or not csrf_token:
            raise RuntimeError("PERF_SESSION_TOKEN 与 PERF_CSRF_TOKEN 必须同时设置")
        self.client.cookies.set("drive_session", session_token)
        self.client.cookies.set("drive_csrf", csrf_token)
        self.csrf_token = csrf_token
        return True

    def _headers(self, *, transfer: bool = False) -> dict[str, str]:
        headers = {"X-CSRF-Token": self.csrf_token}
        if transfer:
            headers["X-Drive-Transfer-Protocol"] = "DTP/1"
        return headers

    @task
    def run_scenario(self) -> None:
        handlers = {
            "login": self._login,
            "auth_me": self._auth_me,
            "list": self._file_list,
            "search": self._search,
            "upload_init": self._upload_init,
            "upload_complete": self._upload_complete,
            "audit": self._admin_audit,
            "mixed": self._mixed,
        }
        try:
            handlers[self.scenario]()
        except KeyError:
            raise StopUser() from None

    def _mixed(self) -> None:
        handlers = (
            self._file_list,
            self._file_list,
            self._search,
            self._upload_init,
            self._admin_audit,
            self._auth_me,
        )
        secrets.choice(handlers)()

    def _auth_me(self) -> None:
        with self.client.get("/api/v1/auth/me", name="auth_me", catch_response=True) as response:
            if response.status_code != 200:
                response.failure(f"auth/me status={response.status_code}")

    def _file_list(self) -> None:
        with self.client.get(
            "/api/v1/files",
            params={
                "space_id": self.fixture["space_id"],
                "parent_id": self.fixture_list_parent_id,
                "page_size": 100,
            },
            name="file_list_permission_batch",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"file list status={response.status_code}")

    def _search(self) -> None:
        with self.client.get(
            "/api/v1/search",
            params={"q": self.fixture["search_query"], "limit": 20},
            name="search",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"search status={response.status_code}")

    def _upload_init(self) -> None:
        digest = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
        with self.client.post(
            "/api/v1/uploads/init",
            headers=self._headers(transfer=True),
            json={
                "space_id": self.fixture["space_id"],
                "parent_id": self.fixture["parent_id"],
                "file_name": f"perf-{digest[:12]}.bin",
                "size_bytes": 1024,
                "content_hash": digest,
                "hash_algo": "sha256",
                "mime_type": "application/octet-stream",
                "conflict_policy": "fail",
            },
            name="upload_init",
            catch_response=True,
        ) as response:
            if response.status_code != 201:
                response.failure(f"upload init status={response.status_code}")
                return
            payload = response.json()
            if (
                payload.get("mode") == "multipart"
                and payload.get("session_id")
                and os.getenv("PERF_UPLOAD_INIT_CLEANUP", "abort").lower() != "deferred"
            ):
                self._abort_upload(str(payload["session_id"]))

    def _abort_upload(self, session_id: str) -> None:
        with self.client.post(
            f"/api/v1/uploads/{session_id}/abort",
            headers=self._headers(transfer=True),
            name="upload_abort_cleanup",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"upload abort status={response.status_code}")

    def _upload_complete(self) -> None:
        queue_path = os.getenv("PERF_COMPLETE_QUEUE_PATH")
        if queue_path:
            prepared_item = _take_prepared_complete_item()
            if prepared_item is None:
                raise StopUser()
            self._complete_prepared_upload(prepared_item)
            return

        size_bytes = int(os.getenv("PERF_MULTIPART_SIZE_BYTES", str(64 * 1024)))
        if size_bytes < 1:
            raise StopUser()
        storage_client = self._storage_client()
        prefix = secrets.token_bytes(min(size_bytes, 32))
        content = prefix + (b"\x00" * (size_bytes - len(prefix)))
        digest = hashlib.sha256(content).hexdigest()
        session_id: str | None = None
        completed_node_id: str | None = None
        with self.client.post(
            "/api/v1/uploads/init",
            headers=self._headers(transfer=True),
            json={
                "space_id": self.fixture["space_id"],
                "parent_id": self.fixture["parent_id"],
                "file_name": f"perf-complete-{digest[:16]}.bin",
                "size_bytes": size_bytes,
                "content_hash": digest,
                "hash_algo": "sha256",
                "mime_type": "application/octet-stream",
                "conflict_policy": "fail",
            },
            name="upload_complete_setup_init",
            catch_response=True,
        ) as response:
            if response.status_code != 201:
                response.failure(f"upload complete init status={response.status_code}")
                return
            payload = response.json()
            if payload.get("mode") != "multipart" or not payload.get("session_id"):
                response.failure("upload complete init did not create multipart session")
                return
            session_id = str(payload["session_id"])

        try:
            with self.client.post(
                f"/api/v1/uploads/{session_id}/parts/1/presign",
                headers=self._headers(transfer=True),
                name="upload_complete_setup_presign",
                catch_response=True,
            ) as response:
                if response.status_code != 200:
                    response.failure(f"upload complete presign status={response.status_code}")
                    return
                presigned = response.json()
            upload_headers = presigned.get("headers")
            if not isinstance(upload_headers, dict):
                upload_headers = {}
            if not self.storage_client_warmed:
                self._warm_storage_connection(
                    client=storage_client,
                    upload_url=str(presigned["upload_url"]),
                )
                self.storage_client_warmed = True
            etag = upload_presigned_part(
                client=storage_client,
                upload_url=str(presigned["upload_url"]),
                content=content,
                headers={str(key): str(value) for key, value in upload_headers.items()},
                timeout_seconds=float(os.getenv("PERF_MULTIPART_TIMEOUT_SECONDS", "30")),
            )
            with self.client.post(
                f"/api/v1/uploads/{session_id}/complete",
                headers={
                    **self._headers(transfer=True),
                    "X-Drive-Benchmark": "BE-029",
                },
                json={
                    "parts": [
                        {
                            "part_no": 1,
                            "etag": etag,
                            "size_bytes": size_bytes,
                        }
                    ]
                },
                name="upload_complete_end_to_end",
                catch_response=True,
            ) as response:
                if response.status_code != 200:
                    response.failure(f"upload complete status={response.status_code}")
                    return
                completed_node_id = str(response.json()["node_id"])
                response_time_ms = float(response.request_meta.get("response_time") or 0)
                context = response.request_meta.get("context")
                record_complete_timing(
                    response_time_ms=response_time_ms,
                    server_timing_header=response.headers.get("Server-Timing", ""),
                    context=context if isinstance(context, dict) else {},
                )
        finally:
            if completed_node_id is not None:
                self._cleanup_completed_node(completed_node_id)
            elif session_id is not None:
                self._abort_upload(session_id)

    def _complete_prepared_upload(self, item: PreparedCompleteItem) -> None:
        queue_path = os.environ["PERF_COMPLETE_QUEUE_PATH"]
        semaphore = _COMPLETE_SEMAPHORE
        if semaphore is not None:
            semaphore.acquire()
        try:
            with self.client.post(
                f"/api/v1/uploads/{item.session_id}/complete",
                headers={
                    **self._headers(transfer=True),
                    "X-Drive-Benchmark": "BE-029",
                },
                json={
                    "parts": [
                        {
                            "part_no": 1,
                            "etag": item.etag,
                            "size_bytes": item.size_bytes,
                        }
                    ]
                },
                name="upload_complete_end_to_end",
                catch_response=True,
            ) as response:
                if response.status_code != 200:
                    response.failure(f"upload complete status={response.status_code}")
                    return
                response_time_ms = float(response.request_meta.get("response_time") or 0)
                context = response.request_meta.get("context")
                record_complete_timing(
                    response_time_ms=response_time_ms,
                    server_timing_header=response.headers.get("Server-Timing", ""),
                    context=context if isinstance(context, dict) else {},
                )
        finally:
            if semaphore is not None:
                semaphore.release()
            if mark_prepared_complete_item_finished(queue_path):
                runner = self.environment.runner
                if runner is not None:
                    spawn_later(
                        max(
                            float(os.getenv("PERF_COMPLETE_QUIT_GRACE_SECONDS", "0.2")),
                            0.0,
                        ),
                        runner.quit,
                    )

    def _storage_client(self) -> requests.Session:
        if self.storage_client is None:
            self.storage_client = requests.Session()
            self.storage_client.trust_env = False
        return self.storage_client

    def _warm_storage_connection(self, *, client: requests.Session, upload_url: str) -> None:
        mode = os.getenv("PERF_STORAGE_WARMUP_MODE", "per_user").lower()
        if mode == "disabled":
            return
        if mode != "per_process":
            warm_storage_connection(
                client=client,
                upload_url=upload_url,
                timeout_seconds=float(os.getenv("PERF_MULTIPART_TIMEOUT_SECONDS", "30")),
            )
            return

        parsed = urlsplit(upload_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        with _STORAGE_WARMUP_LOCK:
            if origin in _WARMED_STORAGE_ORIGINS:
                return
            _WARMED_STORAGE_ORIGINS.add(origin)
        try:
            warm_storage_connection(
                client=client,
                upload_url=upload_url,
                timeout_seconds=float(os.getenv("PERF_MULTIPART_TIMEOUT_SECONDS", "30")),
            )
        except Exception:
            with _STORAGE_WARMUP_LOCK:
                _WARMED_STORAGE_ORIGINS.discard(origin)
            raise

    def _cleanup_completed_node(self, node_id: str) -> None:
        with self.client.delete(
            f"/api/v1/files/{node_id}",
            headers=self._headers(),
            name="upload_complete_cleanup_delete",
            catch_response=True,
        ) as response:
            if response.status_code not in (200, 404):
                response.failure(f"upload complete cleanup delete status={response.status_code}")
                return
        with self.client.delete(
            f"/api/v1/files/{node_id}/purge",
            headers=self._headers(),
            name="upload_complete_cleanup_purge",
            catch_response=True,
        ) as response:
            if response.status_code not in (200, 404):
                response.failure(f"upload complete cleanup purge status={response.status_code}")

    def _admin_audit(self) -> None:
        with self.client.get(
            "/api/v1/admin/audit-logs",
            params={"page_size": 50},
            name="admin_audit",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"audit status={response.status_code}")


@events.init.add_listener
def _register_stats_reset_after_spawning(environment: Any, **_kwargs: Any) -> None:
    def on_spawning_complete(*, user_count: int, **_event_kwargs: Any) -> None:
        del user_count
        _schedule_stats_reset(environment)

    environment.events.spawning_complete.add_listener(on_spawning_complete)


def _schedule_stats_reset(environment: Any) -> None:
    warmup_seconds = float(os.getenv("PERF_WARMUP_SECONDS", "0"))
    if warmup_seconds <= 0:
        return
    global _STATS_RESET_SCHEDULED
    with _STATS_RESET_LOCK:
        if _STATS_RESET_SCHEDULED:
            return
        _STATS_RESET_SCHEDULED = True
    spawn_later(warmup_seconds, environment.stats.reset_all)
