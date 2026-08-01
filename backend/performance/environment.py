from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from performance.data_snapshot import (
    database_snapshot,
    opensearch_snapshot,
    read_optional_target_state,
)
from performance.docker_snapshot import (
    compose_snapshot,
    docker_info,
    host_snapshot,
    service_container,
)


def collect_environment_snapshot(
    *,
    output_dir: Path,
    compose_project: str | None,
    target_state_path: Path | None,
    postgres_user: str,
    postgres_database: str,
) -> dict[str, Any]:
    errors: list[str] = []
    optional_errors: list[str] = []
    target_state = read_optional_target_state(target_state_path, errors)
    docker_errors = errors if compose_project is not None else optional_errors
    docker = docker_info(docker_errors)
    compose = compose_snapshot(compose_project, errors)
    postgres_container = service_container(compose, "postgres")
    opensearch_container = service_container(compose, "opensearch")
    if compose_project is not None and postgres_container is None:
        errors.append("compose_containers: 缺少 postgres service")
    if compose_project is not None and opensearch_container is None:
        errors.append("compose_containers: 缺少 opensearch service")
    database = database_snapshot(
        postgres_container=postgres_container,
        postgres_user=postgres_user,
        postgres_database=postgres_database,
        target_state=target_state,
        errors=errors,
    )
    opensearch = opensearch_snapshot(
        opensearch_container=opensearch_container,
        target_state=target_state,
        errors=errors,
    )
    return {
        "complete": not errors,
        "collection_errors": errors,
        "optional_collection_errors": optional_errors,
        "host": host_snapshot(output_dir),
        "docker": docker,
        "compose": compose,
        "database": database,
        "opensearch": opensearch,
        "target_data": asdict(target_state) if target_state is not None else None,
    }
