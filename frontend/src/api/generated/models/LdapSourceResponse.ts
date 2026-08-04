/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type LdapSourceResponse = {
    attribute_mapping: Record<string, string>;
    base_dn: string;
    bind_dn: (string | null);
    bind_password_configured: boolean;
    created_at: string;
    department_base_dn: (string | null);
    department_filter: (string | null);
    enabled: boolean;
    group_base_dn: (string | null);
    group_filter: (string | null);
    id: string;
    last_success_at: (string | null);
    name: string;
    server_url: string;
    slug: string;
    sync_cursor: (string | null);
    tenant_id: string;
    updated_at: string;
    user_base_dn: string;
    user_filter: string;
    version: number;
};
