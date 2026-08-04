/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AddSpaceMemberRequest } from '../models/AddSpaceMemberRequest';
import type { CreateSpaceRequest } from '../models/CreateSpaceRequest';
import type { CreateSpaceResponse } from '../models/CreateSpaceResponse';
import type { RemoveSpaceMemberResponse } from '../models/RemoveSpaceMemberResponse';
import type { SpaceListResponse } from '../models/SpaceListResponse';
import type { SpaceMemberListResponse } from '../models/SpaceMemberListResponse';
import type { SpaceMemberResponse } from '../models/SpaceMemberResponse';
import type { UpdateSpaceMemberRequest } from '../models/UpdateSpaceMemberRequest';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class SpacesService {
    /**
     * List Spaces
     * @returns SpaceListResponse Successful Response
     * @throws ApiError
     */
    public static listSpacesApiV1SpacesGet({
        cursor,
        pageSize = 50,
    }: {
        cursor?: (string | null),
        pageSize?: number,
    }): CancelablePromise<SpaceListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/spaces',
            query: {
                'cursor': cursor,
                'page_size': pageSize,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Create Space
     * @returns CreateSpaceResponse Successful Response
     * @throws ApiError
     */
    public static createSpaceApiV1SpacesPost({
        requestBody,
    }: {
        requestBody: CreateSpaceRequest,
    }): CancelablePromise<CreateSpaceResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/spaces',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * List Space Members
     * @returns SpaceMemberListResponse Successful Response
     * @throws ApiError
     */
    public static listSpaceMembersApiV1SpacesSpaceIdMembersGet({
        spaceId,
    }: {
        spaceId: string,
    }): CancelablePromise<SpaceMemberListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/spaces/{space_id}/members',
            path: {
                'space_id': spaceId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Add Space Member
     * @returns SpaceMemberResponse Successful Response
     * @throws ApiError
     */
    public static addSpaceMemberApiV1SpacesSpaceIdMembersPost({
        spaceId,
        requestBody,
    }: {
        spaceId: string,
        requestBody: AddSpaceMemberRequest,
    }): CancelablePromise<SpaceMemberResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/spaces/{space_id}/members',
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
    /**
     * Remove Space Member
     * @returns RemoveSpaceMemberResponse Successful Response
     * @throws ApiError
     */
    public static removeSpaceMemberApiV1SpacesSpaceIdMembersUserIdDelete({
        spaceId,
        userId,
    }: {
        spaceId: string,
        userId: string,
    }): CancelablePromise<RemoveSpaceMemberResponse> {
        return __request(OpenAPI, {
            method: 'DELETE',
            url: '/api/v1/spaces/{space_id}/members/{user_id}',
            path: {
                'space_id': spaceId,
                'user_id': userId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Update Space Member
     * @returns SpaceMemberResponse Successful Response
     * @throws ApiError
     */
    public static updateSpaceMemberApiV1SpacesSpaceIdMembersUserIdPatch({
        spaceId,
        userId,
        requestBody,
    }: {
        spaceId: string,
        userId: string,
        requestBody: UpdateSpaceMemberRequest,
    }): CancelablePromise<SpaceMemberResponse> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/spaces/{space_id}/members/{user_id}',
            path: {
                'space_id': spaceId,
                'user_id': userId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
