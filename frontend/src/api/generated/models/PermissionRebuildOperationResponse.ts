/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type PermissionRebuildOperationResponse = {
    attempt_count: number;
    completed_at: (string | null);
    created_at: string;
    error_code: (string | null);
    id: string;
    indexed_count: number;
    permission_version: number;
    processed_count: number;
    requested_by: (string | null);
    restart_requested: boolean;
    root_node_id: (string | null);
    scope: 'space' | 'node';
    space_id: string;
    status: 'pending' | 'running' | 'completed' | 'failed';
    tenant_id: string;
    total_count: number;
    updated_at: string;
};
