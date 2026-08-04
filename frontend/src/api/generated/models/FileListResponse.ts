/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { FileNodeResponse } from './FileNodeResponse';
export type FileListResponse = {
    items: Array<FileNodeResponse>;
    next_cursor?: (string | null);
    parent_id: string;
    space_id: string;
};
