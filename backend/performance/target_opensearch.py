from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from opensearchpy import OpenSearch, helpers

from performance.target_state import (
    TargetDataState,
    deterministic_uuid,
    update_target_state,
    write_target_state,
)


@dataclass(frozen=True)
class OpenSearchGenerationResult:
    attempted: int
    indexed: int
    total_count: int
    store_bytes: int
    elapsed_seconds: float
    completed: bool


def build_opensearch_client(url: str) -> OpenSearch:
    return OpenSearch(hosts=[url], timeout=60, max_retries=3, retry_on_timeout=True)


def generate_opensearch_documents(
    *,
    client: OpenSearch,
    state: TargetDataState,
    state_path: Path,
    batch_size: int,
    max_batches: int,
    throttle_seconds: float,
) -> tuple[TargetDataState, OpenSearchGenerationResult]:
    if batch_size <= 0:
        raise ValueError("OpenSearch batch_size 必须大于 0")
    if max_batches < 0:
        raise ValueError("max_batches 不能为负数")
    if throttle_seconds < 0:
        raise ValueError("throttle_seconds 不能为负数")

    _ensure_target_index(client=client, state=state)
    started = time.perf_counter()
    attempted = 0
    indexed = 0
    batches = 0
    current = update_target_state(state, status="opensearch-generating")
    write_target_state(current, state_path)

    while current.opensearch_completed < current.opensearch_target:
        if max_batches and batches >= max_batches:
            break
        start = current.opensearch_completed
        stop = min(start + batch_size, current.opensearch_target)
        actions = [_document_action(current, sequence) for sequence in range(start, stop)]
        success_count, errors = helpers.bulk(
            client,
            actions,
            chunk_size=batch_size,
            max_retries=3,
            raise_on_error=False,
            raise_on_exception=True,
            request_timeout=120,
        )
        if errors:
            first_error = errors[0] if isinstance(errors, list) else errors
            raise RuntimeError(f"OpenSearch bulk 写入失败: {first_error}")
        attempted += stop - start
        indexed += int(success_count)
        batches += 1
        current = update_target_state(current, opensearch_completed=stop)
        write_target_state(current, state_path)
        if throttle_seconds:
            time.sleep(throttle_seconds)

    if current.opensearch_completed >= current.opensearch_target:
        client.indices.put_settings(
            index=current.opensearch_index,
            body={"index": {"refresh_interval": "1s"}},
        )
    client.indices.refresh(index=current.opensearch_index)
    total_count = count_target_documents(client=client, state=current)
    completed = current.opensearch_completed >= current.opensearch_target
    current = update_target_state(
        current,
        status="opensearch-ready" if completed else "opensearch-paused",
    )
    write_target_state(current, state_path)
    return current, OpenSearchGenerationResult(
        attempted=attempted,
        indexed=indexed,
        total_count=total_count,
        store_bytes=_index_store_bytes(client=client, index_name=current.opensearch_index),
        elapsed_seconds=round(time.perf_counter() - started, 6),
        completed=completed,
    )


def count_target_documents(*, client: OpenSearch, state: TargetDataState) -> int:
    if not client.indices.exists(index=state.opensearch_index):
        return 0
    response = client.count(
        index=state.opensearch_index,
        body={"query": {"term": {"benchmark_run_id": state.run_id}}},
    )
    return int(response.get("count", 0))


def delete_target_index(*, client: OpenSearch, state: TargetDataState) -> bool:
    if not client.indices.exists(index=state.opensearch_index):
        return False
    _validate_index_owner(client=client, state=state)
    client.indices.delete(index=state.opensearch_index)
    return True


def _ensure_target_index(*, client: OpenSearch, state: TargetDataState) -> None:
    if client.indices.exists(index=state.opensearch_index):
        _validate_index_owner(client=client, state=state)
        client.indices.put_settings(
            index=state.opensearch_index,
            body={"index": {"refresh_interval": "-1"}},
        )
        return
    client.indices.create(
        index=state.opensearch_index,
        body={
            "settings": {
                "index": {
                    "number_of_shards": 1,
                    "number_of_replicas": 0,
                    "refresh_interval": "-1",
                }
            },
            "mappings": {
                "_meta": {
                    "schema_version": state.schema_version,
                    "benchmark_run_id": state.run_id,
                },
                "properties": {
                    "benchmark_run_id": {"type": "keyword"},
                    "tenant_id": {"type": "keyword"},
                    "space_id": {"type": "keyword"},
                    "node_id": {"type": "keyword"},
                    "parent_id": {"type": "keyword"},
                    "owner_id": {"type": "keyword"},
                    "version_id": {"type": "keyword"},
                    "blob_id": {"type": "keyword"},
                    "name": {"type": "text"},
                    "normalized_name": {"type": "text"},
                    "mime_type": {"type": "keyword"},
                    "size_bytes": {"type": "long"},
                    "hash_algo": {"type": "keyword"},
                    "content_hash": {"type": "keyword"},
                    "acl_tokens": {"type": "keyword"},
                    "deny_acl_tokens": {"type": "keyword"},
                    "created_at": {"type": "date"},
                    "updated_at": {"type": "date"},
                    "is_deleted": {"type": "boolean"},
                    "content": {"type": "text"},
                },
            },
        },
    )


def _validate_index_owner(*, client: OpenSearch, state: TargetDataState) -> None:
    mapping = client.indices.get_mapping(index=state.opensearch_index)
    index_mapping = mapping.get(state.opensearch_index, {})
    mappings = index_mapping.get("mappings", {}) if isinstance(index_mapping, dict) else {}
    metadata = mappings.get("_meta", {}) if isinstance(mappings, dict) else {}
    if not isinstance(metadata, dict) or metadata.get("benchmark_run_id") != state.run_id:
        raise ValueError("拒绝复用或删除不属于当前 BE-029 run 的 OpenSearch index")


def _document_action(state: TargetDataState, sequence: int) -> dict[str, Any]:
    node_id = deterministic_uuid(run_id=state.run_id, kind="node", sequence=sequence)
    search_match = sequence == 0
    name = state.search_term if search_match else f"perf-noise-{sequence:012d}.bin"
    content_hash = _content_hash(run_id=state.run_id, sequence=sequence)
    source = {
        "benchmark_run_id": state.run_id,
        "tenant_id": state.tenant_id,
        "space_id": str(deterministic_uuid(run_id=state.run_id, kind="space", sequence=0)),
        "node_id": str(node_id),
        "parent_id": str(deterministic_uuid(run_id=state.run_id, kind="parent", sequence=0)),
        "owner_id": state.actor_id,
        "version_id": str(
            deterministic_uuid(run_id=state.run_id, kind="version", sequence=sequence)
        ),
        "blob_id": str(deterministic_uuid(run_id=state.run_id, kind="blob", sequence=sequence)),
        "name": name,
        "normalized_name": name.lower(),
        "mime_type": "application/octet-stream",
        "size_bytes": 1024 + sequence % 65536,
        "hash_algo": "sha256",
        "content_hash": content_hash,
        "acl_tokens": [f"user:{state.actor_id}"],
        "deny_acl_tokens": [],
        "created_at": state.created_at,
        "updated_at": state.created_at,
        "is_deleted": False,
        "content": "enterprise drive target benchmark corpus",
    }
    return {
        "_op_type": "index",
        "_index": state.opensearch_index,
        "_id": f"{state.run_id}:{sequence:012d}",
        "_source": source,
    }


def _content_hash(*, run_id: str, sequence: int) -> str:
    prefix = hashlib.sha256(run_id.encode()).hexdigest()[:16]
    return f"{prefix}{sequence:048x}"[-64:]


def _index_store_bytes(*, client: OpenSearch, index_name: str) -> int:
    stats = client.indices.stats(index=index_name, metric="store")
    indices = stats.get("indices", {})
    if not isinstance(indices, dict):
        return 0
    index_stats = indices.get(index_name, {})
    if not isinstance(index_stats, dict):
        return 0
    total = index_stats.get("total", {})
    store = total.get("store", {}) if isinstance(total, dict) else {}
    return int(store.get("size_in_bytes", 0)) if isinstance(store, dict) else 0
