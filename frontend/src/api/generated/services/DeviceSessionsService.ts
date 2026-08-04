/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { DeviceListResponse } from '../models/DeviceListResponse';
import type { DeviceRegisterRequest } from '../models/DeviceRegisterRequest';
import type { DeviceRevokeResponse } from '../models/DeviceRevokeResponse';
import type { DeviceRotateRequest } from '../models/DeviceRotateRequest';
import type { DeviceSessionResponse } from '../models/DeviceSessionResponse';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class DeviceSessionsService {
    /**
     * Revoke All Devices
     * @returns DeviceRevokeResponse Successful Response
     * @throws ApiError
     */
    public static revokeAllDevicesApiV1DeviceSessionsDelete(): CancelablePromise<DeviceRevokeResponse> {
        return __request(OpenAPI, {
            method: 'DELETE',
            url: '/api/v1/device-sessions',
        });
    }
    /**
     * List Devices
     * @returns DeviceListResponse Successful Response
     * @throws ApiError
     */
    public static listDevicesApiV1DeviceSessionsGet(): CancelablePromise<DeviceListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/device-sessions',
        });
    }
    /**
     * Register Device
     * @returns DeviceSessionResponse Successful Response
     * @throws ApiError
     */
    public static registerDeviceApiV1DeviceSessionsRegisterPost({
        requestBody,
    }: {
        requestBody: DeviceRegisterRequest,
    }): CancelablePromise<DeviceSessionResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/device-sessions/register',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Rotate Device Session
     * @returns DeviceSessionResponse Successful Response
     * @throws ApiError
     */
    public static rotateDeviceSessionApiV1DeviceSessionsRotatePost({
        requestBody,
    }: {
        requestBody: DeviceRotateRequest,
    }): CancelablePromise<DeviceSessionResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/device-sessions/rotate',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Revoke Device
     * @returns DeviceRevokeResponse Successful Response
     * @throws ApiError
     */
    public static revokeDeviceApiV1DeviceSessionsDeviceIdDelete({
        deviceId,
    }: {
        deviceId: string,
    }): CancelablePromise<DeviceRevokeResponse> {
        return __request(OpenAPI, {
            method: 'DELETE',
            url: '/api/v1/device-sessions/{device_id}',
            path: {
                'device_id': deviceId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
