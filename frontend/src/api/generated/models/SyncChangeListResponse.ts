/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { SyncChangeResponse } from './SyncChangeResponse';
export type SyncChangeListResponse = {
    cursor_expires_at: string;
    has_more: boolean;
    items: Array<SyncChangeResponse>;
    next_cursor: string;
    root_node_id: string;
    space_id: string;
};
