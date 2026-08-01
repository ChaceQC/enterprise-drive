from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from performance.snapshot_command import container_http_json, run_command, run_json_command
from performance.target_state import (
    TargetDataState,
    audit_action_for_run,
    read_target_state,
)


def read_optional_target_state(
    path: Path | None,
    errors: list[str],
) -> TargetDataState | None:
    if path is None:
        return None
    try:
        return read_target_state(path.resolve())
    except (OSError, ValueError, TypeError, KeyError) as exc:
        errors.append(f"target_state: {exc}")
        return None


def database_snapshot(
    *,
    postgres_container: str | None,
    postgres_user: str,
    postgres_database: str,
    target_state: TargetDataState | None,
    errors: list[str],
) -> dict[str, Any] | None:
    if postgres_container is None:
        return None
    sql = """
    SELECT json_build_object(
      'database_size_bytes', pg_database_size(current_database()),
      'relations', COALESCE((
        SELECT json_agg(
          json_build_object(
            'table', c.relname,
            'total_bytes', pg_total_relation_size(c.oid)
          )
          ORDER BY c.relname
        )
        FROM pg_class AS c
        JOIN pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'r'
      ), '[]'::json),
      'indexes', COALESCE((
        SELECT json_agg(
          json_build_object(
            'table', tablename,
            'name', indexname,
            'definition', indexdef
          )
          ORDER BY tablename, indexname
        )
        FROM pg_indexes
        WHERE schemaname = 'public'
      ), '[]'::json)
    )
    """
    payload = run_json_command(
        [
            "docker",
            "exec",
            postgres_container,
            "psql",
            "-U",
            postgres_user,
            "-d",
            postgres_database,
            "-tAc",
            " ".join(sql.split()),
        ],
        label="database_snapshot",
        errors=errors,
    )
    if not isinstance(payload, dict):
        return None
    if target_state is not None:
        action = audit_action_for_run(target_state.run_id).replace("'", "''")
        count = run_command(
            [
                "docker",
                "exec",
                postgres_container,
                "psql",
                "-U",
                postgres_user,
                "-d",
                postgres_database,
                "-tAc",
                f"SELECT count(*) FROM audit_logs WHERE action = '{action}'",
            ],
            label="target_audit_count",
            errors=errors,
        )
        if count is not None:
            payload["target_audit_count"] = int(count.strip())
    return payload


def opensearch_snapshot(
    *,
    opensearch_container: str | None,
    target_state: TargetDataState | None,
    errors: list[str],
) -> dict[str, Any] | None:
    if opensearch_container is None:
        return None
    index = (
        target_state.opensearch_index
        if target_state is not None
        else os.getenv("DRIVE_OPENSEARCH_INDEX_NAME", "drive_files_v1")
    )
    status, stats = container_http_json(
        opensearch_container,
        f"http://127.0.0.1:9200/{index}/_stats/docs,store,refresh",
        label="opensearch_stats",
        errors=errors,
    )
    if status == 404:
        return {"index": index, "exists": False}
    if status != 200 or not isinstance(stats, dict):
        return {"index": index, "exists": None}
    indices_value = stats.get("indices")
    indices: dict[str, Any] = indices_value if isinstance(indices_value, dict) else {}
    index_stats_value = indices.get(index)
    index_stats: dict[str, Any] = index_stats_value if isinstance(index_stats_value, dict) else {}
    total_value = index_stats.get("total")
    total: dict[str, Any] = total_value if isinstance(total_value, dict) else {}
    docs_value = total.get("docs")
    docs: dict[str, Any] = docs_value if isinstance(docs_value, dict) else {}
    store_value = total.get("store")
    store: dict[str, Any] = store_value if isinstance(store_value, dict) else {}
    refresh_value = total.get("refresh")
    refresh: dict[str, Any] = refresh_value if isinstance(refresh_value, dict) else {}
    _, settings = container_http_json(
        opensearch_container,
        f"http://127.0.0.1:9200/{index}/_settings?flat_settings=true",
        label="opensearch_settings",
        errors=errors,
    )
    flat_settings: dict[str, Any] = {}
    if isinstance(settings, dict):
        index_settings = settings.get(index)
        if isinstance(index_settings, dict):
            settings_value = index_settings.get("settings")
            if isinstance(settings_value, dict):
                flat_settings = settings_value
    _, health = container_http_json(
        opensearch_container,
        "http://127.0.0.1:9200/_cluster/health",
        label="opensearch_health",
        errors=errors,
    )
    health_payload: dict[str, Any] = health if isinstance(health, dict) else {}
    return {
        "index": index,
        "exists": True,
        "documents": docs.get("count"),
        "deleted_documents": docs.get("deleted"),
        "store_bytes": store.get("size_in_bytes"),
        "refresh_total": refresh.get("total"),
        "refresh_time_ms": refresh.get("total_time_in_millis"),
        "refresh_interval": flat_settings.get("index.refresh_interval"),
        "cluster_status": health_payload.get("status"),
        "cluster_nodes": health_payload.get("number_of_nodes"),
    }
