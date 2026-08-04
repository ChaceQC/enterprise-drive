/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type CreateFolderRequest = {
    conflict_policy?: 'fail' | 'keep_both' | 'replace';
    name: string;
    parent_id?: (string | null);
    space_id: string;
};
