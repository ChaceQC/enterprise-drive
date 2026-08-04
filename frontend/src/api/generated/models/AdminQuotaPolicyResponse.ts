/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type AdminQuotaPolicyResponse = {
    created_at: string;
    extensions: Array<string>;
    id: string;
    is_active: boolean;
    limit_bytes: number;
    max_file_size_bytes: (number | null);
    mime_prefixes: Array<string>;
    name: string;
    priority: number;
    tenant_id: string;
    updated_at: string;
    used_bytes: number;
};
