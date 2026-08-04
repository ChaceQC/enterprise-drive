/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type SyncChangeResponse = {
    change_type: string;
    changed_at: string;
    client_operation_id: (string | null);
    current_version_id: (string | null);
    name: (string | null);
    node_id: string;
    node_type: (string | null);
    parent_id: (string | null);
    permission_version: (number | null);
    sequence: number;
    space_id: string;
    tombstone: boolean;
};
