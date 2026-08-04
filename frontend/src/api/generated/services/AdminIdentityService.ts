/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { LdapConnectionTestResponse } from '../models/LdapConnectionTestResponse';
import type { LdapSourceCreateRequest } from '../models/LdapSourceCreateRequest';
import type { LdapSourceListResponse } from '../models/LdapSourceListResponse';
import type { LdapSourceResponse } from '../models/LdapSourceResponse';
import type { LdapSourceUpdateRequest } from '../models/LdapSourceUpdateRequest';
import type { LdapSyncConflictListResponse } from '../models/LdapSyncConflictListResponse';
import type { LdapSyncRequest } from '../models/LdapSyncRequest';
import type { LdapSyncRunListResponse } from '../models/LdapSyncRunListResponse';
import type { LdapSyncRunResponse } from '../models/LdapSyncRunResponse';
import type { OidcProviderCreateRequest } from '../models/OidcProviderCreateRequest';
import type { OidcProviderListResponse } from '../models/OidcProviderListResponse';
import type { OidcProviderResponse } from '../models/OidcProviderResponse';
import type { OidcProviderTestResponse } from '../models/OidcProviderTestResponse';
import type { OidcProviderUpdateRequest } from '../models/OidcProviderUpdateRequest';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class AdminIdentityService {
    /**
     * List Ldap Sync Runs
     * @returns LdapSyncRunListResponse Successful Response
     * @throws ApiError
     */
    public static listLdapSyncRunsApiV1AdminIdentityLdapRunsGet({
        sourceId,
        limit = 50,
    }: {
        sourceId?: (string | null),
        limit?: number,
    }): CancelablePromise<LdapSyncRunListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/admin/identity/ldap/runs',
            query: {
                'source_id': sourceId,
                'limit': limit,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * List Ldap Sync Conflicts
     * @returns LdapSyncConflictListResponse Successful Response
     * @throws ApiError
     */
    public static listLdapSyncConflictsApiV1AdminIdentityLdapRunsRunIdConflictsGet({
        runId,
    }: {
        runId: string,
    }): CancelablePromise<LdapSyncConflictListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/admin/identity/ldap/runs/{run_id}/conflicts',
            path: {
                'run_id': runId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * List Ldap Sources
     * @returns LdapSourceListResponse Successful Response
     * @throws ApiError
     */
    public static listLdapSourcesApiV1AdminIdentityLdapSourcesGet(): CancelablePromise<LdapSourceListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/admin/identity/ldap/sources',
        });
    }
    /**
     * Create Ldap Source
     * @returns LdapSourceResponse Successful Response
     * @throws ApiError
     */
    public static createLdapSourceApiV1AdminIdentityLdapSourcesPost({
        requestBody,
    }: {
        requestBody: LdapSourceCreateRequest,
    }): CancelablePromise<LdapSourceResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/admin/identity/ldap/sources',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Update Ldap Source
     * @returns LdapSourceResponse Successful Response
     * @throws ApiError
     */
    public static updateLdapSourceApiV1AdminIdentityLdapSourcesSourceIdPatch({
        sourceId,
        requestBody,
    }: {
        sourceId: string,
        requestBody: LdapSourceUpdateRequest,
    }): CancelablePromise<LdapSourceResponse> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/admin/identity/ldap/sources/{source_id}',
            path: {
                'source_id': sourceId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Start Ldap Sync
     * @returns LdapSyncRunResponse Successful Response
     * @throws ApiError
     */
    public static startLdapSyncApiV1AdminIdentityLdapSourcesSourceIdSyncPost({
        sourceId,
        requestBody,
    }: {
        sourceId: string,
        requestBody: LdapSyncRequest,
    }): CancelablePromise<LdapSyncRunResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/admin/identity/ldap/sources/{source_id}/sync',
            path: {
                'source_id': sourceId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Test Ldap Source
     * @returns LdapConnectionTestResponse Successful Response
     * @throws ApiError
     */
    public static testLdapSourceApiV1AdminIdentityLdapSourcesSourceIdTestPost({
        sourceId,
    }: {
        sourceId: string,
    }): CancelablePromise<LdapConnectionTestResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/admin/identity/ldap/sources/{source_id}/test',
            path: {
                'source_id': sourceId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * List Oidc Providers
     * @returns OidcProviderListResponse Successful Response
     * @throws ApiError
     */
    public static listOidcProvidersApiV1AdminIdentityOidcProvidersGet(): CancelablePromise<OidcProviderListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/admin/identity/oidc/providers',
        });
    }
    /**
     * Create Oidc Provider
     * @returns OidcProviderResponse Successful Response
     * @throws ApiError
     */
    public static createOidcProviderApiV1AdminIdentityOidcProvidersPost({
        requestBody,
    }: {
        requestBody: OidcProviderCreateRequest,
    }): CancelablePromise<OidcProviderResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/admin/identity/oidc/providers',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Update Oidc Provider
     * @returns OidcProviderResponse Successful Response
     * @throws ApiError
     */
    public static updateOidcProviderApiV1AdminIdentityOidcProvidersProviderIdPatch({
        providerId,
        requestBody,
    }: {
        providerId: string,
        requestBody: OidcProviderUpdateRequest,
    }): CancelablePromise<OidcProviderResponse> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/admin/identity/oidc/providers/{provider_id}',
            path: {
                'provider_id': providerId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Test Oidc Provider
     * @returns OidcProviderTestResponse Successful Response
     * @throws ApiError
     */
    public static testOidcProviderApiV1AdminIdentityOidcProvidersProviderIdTestPost({
        providerId,
    }: {
        providerId: string,
    }): CancelablePromise<OidcProviderTestResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/admin/identity/oidc/providers/{provider_id}/test',
            path: {
                'provider_id': providerId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
