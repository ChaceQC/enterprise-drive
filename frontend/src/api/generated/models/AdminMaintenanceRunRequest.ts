/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type AdminMaintenanceRunRequest = {
    dry_run?: boolean;
    limit?: number;
    repair?: boolean;
    retention_days?: (number | null);
    scan_all?: boolean;
    task_name: 'upload.expire_sessions' | 'file.cleanup_expired_trash' | 'share.expire_shares' | 'preview.cleanup_artifacts' | 'file.process_tree_operations' | 'file.cleanup_unreferenced_blobs' | 'file.cleanup_orphaned_objects' | 'quota.reconcile_space_usage' | 'admin.cleanup_expired_exports';
};
