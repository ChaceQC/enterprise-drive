/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type FileTreeOperationResponse = {
    completed_at?: (string | null);
    created_at: string;
    error_code?: (string | null);
    node_id: string;
    operation: 'delete' | 'restore' | 'purge';
    operation_id: string;
    processed_count: number;
    released_bytes: number;
    status: 'pending' | 'running' | 'completed' | 'failed';
    total_count: number;
    updated_at: string;
};
