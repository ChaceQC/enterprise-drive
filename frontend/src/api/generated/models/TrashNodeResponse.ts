/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type TrashNodeResponse = {
    created_at: string;
    current_version_id: (string | null);
    deleted_at: string;
    deleted_by: (string | null);
    id: string;
    name: string;
    node_type: string;
    parent_id: (string | null);
    permission_version: number;
    permissions?: Record<string, boolean>;
    space_id: string;
    tenant_id: string;
    updated_at: string;
};
