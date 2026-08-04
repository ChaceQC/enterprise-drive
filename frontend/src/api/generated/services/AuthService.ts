/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { BrowserSessionListResponse } from '../models/BrowserSessionListResponse';
import type { BrowserSessionRevokeResponse } from '../models/BrowserSessionRevokeResponse';
import type { LoginRequest } from '../models/LoginRequest';
import type { LogoutResponse } from '../models/LogoutResponse';
import type { PasswordChangeRequest } from '../models/PasswordChangeRequest';
import type { PasswordChangeResponse } from '../models/PasswordChangeResponse';
import type { PasswordPolicyResponse } from '../models/PasswordPolicyResponse';
import type { SessionResponse } from '../models/SessionResponse';
import type { UserProfileResponse } from '../models/UserProfileResponse';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class AuthService {
    /**
     * Login
     * @returns SessionResponse Successful Response
     * @throws ApiError
     */
    public static loginApiV1AuthLoginPost({
        requestBody,
    }: {
        requestBody: LoginRequest,
    }): CancelablePromise<SessionResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/auth/login',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Logout
     * @returns LogoutResponse Successful Response
     * @throws ApiError
     */
    public static logoutApiV1AuthLogoutPost(): CancelablePromise<LogoutResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/auth/logout',
        });
    }
    /**
     * Me
     * @returns UserProfileResponse Successful Response
     * @throws ApiError
     */
    public static meApiV1AuthMeGet(): CancelablePromise<UserProfileResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/auth/me',
        });
    }
    /**
     * Change Password
     * @returns PasswordChangeResponse Successful Response
     * @throws ApiError
     */
    public static changePasswordApiV1AuthPasswordChangePost({
        requestBody,
    }: {
        requestBody: PasswordChangeRequest,
    }): CancelablePromise<PasswordChangeResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/auth/password/change',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get Password Policy
     * @returns PasswordPolicyResponse Successful Response
     * @throws ApiError
     */
    public static getPasswordPolicyApiV1AuthPasswordPolicyGet(): CancelablePromise<PasswordPolicyResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/auth/password/policy',
        });
    }
    /**
     * Rotate Session
     * @returns SessionResponse Successful Response
     * @throws ApiError
     */
    public static rotateSessionApiV1AuthSessionRotatePost(): CancelablePromise<SessionResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/auth/session/rotate',
        });
    }
    /**
     * List Browser Sessions
     * @returns BrowserSessionListResponse Successful Response
     * @throws ApiError
     */
    public static listBrowserSessionsApiV1AuthSessionsGet(): CancelablePromise<BrowserSessionListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/auth/sessions',
        });
    }
    /**
     * Revoke Browser Session
     * @returns BrowserSessionRevokeResponse Successful Response
     * @throws ApiError
     */
    public static revokeBrowserSessionApiV1AuthSessionsSessionIdDelete({
        sessionId,
    }: {
        sessionId: string,
    }): CancelablePromise<BrowserSessionRevokeResponse> {
        return __request(OpenAPI, {
            method: 'DELETE',
            url: '/api/v1/auth/sessions/{session_id}',
            path: {
                'session_id': sessionId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
