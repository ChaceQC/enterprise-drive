/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type AdminDepartmentUpdateRequest = {
    expected_version: number;
    move_to_root?: boolean;
    name?: (string | null);
    parent_id?: (string | null);
    sort_order?: (number | null);
    status?: ('active' | 'disabled' | null);
};
