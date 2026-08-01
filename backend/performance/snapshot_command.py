from __future__ import annotations

import json
import subprocess
from typing import Any


def run_command(
    command: list[str],
    *,
    label: str,
    errors: list[str],
) -> str | None:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        errors.append(f"{label}: {exc}")
        return None
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip().replace("\n", " ")[:300]
        errors.append(f"{label}: exit={completed.returncode} {detail}")
        return None
    return completed.stdout.strip()


def run_json_command(
    command: list[str],
    *,
    label: str,
    errors: list[str],
) -> Any:
    output = run_command(command, label=label, errors=errors)
    if output is None:
        return None
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        errors.append(f"{label}: 返回内容不是 JSON")
        return None


def container_http_json(
    container: str,
    url: str,
    *,
    label: str,
    errors: list[str],
) -> tuple[int | None, Any]:
    output = run_command(
        [
            "docker",
            "exec",
            container,
            "curl",
            "-sS",
            "-w",
            "\n%{http_code}",
            url,
        ],
        label=label,
        errors=errors,
    )
    if output is None or "\n" not in output:
        return None, None
    body, status_text = output.rsplit("\n", 1)
    try:
        status = int(status_text.strip())
    except ValueError:
        errors.append(f"{label}: 无法解析 HTTP 状态码")
        return None, None
    try:
        return status, json.loads(body)
    except json.JSONDecodeError:
        errors.append(f"{label}: 返回内容不是 JSON")
        return status, None
