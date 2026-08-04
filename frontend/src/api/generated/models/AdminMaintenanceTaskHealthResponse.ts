/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type AdminMaintenanceTaskHealthResponse = {
    alert_active: boolean;
    consecutive_failures: number;
    expected_interval_seconds: number;
    last_failure_at: (string | null);
    last_finished_at: (string | null);
    last_status: string;
    last_success_at: (string | null);
    stale: boolean;
    task_name: 'upload.expire_sessions' | 'file.cleanup_expired_trash' | 'share.expire_shares' | 'preview.cleanup_artifacts' | 'file.process_tree_operations' | 'file.cleanup_unreferenced_blobs' | 'file.cleanup_orphaned_objects' | 'quota.reconcile_space_usage' | 'admin.cleanup_expired_exports';
};
