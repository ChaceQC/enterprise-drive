/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type AdminJobResponse = {
    completed_at: (string | null);
    content_sha256: (string | null);
    content_type: (string | null);
    created_at: string;
    created_by: string;
    error_code: (string | null);
    error_message: (string | null);
    file_name: (string | null);
    id: string;
    kind: 'maintenance' | 'export';
    operation: string;
    parameters: Record<string, any>;
    result: Record<string, any>;
    signature_algorithm: (string | null);
    signature_key_id: (string | null);
    signature_value: (string | null);
    size_bytes: (number | null);
    started_at: (string | null);
    status: 'pending' | 'running' | 'succeeded' | 'failed' | 'expired';
    tenant_id: string;
    updated_at: string;
    version: number;
};
