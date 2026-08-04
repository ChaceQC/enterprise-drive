/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AdminFileSecurityPolicyCreateRequest } from '../models/AdminFileSecurityPolicyCreateRequest';
import type { AdminFileSecurityPolicyListResponse } from '../models/AdminFileSecurityPolicyListResponse';
import type { AdminFileSecurityPolicyResponse } from '../models/AdminFileSecurityPolicyResponse';
import type { AdminFileSecurityPolicyUpdateRequest } from '../models/AdminFileSecurityPolicyUpdateRequest';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class AdminFileSecurityService {
    /**
     * List File Security Policies
     * @returns AdminFileSecurityPolicyListResponse Successful Response
     * @throws ApiError
     */
    public static listFileSecurityPoliciesApiV1AdminFileSecurityPoliciesGet({
        isActive,
        classification,
        name,
        cursor,
        pageSize = 50,
    }: {
        isActive?: (boolean | null),
        classification?: ('internal' | 'confidential' | 'restricted' | null),
        name?: (string | null),
        cursor?: (string | null),
        pageSize?: number,
    }): CancelablePromise<AdminFileSecurityPolicyListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/admin/file-security/policies',
            query: {
                'is_active': isActive,
                'classification': classification,
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
     * Create File Security Policy
     * @returns AdminFileSecurityPolicyResponse Successful Response
     * @throws ApiError
     */
    public static createFileSecurityPolicyApiV1AdminFileSecurityPoliciesPost({
        requestBody,
    }: {
        requestBody: AdminFileSecurityPolicyCreateRequest,
    }): CancelablePromise<AdminFileSecurityPolicyResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/admin/file-security/policies',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Deactivate File Security Policy
     * @returns AdminFileSecurityPolicyResponse Successful Response
     * @throws ApiError
     */
    public static deactivateFileSecurityPolicyApiV1AdminFileSecurityPoliciesPolicyIdDelete({
        policyId,
        expectedVersion,
    }: {
        policyId: string,
        expectedVersion: number,
    }): CancelablePromise<AdminFileSecurityPolicyResponse> {
        return __request(OpenAPI, {
            method: 'DELETE',
            url: '/api/v1/admin/file-security/policies/{policy_id}',
            path: {
                'policy_id': policyId,
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
     * Update File Security Policy
     * @returns AdminFileSecurityPolicyResponse Successful Response
     * @throws ApiError
     */
    public static updateFileSecurityPolicyApiV1AdminFileSecurityPoliciesPolicyIdPatch({
        policyId,
        requestBody,
    }: {
        policyId: string,
        requestBody: AdminFileSecurityPolicyUpdateRequest,
    }): CancelablePromise<AdminFileSecurityPolicyResponse> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/admin/file-security/policies/{policy_id}',
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
