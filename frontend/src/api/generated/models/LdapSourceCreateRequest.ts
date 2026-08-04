/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type LdapSourceCreateRequest = {
    attribute_mapping: Record<string, string>;
    base_dn: string;
    bind_dn?: (string | null);
    bind_password_ref?: (string | null);
    department_base_dn?: (string | null);
    department_filter?: (string | null);
    enabled?: boolean;
    group_base_dn?: (string | null);
    group_filter?: (string | null);
    name: string;
    server_url: string;
    slug: string;
    user_base_dn: string;
    user_filter: string;
};
