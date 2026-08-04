/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { TrashNodeResponse } from './TrashNodeResponse';
export type TrashListResponse = {
    items: Array<TrashNodeResponse>;
    next_cursor?: (string | null);
    space_id: string;
};
