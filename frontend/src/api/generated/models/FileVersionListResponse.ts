/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { FileVersionResponse } from './FileVersionResponse';
export type FileVersionListResponse = {
    current_version_id: (string | null);
    items: Array<FileVersionResponse>;
    next_cursor?: (string | null);
    node_id: string;
};
