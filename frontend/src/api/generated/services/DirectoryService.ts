/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { DirectoryDepartmentListResponse } from '../models/DirectoryDepartmentListResponse';
import type { DirectoryGroupListResponse } from '../models/DirectoryGroupListResponse';
import type { DirectoryUserListResponse } from '../models/DirectoryUserListResponse';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class DirectoryService {
    /**
     * List Directory Departments
     * @returns DirectoryDepartmentListResponse Successful Response
     * @throws ApiError
     */
    public static listDirectoryDepartmentsApiV1DirectoryDepartmentsGet({
        q,
        cursor,
        pageSize = 50,
    }: {
        q?: (string | null),
        cursor?: (string | null),
        pageSize?: number,
    }): CancelablePromise<DirectoryDepartmentListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/directory/departments',
            query: {
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
     * List Directory Groups
     * @returns DirectoryGroupListResponse Successful Response
     * @throws ApiError
     */
    public static listDirectoryGroupsApiV1DirectoryGroupsGet({
        q,
        cursor,
        pageSize = 50,
    }: {
        q?: (string | null),
        cursor?: (string | null),
        pageSize?: number,
    }): CancelablePromise<DirectoryGroupListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/directory/groups',
            query: {
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
     * List Directory Users
     * @returns DirectoryUserListResponse Successful Response
     * @throws ApiError
     */
    public static listDirectoryUsersApiV1DirectoryUsersGet({
        q,
        cursor,
        pageSize = 50,
    }: {
        q?: (string | null),
        cursor?: (string | null),
        pageSize?: number,
    }): CancelablePromise<DirectoryUserListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/directory/users',
            query: {
                'q': q,
                'cursor': cursor,
                'page_size': pageSize,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
