/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type InitUploadRequest = {
    conflict_policy?: string;
    content_hash: string;
    expected_current_version_id?: (string | null);
    file_name: string;
    hash_algo?: string;
    mime_type?: (string | null);
    parent_id: string;
    size_bytes: number;
    space_id: string;
    target_node_id?: (string | null);
};
