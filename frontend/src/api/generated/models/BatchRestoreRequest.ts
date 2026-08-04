/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type BatchRestoreRequest = {
    conflict_policy?: 'fail' | 'keep_both' | 'replace';
    new_name?: (string | null);
    node_ids: Array<string>;
    target_parent_id?: (string | null);
};
