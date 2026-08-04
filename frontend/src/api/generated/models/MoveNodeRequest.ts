/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type MoveNodeRequest = {
    conflict_policy?: 'fail' | 'keep_both' | 'replace';
    expected_current_version_id?: (string | null);
    new_name?: (string | null);
    target_parent_id: string;
};
