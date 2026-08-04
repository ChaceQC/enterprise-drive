from __future__ import annotations

from app.core.config import Settings


def build_beat_schedule(settings: Settings) -> dict[str, dict[str, object]]:
    outbox_interval = float(settings.outbox_dispatch_interval_seconds)
    batch_size = settings.maintenance_task_batch_size

    return {
        "dispatch-audit-outbox": {
            "task": "audit.dispatch_outbox",
            "schedule": outbox_interval,
            "options": {"queue": "audit"},
        },
        "dispatch-permission-outbox": {
            "task": "permission.invalidate_cache",
            "schedule": outbox_interval,
            "options": {"queue": "permission"},
        },
        "dispatch-search-outbox": {
            "task": "search.dispatch_outbox",
            "schedule": outbox_interval,
            "options": {"queue": "search"},
        },
        "dispatch-preview-outbox": {
            "task": "preview.dispatch_outbox",
            "schedule": outbox_interval,
            "options": {"queue": "preview"},
        },
        "dispatch-share-outbox": {
            "task": "share.dispatch_outbox",
            "schedule": outbox_interval,
            "options": {"queue": "permission"},
        },
        "ensure-audit-partitions": {
            "task": "audit.ensure_partitions",
            "schedule": float(settings.audit_partition_maintenance_interval_seconds),
            "kwargs": {"months_ahead": settings.audit_partition_months_ahead},
            "options": {"queue": "maintenance"},
        },
        "archive-audit-retention": {
            "task": "audit.archive_retention",
            "schedule": float(settings.audit_archive_interval_seconds),
            "kwargs": {"delete_source": settings.audit_archive_delete_source},
            "options": {"queue": "maintenance"},
        },
        "expire-upload-sessions": {
            "task": "upload.expire_sessions",
            "schedule": float(settings.upload_cleanup_interval_seconds),
            "kwargs": {"limit": batch_size},
            "options": {"queue": "maintenance"},
        },
        "cleanup-expired-trash": {
            "task": "file.cleanup_expired_trash",
            "schedule": float(settings.trash_cleanup_interval_seconds),
            "kwargs": {"limit": batch_size},
            "options": {"queue": "maintenance"},
        },
        "expire-shares": {
            "task": "share.expire_shares",
            "schedule": float(settings.share_expiry_interval_seconds),
            "kwargs": {"limit": batch_size},
            "options": {"queue": "maintenance"},
        },
        "cleanup-preview-artifacts": {
            "task": "preview.cleanup_artifacts",
            "schedule": float(settings.preview_cleanup_interval_seconds),
            "kwargs": {
                "limit": batch_size,
                "retention_days": settings.preview_artifact_retention_days,
                "dry_run": False,
                "scan_all": True,
            },
            "options": {"queue": "maintenance"},
        },
        "process-file-tree-operations": {
            "task": "file.process_tree_operations",
            "schedule": float(settings.file_tree_operation_interval_seconds),
            "kwargs": {"limit": batch_size},
            "options": {"queue": "maintenance"},
        },
        "process-permission-rebuilds": {
            "task": "governance.process_permission_rebuilds",
            "schedule": float(settings.file_tree_operation_interval_seconds),
            "kwargs": {"limit": batch_size},
            "options": {"queue": "maintenance"},
        },
        "cleanup-unreferenced-blobs": {
            "task": "file.cleanup_unreferenced_blobs",
            "schedule": float(settings.blob_cleanup_interval_seconds),
            "kwargs": {"limit": batch_size},
            "options": {"queue": "maintenance"},
        },
        "scan-orphaned-objects": {
            "task": "file.cleanup_orphaned_objects",
            "schedule": float(settings.orphan_object_scan_interval_seconds),
            "kwargs": {
                "limit": batch_size,
                "dry_run": True,
                "scan_all": True,
            },
            "options": {"queue": "maintenance"},
        },
        "report-quota-drift": {
            "task": "quota.reconcile_space_usage",
            "schedule": float(settings.quota_reconciliation_interval_seconds),
            "kwargs": {
                "limit": batch_size,
                "repair": False,
                "scan_all": True,
            },
            "options": {"queue": "maintenance"},
        },
        "cleanup-expired-admin-exports": {
            "task": "admin.cleanup_expired_exports",
            "schedule": float(settings.admin_export_cleanup_interval_seconds),
            "kwargs": {"limit": batch_size},
            "options": {"queue": "maintenance"},
        },
    }
