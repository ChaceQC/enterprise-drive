from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4


def _run(
    command: list[str],
    *,
    check: bool = True,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if check and result.returncode != 0:
        output = "\n".join(part for part in (result.stdout, result.stderr) if part.strip())
        raise RuntimeError(
            f"Command failed with exit code {result.returncode}: {' '.join(command)}\n{output}"
        )
    return result


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _send_raw_http(
    port: int,
    request: bytes,
    *,
    probe_name: str = "request",
    allow_empty_rejection: bool = False,
) -> tuple[int, bytes]:
    chunks: list[bytes] = []
    with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
        connection.settimeout(5)
        connection.sendall(request)
        connection.shutdown(socket.SHUT_WR)
        while True:
            try:
                chunk = connection.recv(65536)
            except TimeoutError:
                break
            if not chunk:
                break
            chunks.append(chunk)
            if sum(map(len, chunks)) > 1024 * 1024:
                raise RuntimeError("Gateway response exceeded 1 MiB")

    response = b"".join(chunks)
    if not response and allow_empty_rejection:
        return 0, response
    status_line = response.split(b"\r\n", 1)[0]
    parts = status_line.split()
    if len(parts) < 2 or not parts[1].isdigit():
        raise RuntimeError(f"{probe_name} returned an invalid HTTP response: {response[:500]!r}")
    return int(parts[1]), response


def _wait_for_gateway(container_name: str, port: int) -> bytes:
    request = (
        b"GET /gateway-healthz HTTP/1.1\r\nHost: drive.security.test\r\nConnection: close\r\n\r\n"
    )
    deadline = time.monotonic() + 20
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        running = _run(
            [
                "docker",
                "inspect",
                "--format",
                "{{.State.Running}}",
                container_name,
            ],
            check=False,
        )
        if running.returncode == 0 and running.stdout.strip() != "true":
            break
        try:
            status, response = _send_raw_http(port, request)
            if status == 200:
                return response
        except (OSError, RuntimeError) as exc:
            last_error = exc
        time.sleep(0.25)

    logs = _run(["docker", "logs", container_name], check=False).stdout
    raise RuntimeError(f"Gateway did not become ready: {last_error}\n{logs}")


def _assert_status(
    results: dict[str, int],
    name: str,
    actual: int,
    expected: set[int],
) -> None:
    results[name] = actual
    if actual not in expected:
        raise RuntimeError(f"{name} returned {actual}, expected one of {sorted(expected)}")


def run_smoke(*, image: str, template_path: Path) -> dict[str, object]:
    resolved_template = template_path.resolve(strict=True)
    _run(["docker", "version", "--format", "{{.Server.Version}}"])
    _run(["docker", "image", "inspect", image])

    container_name = f"enterprise-drive-gateway-security-{uuid4().hex[:12]}"
    host_port = _free_local_port()
    storage_host_port = _free_local_port()
    while storage_host_port == host_port:
        storage_host_port = _free_local_port()
    results: dict[str, int] = {}
    started = False

    try:
        _run(
            [
                "docker",
                "run",
                "--detach",
                "--pull",
                "never",
                "--name",
                container_name,
                "--cpus",
                "0.25",
                "--memory",
                "128m",
                "--memory-swap",
                "128m",
                "--pids-limit",
                "64",
                "--read-only",
                "--security-opt",
                "no-new-privileges:true",
                "--tmpfs",
                "/etc/nginx/conf.d:rw,noexec,nosuid,size=4m",
                "--tmpfs",
                "/var/cache/nginx:rw,noexec,nosuid,size=16m",
                "--tmpfs",
                "/var/run:rw,noexec,nosuid,size=1m",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=4m",
                "--add-host",
                "api:127.0.0.2",
                "--add-host",
                "minio:127.0.0.2",
                "--mount",
                (
                    f"type=bind,source={resolved_template},"
                    "target=/etc/nginx/templates/default.conf.template,readonly"
                ),
                "--env",
                "DRIVE_SERVER_NAME=drive.security.test",
                "--env",
                "DRIVE_STORAGE_SERVER_NAME=storage.security.test",
                "--env",
                "DRIVE_API_MAX_BODY_SIZE=1k",
                "--env",
                "DRIVE_PROXY_CONNECT_TIMEOUT=1s",
                "--env",
                "DRIVE_PROXY_READ_TIMEOUT=1s",
                "--env",
                "DRIVE_PROXY_SEND_TIMEOUT=1s",
                "--publish",
                f"127.0.0.1:{host_port}:8080",
                "--publish",
                f"127.0.0.1:{storage_host_port}:9000",
                image,
            ],
            timeout=60,
        )
        started = True
        health_response = _wait_for_gateway(container_name, host_port)
        _assert_status(results, "health", 200, {200})
        for header in (
            b"x-content-type-options: nosniff",
            b"x-frame-options: DENY",
            b"referrer-policy: strict-origin-when-cross-origin",
        ):
            if header.lower() not in health_response.lower():
                raise RuntimeError(f"Missing gateway security header: {header.decode()}")

        unknown_api_status, _ = _send_raw_http(
            host_port,
            (b"GET / HTTP/1.1\r\nHost: unexpected.security.test\r\nConnection: close\r\n\r\n"),
            probe_name="unknown_api_host",
            allow_empty_rejection=True,
        )
        _assert_status(results, "unknown_api_host", unknown_api_status, {0})

        unknown_storage_status, _ = _send_raw_http(
            storage_host_port,
            (b"GET / HTTP/1.1\r\nHost: unexpected.security.test\r\nConnection: close\r\n\r\n"),
            probe_name="unknown_storage_host",
            allow_empty_rejection=True,
        )
        _assert_status(results, "unknown_storage_host", unknown_storage_status, {0})

        cl_te_status, _ = _send_raw_http(
            host_port,
            (
                b"POST /gateway-healthz HTTP/1.1\r\n"
                b"Host: drive.security.test\r\n"
                b"Content-Length: 4\r\n"
                b"Transfer-Encoding: chunked\r\n"
                b"Connection: close\r\n\r\n"
                b"0\r\n\r\n"
            ),
            probe_name="conflicting_content_length_transfer_encoding",
            allow_empty_rejection=True,
        )
        _assert_status(
            results,
            "conflicting_content_length_transfer_encoding",
            cl_te_status,
            {0, 400},
        )

        duplicate_cl_status, _ = _send_raw_http(
            host_port,
            (
                b"POST /gateway-healthz HTTP/1.1\r\n"
                b"Host: drive.security.test\r\n"
                b"Content-Length: 4\r\n"
                b"Content-Length: 5\r\n"
                b"Connection: close\r\n\r\n"
                b"abcd"
            ),
            probe_name="conflicting_content_length",
            allow_empty_rejection=True,
        )
        _assert_status(results, "conflicting_content_length", duplicate_cl_status, {0, 400})

        large_body = b"x" * 2048
        api_large_status, _ = _send_raw_http(
            host_port,
            (
                b"POST /api/v1/auth/login HTTP/1.1\r\n"
                b"Host: drive.security.test\r\n"
                b"Content-Type: application/json\r\n"
                + f"Content-Length: {len(large_body)}\r\n".encode()
                + b"Expect: 100-continue\r\n"
                + b"Connection: close\r\n\r\n"
            ),
            probe_name="api_body_limit",
        )
        _assert_status(results, "api_body_limit", api_large_status, {413})

        storage_large_status, _ = _send_raw_http(
            host_port,
            (
                b"PUT /large-object HTTP/1.1\r\n"
                b"Host: storage.security.test\r\n"
                b"Content-Type: application/octet-stream\r\n"
                + f"Content-Length: {len(large_body)}\r\n".encode()
                + b"Expect: 100-continue\r\n"
                + b"Connection: close\r\n\r\n"
            ),
            probe_name="storage_streaming_body_headers",
        )
        _assert_status(results, "storage_streaming_body_headers", storage_large_status, {100})

        local_storage_status, _ = _send_raw_http(
            storage_host_port,
            (
                b"PUT /large-object HTTP/1.1\r\n"
                b"Host: localhost\r\n"
                b"Content-Type: application/octet-stream\r\n"
                + f"Content-Length: {len(large_body)}\r\n".encode()
                + b"Expect: 100-continue\r\n"
                + b"Connection: close\r\n\r\n"
            ),
            probe_name="local_storage_host",
        )
        _assert_status(results, "local_storage_host", local_storage_status, {100})
    finally:
        if started:
            _run(["docker", "rm", "--force", container_name], check=False)
        leftover = _run(
            [
                "docker",
                "ps",
                "--all",
                "--quiet",
                "--filter",
                f"name=^{container_name}$",
            ],
            check=False,
        )
        if leftover.stdout.strip():
            raise RuntimeError(f"Gateway security container was not removed: {container_name}")

    return {
        "image": image,
        "template": str(resolved_template),
        "host_port": host_port,
        "storage_host_port": storage_host_port,
        "resource_limits": {
            "cpus": "0.25",
            "memory": "128m",
            "memory_swap": "128m",
            "pids": 64,
        },
        "results": results,
    }


def main() -> int:
    repository_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Run real Nginx raw HTTP security smoke")
    parser.add_argument("--image", default="nginx:1.27-alpine")
    parser.add_argument(
        "--template",
        type=Path,
        default=repository_root / "deploy/windows/nginx/default.conf.template",
    )
    args = parser.parse_args()
    try:
        result = run_smoke(image=args.image, template_path=args.template)
    except Exception as exc:
        print(f"gateway security smoke failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
