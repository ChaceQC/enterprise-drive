/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AdminQuotaAccountListResponse } from '../models/AdminQuotaAccountListResponse';
import type { AdminQuotaAccountResponse } from '../models/AdminQuotaAccountResponse';
import type { AdminQuotaAccountUpsertRequest } from '../models/AdminQuotaAccountUpsertRequest';
import type { AdminQuotaPolicyCreateRequest } from '../models/AdminQuotaPolicyCreateRequest';
import type { AdminQuotaPolicyListResponse } from '../models/AdminQuotaPolicyListResponse';
import type { AdminQuotaPolicyResponse } from '../models/AdminQuotaPolicyResponse';
import type { AdminQuotaPolicyUpdateRequest } from '../models/AdminQuotaPolicyUpdateRequest';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class AdminQuotasService {
    /**
     * List Quota Accounts
     * @returns AdminQuotaAccountListResponse Successful Response
     * @throws ApiError
     */
    public static listQuotaAccountsApiV1AdminQuotasAccountsGet({
        ownerType,
        ownerId,
        cursor,
        pageSize = 50,
    }: {
        ownerType?: ('space' | 'tenant' | 'user' | 'policy' | null),
        ownerId?: (string | null),
        cursor?: (string | null),
        pageSize?: number,
    }): CancelablePromise<AdminQuotaAccountListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/admin/quotas/accounts',
            query: {
                'owner_type': ownerType,
                'owner_id': ownerId,
                'cursor': cursor,
                'page_size': pageSize,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Upsert Quota Account
     * @returns AdminQuotaAccountResponse Successful Response
     * @throws ApiError
     */
    public static upsertQuotaAccountApiV1AdminQuotasAccountsOwnerTypeOwnerIdPut({
        ownerType,
        ownerId,
        requestBody,
    }: {
        ownerType: 'space' | 'tenant' | 'user',
        ownerId: string,
        requestBody: AdminQuotaAccountUpsertRequest,
    }): CancelablePromise<AdminQuotaAccountResponse> {
        return __request(OpenAPI, {
            method: 'PUT',
            url: '/api/v1/admin/quotas/accounts/{owner_type}/{owner_id}',
            path: {
                'owner_type': ownerType,
                'owner_id': ownerId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * List Quota Policies
     * @returns AdminQuotaPolicyListResponse Successful Response
     * @throws ApiError
     */
    public static listQuotaPoliciesApiV1AdminQuotasPoliciesGet({
        isActive,
        name,
        cursor,
        pageSize = 50,
    }: {
        isActive?: (boolean | null),
        name?: (string | null),
        cursor?: (string | null),
        pageSize?: number,
    }): CancelablePromise<AdminQuotaPolicyListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/admin/quotas/policies',
            query: {
                'is_active': isActive,
                'name': name,
                'cursor': cursor,
                'page_size': pageSize,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Create Quota Policy
     * @returns AdminQuotaPolicyResponse Successful Response
     * @throws ApiError
     */
    public static createQuotaPolicyApiV1AdminQuotasPoliciesPost({
        requestBody,
    }: {
        requestBody: AdminQuotaPolicyCreateRequest,
    }): CancelablePromise<AdminQuotaPolicyResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/admin/quotas/policies',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Deactivate Quota Policy
     * @returns AdminQuotaPolicyResponse Successful Response
     * @throws ApiError
     */
    public static deactivateQuotaPolicyApiV1AdminQuotasPoliciesPolicyIdDelete({
        policyId,
        expectedLimitBytes,
    }: {
        policyId: string,
        expectedLimitBytes: number,
    }): CancelablePromise<AdminQuotaPolicyResponse> {
        return __request(OpenAPI, {
            method: 'DELETE',
            url: '/api/v1/admin/quotas/policies/{policy_id}',
            path: {
                'policy_id': policyId,
            },
            query: {
                'expected_limit_bytes': expectedLimitBytes,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Update Quota Policy
     * @returns AdminQuotaPolicyResponse Successful Response
     * @throws ApiError
     */
    public static updateQuotaPolicyApiV1AdminQuotasPoliciesPolicyIdPatch({
        policyId,
        requestBody,
    }: {
        policyId: string,
        requestBody: AdminQuotaPolicyUpdateRequest,
    }): CancelablePromise<AdminQuotaPolicyResponse> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/admin/quotas/policies/{policy_id}',
            path: {
                'policy_id': policyId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
