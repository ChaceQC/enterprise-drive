from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from uuid import UUID

import pytest

from performance.target_audit import _audit_records
from performance.target_data import _validate_large_target
from performance.target_opensearch import _document_action
from performance.target_state import (
    TargetDataState,
    audit_action_for_run,
    deterministic_uuid,
    new_target_state,
    opensearch_index_for_run,
    read_target_state,
    update_target_state,
    write_target_state,
)


def _state(*, opensearch_target: int = 10, audit_target: int = 20) -> TargetDataState:
    return new_target_state(
        run_id="be029-unit",
        tenant_slug="default",
        username="admin",
        tenant_id=UUID(int=1),
        actor_id=UUID(int=2),
        opensearch_target=opensearch_target,
        audit_target=audit_target,
        search_term="be029-anchor",
    )


def test_target_state_round_trip_is_utf8_and_atomic(tmp_path: Path) -> None:
    path = tmp_path / "target" / "state.json"
    state = _state()
    write_target_state(state, path)

    loaded = read_target_state(path)
    assert loaded == state or loaded.updated_at >= state.updated_at
    assert json.loads(path.read_text(encoding="utf-8"))["run_id"] == "be029-unit"
    assert not list(path.parent.glob("*.tmp"))


def test_target_state_rejects_mismatched_index_and_run_id(tmp_path: Path) -> None:
    state = _state()
    invalid = update_target_state(state, opensearch_index="production-index")
    path = tmp_path / "invalid-state.json"
    path.write_text(json.dumps(asdict(invalid)), encoding="utf-8")

    with pytest.raises(ValueError, match="index"):
        read_target_state(path)


def test_target_ids_are_stable_and_distinct() -> None:
    first = deterministic_uuid(run_id="be029-unit", kind="audit", sequence=1)
    second = deterministic_uuid(run_id="be029-unit", kind="audit", sequence=1)
    different = deterministic_uuid(run_id="be029-unit", kind="audit", sequence=2)

    assert first == second
    assert first != different


def test_target_names_are_scoped_to_run() -> None:
    assert opensearch_index_for_run("be029-unit") == "be029-be029-unit"
    assert audit_action_for_run("be029-unit") == "performance.target.audit.be029-unit"


def test_opensearch_action_has_one_search_anchor_and_bounded_fields() -> None:
    state = _state()
    anchor = _document_action(state, 0)
    noise = _document_action(state, 1)

    assert anchor["_index"] == state.opensearch_index
    assert anchor["_id"] == "be029-unit:000000000000"
    assert anchor["_source"]["name"] == "be029-anchor"
    assert noise["_source"]["name"] == "perf-noise-000000000001.bin"
    assert anchor["_source"]["benchmark_run_id"] == state.run_id
    assert anchor["_source"]["acl_tokens"] == [f"user:{state.actor_id}"]


def test_audit_records_are_deterministic_and_tagged() -> None:
    state = _state()
    records = _audit_records(state=state, start=3, stop=5)
    repeated = _audit_records(state=state, start=3, stop=5)

    assert records == repeated
    assert len(records) == 2
    assert records[0][3] == "user"
    assert records[0][4] == audit_action_for_run(state.run_id)
    assert records[0][9] == "be029:be029-unit:000000000003"
    assert json.loads(records[0][12])["synthetic"] is True


def test_large_target_requires_explicit_confirmation() -> None:
    with pytest.raises(ValueError, match="confirm-large-target"):
        _validate_large_target(opensearch_docs=100_000, audit_rows=0, confirmed=False)

    _validate_large_target(opensearch_docs=100_000, audit_rows=0, confirmed=True)
    _validate_large_target(opensearch_docs=100, audit_rows=100, confirmed=False)
