/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { OidcIdentityLinkListResponse } from '../models/OidcIdentityLinkListResponse';
import type { OidcIdentityUnlinkResponse } from '../models/OidcIdentityUnlinkResponse';
import type { OidcLogoutResponse } from '../models/OidcLogoutResponse';
import type { OidcStartResponse } from '../models/OidcStartResponse';
import type { PublicOidcProviderListResponse } from '../models/PublicOidcProviderListResponse';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class IdentityService {
    /**
     * List Identity Links
     * @returns OidcIdentityLinkListResponse Successful Response
     * @throws ApiError
     */
    public static listIdentityLinksApiV1AuthIdentityLinksGet(): CancelablePromise<OidcIdentityLinkListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/auth/identity-links',
        });
    }
    /**
     * Unlink Identity
     * @returns OidcIdentityUnlinkResponse Successful Response
     * @throws ApiError
     */
    public static unlinkIdentityApiV1AuthIdentityLinksLinkIdDelete({
        linkId,
    }: {
        linkId: string,
    }): CancelablePromise<OidcIdentityUnlinkResponse> {
        return __request(OpenAPI, {
            method: 'DELETE',
            url: '/api/v1/auth/identity-links/{link_id}',
            path: {
                'link_id': linkId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * List Public Oidc Providers
     * @returns PublicOidcProviderListResponse Successful Response
     * @throws ApiError
     */
    public static listPublicOidcProvidersApiV1AuthOidcProvidersGet({
        tenantSlug = 'default',
    }: {
        tenantSlug?: string,
    }): CancelablePromise<PublicOidcProviderListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/auth/oidc/providers',
            query: {
                'tenant_slug': tenantSlug,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Start Oidc Binding
     * @returns OidcStartResponse Successful Response
     * @throws ApiError
     */
    public static startOidcBindingApiV1AuthOidcProviderSlugBindStartPost({
        providerSlug,
        redirectPath = '/account',
    }: {
        providerSlug: string,
        redirectPath?: string,
    }): CancelablePromise<OidcStartResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/auth/oidc/{provider_slug}/bind/start',
            path: {
                'provider_slug': providerSlug,
            },
            query: {
                'redirect_path': redirectPath,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Oidc Callback
     * @returns void
     * @throws ApiError
     */
    public static oidcCallbackApiV1AuthOidcProviderSlugCallbackGet({
        providerSlug,
        state,
        code,
        error,
    }: {
        providerSlug: string,
        state: string,
        code?: (string | null),
        error?: (string | null),
    }): CancelablePromise<void> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/auth/oidc/{provider_slug}/callback',
            path: {
                'provider_slug': providerSlug,
            },
            query: {
                'state': state,
                'code': code,
                'error': error,
            },
            errors: {
                307: `Successful Response`,
                422: `Validation Error`,
            },
        });
    }
    /**
     * Oidc Logout
     * @returns OidcLogoutResponse Successful Response
     * @throws ApiError
     */
    public static oidcLogoutApiV1AuthOidcProviderSlugLogoutPost({
        providerSlug,
    }: {
        providerSlug: string,
    }): CancelablePromise<OidcLogoutResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/auth/oidc/{provider_slug}/logout',
            path: {
                'provider_slug': providerSlug,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Start Oidc Login
     * @returns OidcStartResponse Successful Response
     * @throws ApiError
     */
    public static startOidcLoginApiV1AuthOidcProviderSlugStartGet({
        providerSlug,
        tenantSlug = 'default',
        redirectPath = '/',
    }: {
        providerSlug: string,
        tenantSlug?: string,
        redirectPath?: string,
    }): CancelablePromise<OidcStartResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/auth/oidc/{provider_slug}/start',
            path: {
                'provider_slug': providerSlug,
            },
            query: {
                'tenant_slug': tenantSlug,
                'redirect_path': redirectPath,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
