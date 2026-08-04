/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { SearchFilesResponse } from '../models/SearchFilesResponse';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class SearchService {
    /**
     * Search Files
     * @returns SearchFilesResponse Successful Response
     * @throws ApiError
     */
    public static searchFilesApiV1SearchGet({
        q,
        limit = 20,
        cursor,
    }: {
        q: string,
        limit?: number,
        cursor?: (string | null),
    }): CancelablePromise<SearchFilesResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/search',
            query: {
                'q': q,
                'limit': limit,
                'cursor': cursor,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
