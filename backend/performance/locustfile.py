from __future__ import annotations

import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import Any

from locust import HttpUser, between, task
from locust.exception import StopUser


def _load_fixture() -> dict[str, Any]:
    fixture_path = os.getenv("PERF_FIXTURE_PATH")
    if not fixture_path:
        raise RuntimeError("PERF_FIXTURE_PATH 未设置")
    payload = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("性能 fixture JSON 必须是对象")
    return payload


class BenchmarkUser(HttpUser):
    wait_time = between(0.1, 0.3)

    def on_start(self) -> None:
        try:
            self.fixture = _load_fixture()
            self.scenario = os.getenv("PERF_SCENARIO", "mixed")
            self.tenant_slug = os.getenv("PERF_TENANT_SLUG", self.fixture["tenant_slug"])
            self.username = os.environ["PERF_USERNAME"]
            self.password = os.environ["PERF_PASSWORD"]
            self.csrf_token = ""
            self.fixture_list_parent_id = str(
                self.fixture.get("fixture_root_id") or self.fixture["parent_id"]
            )
            if self.scenario != "login" and not self._login():
                raise StopUser()
        except (KeyError, OSError, ValueError, RuntimeError) as exc:
            raise StopUser() from exc

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
            if payload.get("mode") == "multipart" and payload.get("session_id"):
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

    def _admin_audit(self) -> None:
        with self.client.get(
            "/api/v1/admin/audit-logs",
            params={"page_size": 50},
            name="admin_audit",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"audit status={response.status_code}")
