/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type AdminQuotaAccountResponse = {
    created_at: string;
    id: string;
    limit_bytes: number;
    owner_id: string;
    owner_type: 'space' | 'tenant' | 'user' | 'policy';
    remaining_bytes: number;
    tenant_id: string;
    updated_at: string;
    used_bytes: number;
};
