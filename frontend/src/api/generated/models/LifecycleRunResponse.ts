/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type LifecycleRunResponse = {
    completed_at: (string | null);
    created_at: string;
    created_by: string;
    dry_run: boolean;
    error_code: (string | null);
    id: string;
    policy_version: number;
    result: Record<string, any>;
    started_at: (string | null);
    status: 'pending' | 'running' | 'succeeded' | 'failed';
    updated_at: string;
};
