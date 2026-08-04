/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type AdminTreeOperationResponse = {
    attempt_count: number;
    completed_at: (string | null);
    created_at: string;
    error_code: (string | null);
    id: string;
    node_id: string;
    operation: 'delete' | 'restore' | 'purge';
    processed_count: number;
    released_bytes: number;
    space_id: string;
    status: 'pending' | 'running' | 'completed' | 'failed';
    total_count: number;
    updated_at: string;
    user_id: string;
};
