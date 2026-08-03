from __future__ import annotations

from app.core.config import Settings
from app.infrastructure.queue.schedule import build_beat_schedule


def test_beat_schedule_routes_outbox_dispatchers_to_dedicated_queues() -> None:
    schedule = build_beat_schedule(
        Settings(
            outbox_dispatch_interval_seconds=7,
        )
    )

    expected = {
        "dispatch-audit-outbox": ("audit.dispatch_outbox", "audit"),
        "dispatch-permission-outbox": ("permission.invalidate_cache", "permission"),
        "dispatch-search-outbox": ("search.dispatch_outbox", "search"),
        "dispatch-preview-outbox": ("preview.dispatch_outbox", "preview"),
        "dispatch-share-outbox": ("share.dispatch_outbox", "permission"),
    }
    for entry_name, (task_name, queue_name) in expected.items():
        entry = schedule[entry_name]
        assert entry["task"] == task_name
        assert entry["schedule"] == 7.0
        assert entry["options"] == {"queue": queue_name}


def test_beat_schedule_keeps_destructive_maintenance_in_safe_modes() -> None:
    schedule = build_beat_schedule(
        Settings(
            maintenance_task_batch_size=23,
            upload_cleanup_interval_seconds=60,
            trash_cleanup_interval_seconds=120,
            share_expiry_interval_seconds=135,
            preview_cleanup_interval_seconds=150,
            preview_artifact_retention_days=31,
            blob_cleanup_interval_seconds=180,
            file_tree_operation_interval_seconds=210,
            orphan_object_scan_interval_seconds=240,
            quota_reconciliation_interval_seconds=300,
        )
    )

    assert schedule["expire-upload-sessions"]["schedule"] == 60.0
    assert schedule["cleanup-expired-trash"]["schedule"] == 120.0
    assert schedule["expire-shares"]["schedule"] == 135.0
    assert schedule["cleanup-preview-artifacts"]["schedule"] == 150.0
    assert schedule["cleanup-unreferenced-blobs"]["schedule"] == 180.0
    assert schedule["process-file-tree-operations"]["schedule"] == 210.0
    assert schedule["scan-orphaned-objects"]["schedule"] == 240.0
    assert schedule["report-quota-drift"]["schedule"] == 300.0
    assert schedule["expire-upload-sessions"]["kwargs"] == {"limit": 23}
    assert schedule["cleanup-expired-trash"]["kwargs"] == {"limit": 23}
    assert schedule["expire-shares"]["kwargs"] == {"limit": 23}
    assert schedule["cleanup-preview-artifacts"]["kwargs"] == {
        "limit": 23,
        "retention_days": 31,
        "dry_run": False,
        "scan_all": True,
    }
    assert schedule["cleanup-unreferenced-blobs"]["kwargs"] == {"limit": 23}
    assert schedule["process-file-tree-operations"]["kwargs"] == {"limit": 23}
    assert schedule["scan-orphaned-objects"]["kwargs"] == {
        "limit": 23,
        "dry_run": True,
        "scan_all": True,
    }
    assert schedule["report-quota-drift"]["kwargs"] == {
        "limit": 23,
        "repair": False,
        "scan_all": True,
    }
