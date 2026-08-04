/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type AdminUserResponse = {
    created_at: string;
    display_name: string;
    email: (string | null);
    failed_login_attempts: number;
    id: string;
    is_active: boolean;
    is_super_admin: boolean;
    locked: boolean;
    locked_until: (string | null);
    must_change_password: boolean;
    tenant_id: string;
    updated_at: string;
    username: string;
    version: number;
};
