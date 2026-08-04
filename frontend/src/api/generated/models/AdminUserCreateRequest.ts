/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type AdminUserCreateRequest = {
    display_name: string;
    email?: (string | null);
    is_active?: boolean;
    is_super_admin?: boolean;
    must_change_password?: boolean;
    password: string;
    username: string;
};
