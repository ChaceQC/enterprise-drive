/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type LifecyclePolicyUpdateRequest = {
    cleanup_orphaned_objects?: boolean;
    cleanup_unreferenced_blobs?: boolean;
    expected_version: number;
    expire_shares?: boolean;
    expire_uploads?: boolean;
    preview_retention_days: number;
    trash_retention_days: number;
};
