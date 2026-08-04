/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type AdminAuditArchiveResponse = {
    content_sha256: (string | null);
    created_at: string;
    delete_source: boolean;
    error_code: (string | null);
    file_name: (string | null);
    id: string;
    period_end: string;
    period_start: string;
    row_count: number;
    signature_algorithm: (string | null);
    signature_key_id: (string | null);
    size_bytes: (number | null);
    source_deleted_at: (string | null);
    status: string;
    updated_at: string;
};
