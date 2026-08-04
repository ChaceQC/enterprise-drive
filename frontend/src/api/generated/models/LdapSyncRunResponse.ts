/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type LdapSyncRunResponse = {
    created_at: string;
    cursor_after: (string | null);
    cursor_before: (string | null);
    error_code: (string | null);
    error_message: (string | null);
    finished_at: (string | null);
    id: string;
    mode: 'dry_run' | 'full' | 'incremental';
    requested_by: (string | null);
    source_id: string;
    source_version: number;
    started_at: (string | null);
    stats: Record<string, number>;
    status: 'queued' | 'running' | 'succeeded' | 'failed';
    tenant_id: string;
};
