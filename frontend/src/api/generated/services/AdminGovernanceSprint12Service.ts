/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AdminTreeOperationListResponse } from '../models/AdminTreeOperationListResponse';
import type { GovernanceOverviewResponse } from '../models/GovernanceOverviewResponse';
import type { LifecyclePolicyResponse } from '../models/LifecyclePolicyResponse';
import type { LifecyclePolicyUpdateRequest } from '../models/LifecyclePolicyUpdateRequest';
import type { LifecycleRunCreateRequest } from '../models/LifecycleRunCreateRequest';
import type { LifecycleRunListResponse } from '../models/LifecycleRunListResponse';
import type { LifecycleRunResponse } from '../models/LifecycleRunResponse';
import type { PermissionRebuildCreateRequest } from '../models/PermissionRebuildCreateRequest';
import type { PermissionRebuildOperationListResponse } from '../models/PermissionRebuildOperationListResponse';
import type { PermissionRebuildOperationResponse } from '../models/PermissionRebuildOperationResponse';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class AdminGovernanceSprint12Service {
    /**
     * Get Lifecycle Policy
     * @returns LifecyclePolicyResponse Successful Response
     * @throws ApiError
     */
    public static getLifecyclePolicyApiV1AdminGovernanceLifecyclePolicyGet(): CancelablePromise<LifecyclePolicyResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/admin/governance/lifecycle-policy',
        });
    }
    /**
     * Update Lifecycle Policy
     * @returns LifecyclePolicyResponse Successful Response
     * @throws ApiError
     */
    public static updateLifecyclePolicyApiV1AdminGovernanceLifecyclePolicyPatch({
        requestBody,
    }: {
        requestBody: LifecyclePolicyUpdateRequest,
    }): CancelablePromise<LifecyclePolicyResponse> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/admin/governance/lifecycle-policy',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * List Lifecycle Runs
     * @returns LifecycleRunListResponse Successful Response
     * @throws ApiError
     */
    public static listLifecycleRunsApiV1AdminGovernanceLifecycleRunsGet({
        cursor,
        pageSize = 50,
    }: {
        cursor?: (string | null),
        pageSize?: number,
    }): CancelablePromise<LifecycleRunListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/admin/governance/lifecycle-runs',
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
     * Create Lifecycle Run
     * @returns LifecycleRunResponse Successful Response
     * @throws ApiError
     */
    public static createLifecycleRunApiV1AdminGovernanceLifecycleRunsPost({
        requestBody,
    }: {
        requestBody: LifecycleRunCreateRequest,
    }): CancelablePromise<LifecycleRunResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/admin/governance/lifecycle-runs',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get Governance Overview
     * @returns GovernanceOverviewResponse Successful Response
     * @throws ApiError
     */
    public static getGovernanceOverviewApiV1AdminGovernanceOverviewGet(): CancelablePromise<GovernanceOverviewResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/admin/governance/overview',
        });
    }
    /**
     * List Permission Rebuilds
     * @returns PermissionRebuildOperationListResponse Successful Response
     * @throws ApiError
     */
    public static listPermissionRebuildsApiV1AdminGovernancePermissionRebuildsGet({
        status,
        scope,
        cursor,
        pageSize = 50,
    }: {
        status?: ('pending' | 'running' | 'completed' | 'failed' | null),
        scope?: ('space' | 'node' | null),
        cursor?: (string | null),
        pageSize?: number,
    }): CancelablePromise<PermissionRebuildOperationListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/admin/governance/permission-rebuilds',
            query: {
                'status': status,
                'scope': scope,
                'cursor': cursor,
                'page_size': pageSize,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Create Permission Rebuild
     * @returns PermissionRebuildOperationResponse Successful Response
     * @throws ApiError
     */
    public static createPermissionRebuildApiV1AdminGovernancePermissionRebuildsPost({
        requestBody,
    }: {
        requestBody: PermissionRebuildCreateRequest,
    }): CancelablePromise<PermissionRebuildOperationResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/admin/governance/permission-rebuilds',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get Permission Rebuild
     * @returns PermissionRebuildOperationResponse Successful Response
     * @throws ApiError
     */
    public static getPermissionRebuildApiV1AdminGovernancePermissionRebuildsOperationIdGet({
        operationId,
    }: {
        operationId: string,
    }): CancelablePromise<PermissionRebuildOperationResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/admin/governance/permission-rebuilds/{operation_id}',
            path: {
                'operation_id': operationId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Retry Permission Rebuild
     * @returns PermissionRebuildOperationResponse Successful Response
     * @throws ApiError
     */
    public static retryPermissionRebuildApiV1AdminGovernancePermissionRebuildsOperationIdRetryPost({
        operationId,
    }: {
        operationId: string,
    }): CancelablePromise<PermissionRebuildOperationResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/admin/governance/permission-rebuilds/{operation_id}/retry',
            path: {
                'operation_id': operationId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * List Governance Tree Operations
     * @returns AdminTreeOperationListResponse Successful Response
     * @throws ApiError
     */
    public static listGovernanceTreeOperationsApiV1AdminGovernanceTreeOperationsGet({
        status,
        cursor,
        pageSize = 50,
    }: {
        status?: ('pending' | 'running' | 'completed' | 'failed' | null),
        cursor?: (string | null),
        pageSize?: number,
    }): CancelablePromise<AdminTreeOperationListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/admin/governance/tree-operations',
            query: {
                'status': status,
                'cursor': cursor,
                'page_size': pageSize,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
