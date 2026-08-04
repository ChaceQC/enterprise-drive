/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AdminDepartmentCreateRequest } from '../models/AdminDepartmentCreateRequest';
import type { AdminDepartmentListResponse } from '../models/AdminDepartmentListResponse';
import type { AdminDepartmentResponse } from '../models/AdminDepartmentResponse';
import type { AdminDepartmentUpdateRequest } from '../models/AdminDepartmentUpdateRequest';
import type { AdminGroupCreateRequest } from '../models/AdminGroupCreateRequest';
import type { AdminGroupListResponse } from '../models/AdminGroupListResponse';
import type { AdminGroupResponse } from '../models/AdminGroupResponse';
import type { AdminGroupUpdateRequest } from '../models/AdminGroupUpdateRequest';
import type { AdminOrganizationMemberListResponse } from '../models/AdminOrganizationMemberListResponse';
import type { AdminOrganizationMemberRemovalResponse } from '../models/AdminOrganizationMemberRemovalResponse';
import type { AdminOrganizationMemberRequest } from '../models/AdminOrganizationMemberRequest';
import type { AdminOrganizationMemberResponse } from '../models/AdminOrganizationMemberResponse';
import type { AdminUserCreateRequest } from '../models/AdminUserCreateRequest';
import type { AdminUserListResponse } from '../models/AdminUserListResponse';
import type { AdminUserResponse } from '../models/AdminUserResponse';
import type { AdminUserUpdateRequest } from '../models/AdminUserUpdateRequest';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class AdminOrganizationService {
    /**
     * List Admin Departments
     * @returns AdminDepartmentListResponse Successful Response
     * @throws ApiError
     */
    public static listAdminDepartmentsApiV1AdminDepartmentsGet({
        status,
        parentId,
        rootOnly = false,
        q,
        cursor,
        pageSize = 50,
    }: {
        status?: ('active' | 'disabled' | null),
        parentId?: (string | null),
        rootOnly?: boolean,
        q?: (string | null),
        cursor?: (string | null),
        pageSize?: number,
    }): CancelablePromise<AdminDepartmentListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/admin/departments',
            query: {
                'status': status,
                'parent_id': parentId,
                'root_only': rootOnly,
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
     * Create Admin Department
     * @returns AdminDepartmentResponse Successful Response
     * @throws ApiError
     */
    public static createAdminDepartmentApiV1AdminDepartmentsPost({
        requestBody,
    }: {
        requestBody: AdminDepartmentCreateRequest,
    }): CancelablePromise<AdminDepartmentResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/admin/departments',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Deactivate Admin Department
     * @returns AdminDepartmentResponse Successful Response
     * @throws ApiError
     */
    public static deactivateAdminDepartmentApiV1AdminDepartmentsDepartmentIdDelete({
        departmentId,
        expectedVersion,
    }: {
        departmentId: string,
        expectedVersion: number,
    }): CancelablePromise<AdminDepartmentResponse> {
        return __request(OpenAPI, {
            method: 'DELETE',
            url: '/api/v1/admin/departments/{department_id}',
            path: {
                'department_id': departmentId,
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
     * Get Admin Department
     * @returns AdminDepartmentResponse Successful Response
     * @throws ApiError
     */
    public static getAdminDepartmentApiV1AdminDepartmentsDepartmentIdGet({
        departmentId,
    }: {
        departmentId: string,
    }): CancelablePromise<AdminDepartmentResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/admin/departments/{department_id}',
            path: {
                'department_id': departmentId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Update Admin Department
     * @returns AdminDepartmentResponse Successful Response
     * @throws ApiError
     */
    public static updateAdminDepartmentApiV1AdminDepartmentsDepartmentIdPatch({
        departmentId,
        requestBody,
    }: {
        departmentId: string,
        requestBody: AdminDepartmentUpdateRequest,
    }): CancelablePromise<AdminDepartmentResponse> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/admin/departments/{department_id}',
            path: {
                'department_id': departmentId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * List Admin Department Members
     * @returns AdminOrganizationMemberListResponse Successful Response
     * @throws ApiError
     */
    public static listAdminDepartmentMembersApiV1AdminDepartmentsDepartmentIdMembersGet({
        departmentId,
        isActive,
        q,
        cursor,
        pageSize = 50,
    }: {
        departmentId: string,
        isActive?: (boolean | null),
        q?: (string | null),
        cursor?: (string | null),
        pageSize?: number,
    }): CancelablePromise<AdminOrganizationMemberListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/admin/departments/{department_id}/members',
            path: {
                'department_id': departmentId,
            },
            query: {
                'is_active': isActive,
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
     * Add Admin Department Member
     * @returns AdminOrganizationMemberResponse Successful Response
     * @throws ApiError
     */
    public static addAdminDepartmentMemberApiV1AdminDepartmentsDepartmentIdMembersPost({
        departmentId,
        requestBody,
    }: {
        departmentId: string,
        requestBody: AdminOrganizationMemberRequest,
    }): CancelablePromise<AdminOrganizationMemberResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/admin/departments/{department_id}/members',
            path: {
                'department_id': departmentId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Remove Admin Department Member
     * @returns AdminOrganizationMemberRemovalResponse Successful Response
     * @throws ApiError
     */
    public static removeAdminDepartmentMemberApiV1AdminDepartmentsDepartmentIdMembersUserIdDelete({
        departmentId,
        userId,
        expectedVersion,
    }: {
        departmentId: string,
        userId: string,
        expectedVersion: number,
    }): CancelablePromise<AdminOrganizationMemberRemovalResponse> {
        return __request(OpenAPI, {
            method: 'DELETE',
            url: '/api/v1/admin/departments/{department_id}/members/{user_id}',
            path: {
                'department_id': departmentId,
                'user_id': userId,
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
     * List Admin Groups
     * @returns AdminGroupListResponse Successful Response
     * @throws ApiError
     */
    public static listAdminGroupsApiV1AdminGroupsGet({
        status,
        q,
        cursor,
        pageSize = 50,
    }: {
        status?: ('active' | 'disabled' | null),
        q?: (string | null),
        cursor?: (string | null),
        pageSize?: number,
    }): CancelablePromise<AdminGroupListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/admin/groups',
            query: {
                'status': status,
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
     * Create Admin Group
     * @returns AdminGroupResponse Successful Response
     * @throws ApiError
     */
    public static createAdminGroupApiV1AdminGroupsPost({
        requestBody,
    }: {
        requestBody: AdminGroupCreateRequest,
    }): CancelablePromise<AdminGroupResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/admin/groups',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Deactivate Admin Group
     * @returns AdminGroupResponse Successful Response
     * @throws ApiError
     */
    public static deactivateAdminGroupApiV1AdminGroupsGroupIdDelete({
        groupId,
        expectedVersion,
    }: {
        groupId: string,
        expectedVersion: number,
    }): CancelablePromise<AdminGroupResponse> {
        return __request(OpenAPI, {
            method: 'DELETE',
            url: '/api/v1/admin/groups/{group_id}',
            path: {
                'group_id': groupId,
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
     * Get Admin Group
     * @returns AdminGroupResponse Successful Response
     * @throws ApiError
     */
    public static getAdminGroupApiV1AdminGroupsGroupIdGet({
        groupId,
    }: {
        groupId: string,
    }): CancelablePromise<AdminGroupResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/admin/groups/{group_id}',
            path: {
                'group_id': groupId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Update Admin Group
     * @returns AdminGroupResponse Successful Response
     * @throws ApiError
     */
    public static updateAdminGroupApiV1AdminGroupsGroupIdPatch({
        groupId,
        requestBody,
    }: {
        groupId: string,
        requestBody: AdminGroupUpdateRequest,
    }): CancelablePromise<AdminGroupResponse> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/admin/groups/{group_id}',
            path: {
                'group_id': groupId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * List Admin Group Members
     * @returns AdminOrganizationMemberListResponse Successful Response
     * @throws ApiError
     */
    public static listAdminGroupMembersApiV1AdminGroupsGroupIdMembersGet({
        groupId,
        isActive,
        q,
        cursor,
        pageSize = 50,
    }: {
        groupId: string,
        isActive?: (boolean | null),
        q?: (string | null),
        cursor?: (string | null),
        pageSize?: number,
    }): CancelablePromise<AdminOrganizationMemberListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/admin/groups/{group_id}/members',
            path: {
                'group_id': groupId,
            },
            query: {
                'is_active': isActive,
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
     * Add Admin Group Member
     * @returns AdminOrganizationMemberResponse Successful Response
     * @throws ApiError
     */
    public static addAdminGroupMemberApiV1AdminGroupsGroupIdMembersPost({
        groupId,
        requestBody,
    }: {
        groupId: string,
        requestBody: AdminOrganizationMemberRequest,
    }): CancelablePromise<AdminOrganizationMemberResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/admin/groups/{group_id}/members',
            path: {
                'group_id': groupId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Remove Admin Group Member
     * @returns AdminOrganizationMemberRemovalResponse Successful Response
     * @throws ApiError
     */
    public static removeAdminGroupMemberApiV1AdminGroupsGroupIdMembersUserIdDelete({
        groupId,
        userId,
        expectedVersion,
    }: {
        groupId: string,
        userId: string,
        expectedVersion: number,
    }): CancelablePromise<AdminOrganizationMemberRemovalResponse> {
        return __request(OpenAPI, {
            method: 'DELETE',
            url: '/api/v1/admin/groups/{group_id}/members/{user_id}',
            path: {
                'group_id': groupId,
                'user_id': userId,
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
     * List Admin Users
     * @returns AdminUserListResponse Successful Response
     * @throws ApiError
     */
    public static listAdminUsersApiV1AdminUsersGet({
        isActive,
        isSuperAdmin,
        q,
        cursor,
        pageSize = 50,
    }: {
        isActive?: (boolean | null),
        isSuperAdmin?: (boolean | null),
        q?: (string | null),
        cursor?: (string | null),
        pageSize?: number,
    }): CancelablePromise<AdminUserListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/admin/users',
            query: {
                'is_active': isActive,
                'is_super_admin': isSuperAdmin,
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
     * Create Admin User
     * @returns AdminUserResponse Successful Response
     * @throws ApiError
     */
    public static createAdminUserApiV1AdminUsersPost({
        requestBody,
    }: {
        requestBody: AdminUserCreateRequest,
    }): CancelablePromise<AdminUserResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/admin/users',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Deactivate Admin User
     * @returns AdminUserResponse Successful Response
     * @throws ApiError
     */
    public static deactivateAdminUserApiV1AdminUsersUserIdDelete({
        userId,
        expectedVersion,
    }: {
        userId: string,
        expectedVersion: number,
    }): CancelablePromise<AdminUserResponse> {
        return __request(OpenAPI, {
            method: 'DELETE',
            url: '/api/v1/admin/users/{user_id}',
            path: {
                'user_id': userId,
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
     * Get Admin User
     * @returns AdminUserResponse Successful Response
     * @throws ApiError
     */
    public static getAdminUserApiV1AdminUsersUserIdGet({
        userId,
    }: {
        userId: string,
    }): CancelablePromise<AdminUserResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/admin/users/{user_id}',
            path: {
                'user_id': userId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Update Admin User
     * @returns AdminUserResponse Successful Response
     * @throws ApiError
     */
    public static updateAdminUserApiV1AdminUsersUserIdPatch({
        userId,
        requestBody,
    }: {
        userId: string,
        requestBody: AdminUserUpdateRequest,
    }): CancelablePromise<AdminUserResponse> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/admin/users/{user_id}',
            path: {
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
