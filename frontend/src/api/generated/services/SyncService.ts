/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { SyncChangeListResponse } from '../models/SyncChangeListResponse';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class SyncService {
    /**
     * List Sync Changes
     * @returns SyncChangeListResponse Successful Response
     * @throws ApiError
     */
    public static listSyncChangesApiV1SyncChangesGet({
        spaceId,
        rootNodeId,
        cursor,
        pageSize = 100,
    }: {
        spaceId: string,
        rootNodeId: string,
        cursor?: (string | null),
        pageSize?: number,
    }): CancelablePromise<SyncChangeListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/sync/changes',
            query: {
                'space_id': spaceId,
                'root_node_id': rootNodeId,
                'cursor': cursor,
                'page_size': pageSize,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
