/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AdminSpaceCreateRequest } from '../models/AdminSpaceCreateRequest';
import type { AdminSpaceListResponse } from '../models/AdminSpaceListResponse';
import type { AdminSpaceResponse } from '../models/AdminSpaceResponse';
import type { AdminSpaceUpdateRequest } from '../models/AdminSpaceUpdateRequest';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class AdminSpacesService {
    /**
     * List Admin Spaces
     * @returns AdminSpaceListResponse Successful Response
     * @throws ApiError
     */
    public static listAdminSpacesApiV1AdminSpacesGet({
        isActive,
        spaceType,
        ownerId,
        q,
        cursor,
        pageSize = 50,
    }: {
        isActive?: (boolean | null),
        spaceType?: ('team' | 'personal' | null),
        ownerId?: (string | null),
        q?: (string | null),
        cursor?: (string | null),
        pageSize?: number,
    }): CancelablePromise<AdminSpaceListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/admin/spaces',
            query: {
                'is_active': isActive,
                'space_type': spaceType,
                'owner_id': ownerId,
                'q': q,
                'cursor': cursor,
                'page_size': pageSize,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Create Admin Space
     * @returns AdminSpaceResponse Successful Response
     * @throws ApiError
     */
    public static createAdminSpaceApiV1AdminSpacesPost({
        requestBody,
    }: {
        requestBody: AdminSpaceCreateRequest,
    }): CancelablePromise<AdminSpaceResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/admin/spaces',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Deactivate Admin Space
     * @returns AdminSpaceResponse Successful Response
     * @throws ApiError
     */
    public static deactivateAdminSpaceApiV1AdminSpacesSpaceIdDelete({
        spaceId,
        expectedVersion,
    }: {
        spaceId: string,
        expectedVersion: number,
    }): CancelablePromise<AdminSpaceResponse> {
        return __request(OpenAPI, {
            method: 'DELETE',
            url: '/api/v1/admin/spaces/{space_id}',
            path: {
                'space_id': spaceId,
            },
            query: {
                'expected_version': expectedVersion,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get Admin Space
     * @returns AdminSpaceResponse Successful Response
     * @throws ApiError
     */
    public static getAdminSpaceApiV1AdminSpacesSpaceIdGet({
        spaceId,
    }: {
        spaceId: string,
    }): CancelablePromise<AdminSpaceResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/admin/spaces/{space_id}',
            path: {
                'space_id': spaceId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Update Admin Space
     * @returns AdminSpaceResponse Successful Response
     * @throws ApiError
     */
    public static updateAdminSpaceApiV1AdminSpacesSpaceIdPatch({
        spaceId,
        requestBody,
    }: {
        spaceId: string,
        requestBody: AdminSpaceUpdateRequest,
    }): CancelablePromise<AdminSpaceResponse> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/admin/spaces/{space_id}',
            path: {
                'space_id': spaceId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
