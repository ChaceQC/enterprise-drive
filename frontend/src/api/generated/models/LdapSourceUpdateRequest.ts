/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type LdapSourceUpdateRequest = {
    attribute_mapping?: (Record<string, string> | null);
    base_dn?: (string | null);
    bind_dn?: (string | null);
    bind_password_ref?: (string | null);
    clear_bind_dn?: boolean;
    clear_bind_password_ref?: boolean;
    clear_department_base_dn?: boolean;
    clear_department_filter?: boolean;
    clear_group_base_dn?: boolean;
    clear_group_filter?: boolean;
    department_base_dn?: (string | null);
    department_filter?: (string | null);
    enabled?: (boolean | null);
    expected_version: number;
    group_base_dn?: (string | null);
    group_filter?: (string | null);
    name?: (string | null);
    server_url?: (string | null);
    user_base_dn?: (string | null);
    user_filter?: (string | null);
};
