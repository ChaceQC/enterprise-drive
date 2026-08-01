from __future__ import annotations

import ctypes
import os
import platform
import shutil
from pathlib import Path
from typing import Any

from performance.snapshot_command import run_command, run_json_command


def host_snapshot(output_dir: Path) -> dict[str, Any]:
    disk = shutil.disk_usage(output_dir)
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or os.getenv("PROCESSOR_IDENTIFIER", ""),
        "cpu_count": os.cpu_count(),
        "memory_total_bytes": _host_total_memory_bytes(),
        "output_disk_total_bytes": disk.total,
        "output_disk_used_bytes": disk.used,
        "output_disk_free_bytes": disk.free,
    }


def docker_info(errors: list[str]) -> dict[str, Any] | None:
    payload = run_json_command(
        ["docker", "info", "--format", "{{json .}}"],
        label="docker_info",
        errors=errors,
    )
    if not isinstance(payload, dict):
        return None
    return {
        "server_version": payload.get("ServerVersion"),
        "operating_system": payload.get("OperatingSystem"),
        "os_type": payload.get("OSType"),
        "architecture": payload.get("Architecture"),
        "kernel_version": payload.get("KernelVersion"),
        "cpus": payload.get("NCPU"),
        "memory_total_bytes": payload.get("MemTotal"),
        "storage_driver": payload.get("Driver"),
        "docker_root_dir": payload.get("DockerRootDir"),
    }


def compose_snapshot(
    project: str | None,
    errors: list[str],
) -> dict[str, Any] | None:
    if project is None:
        return None
    ids_output = run_command(
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--format",
            "{{.ID}}",
        ],
        label="compose_containers",
        errors=errors,
    )
    if ids_output is None:
        return None
    container_ids = [line.strip() for line in ids_output.splitlines() if line.strip()]
    if not container_ids:
        errors.append(f"compose_containers: project {project} 没有容器")
        return {"project": project, "containers": []}
    inspected = run_json_command(
        ["docker", "inspect", *container_ids],
        label="compose_inspect",
        errors=errors,
    )
    if not isinstance(inspected, list):
        return {"project": project, "containers": []}
    image_ids = sorted(
        {
            str(item.get("Image"))
            for item in inspected
            if isinstance(item, dict) and item.get("Image")
        }
    )
    images = _image_snapshot(image_ids, errors)
    containers: list[dict[str, Any]] = []
    for item in inspected:
        if not isinstance(item, dict):
            continue
        config_value = item.get("Config")
        config: dict[str, Any] = config_value if isinstance(config_value, dict) else {}
        labels_value = config.get("Labels")
        labels: dict[str, Any] = labels_value if isinstance(labels_value, dict) else {}
        host_config_value = item.get("HostConfig")
        host_config: dict[str, Any] = (
            host_config_value if isinstance(host_config_value, dict) else {}
        )
        state_value = item.get("State")
        state: dict[str, Any] = state_value if isinstance(state_value, dict) else {}
        health_value = state.get("Health")
        health: dict[str, Any] = health_value if isinstance(health_value, dict) else {}
        image_id = str(item.get("Image") or "")
        containers.append(
            {
                "name": str(item.get("Name") or "").lstrip("/"),
                "service": labels.get("com.docker.compose.service"),
                "image_reference": config.get("Image"),
                "image_id": image_id,
                "image": images.get(image_id),
                "status": state.get("Status"),
                "health": health.get("Status"),
                "cpu_limit": host_config.get("NanoCpus"),
                "memory_limit_bytes": host_config.get("Memory"),
                "memory_swap_limit_bytes": host_config.get("MemorySwap"),
                "pids_limit": host_config.get("PidsLimit"),
            }
        )
    containers.sort(key=lambda item: (str(item["service"]), str(item["name"])))
    return {"project": project, "containers": containers}


def service_container(compose: dict[str, Any] | None, service: str) -> str | None:
    if compose is None:
        return None
    containers = compose.get("containers")
    if not isinstance(containers, list):
        return None
    for container in containers:
        if isinstance(container, dict) and container.get("service") == service:
            return str(container.get("name") or "") or None
    return None


def _image_snapshot(
    image_ids: list[str],
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    if not image_ids:
        return {}
    inspected = run_json_command(
        ["docker", "image", "inspect", *image_ids],
        label="image_inspect",
        errors=errors,
    )
    if not isinstance(inspected, list):
        return {}
    results: dict[str, dict[str, Any]] = {}
    for item in inspected:
        if not isinstance(item, dict):
            continue
        image_id = str(item.get("Id") or "")
        results[image_id] = {
            "repo_tags": item.get("RepoTags") or [],
            "repo_digests": item.get("RepoDigests") or [],
            "size_bytes": item.get("Size"),
            "created": item.get("Created"),
        }
    return results


def _host_total_memory_bytes() -> int | None:
    if os.name == "nt":

        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatusEx()
        status.dwLength = ctypes.sizeof(status)
        windll = getattr(ctypes, "windll", None)
        kernel32 = getattr(windll, "kernel32", None)
        if kernel32 is not None and kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.ullTotalPhys)
        return None
    if hasattr(os, "sysconf"):
        try:
            return int(os.sysconf("SC_PAGE_SIZE")) * int(os.sysconf("SC_PHYS_PAGES"))
        except (OSError, ValueError):
            return None
    return None
