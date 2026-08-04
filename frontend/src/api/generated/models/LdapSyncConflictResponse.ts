/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type LdapSyncConflictResponse = {
    code: string;
    created_at: string;
    details: Record<string, any>;
    external_id: string;
    id: string;
    object_type: 'user' | 'department' | 'group' | 'membership';
    run_id: string;
    source_id: string;
};
