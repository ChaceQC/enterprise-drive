/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ExternalShareAccessRequest } from '../models/ExternalShareAccessRequest';
import type { ExternalShareAccessResponse } from '../models/ExternalShareAccessResponse';
import type { ExternalShareDownloadRequest } from '../models/ExternalShareDownloadRequest';
import type { ExternalShareDownloadResponse } from '../models/ExternalShareDownloadResponse';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class PublicSharesService {
    /**
     * Access External Share
     * @returns ExternalShareAccessResponse Successful Response
     * @throws ApiError
     */
    public static accessExternalShareApiV1PublicSharesAccessPost({
        requestBody,
    }: {
        requestBody: ExternalShareAccessRequest,
    }): CancelablePromise<ExternalShareAccessResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/public/shares/access',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Create External Download Url
     * @returns ExternalShareDownloadResponse Successful Response
     * @throws ApiError
     */
    public static createExternalDownloadUrlApiV1PublicSharesDownloadPost({
        requestBody,
        xDriveTransferProtocol,
    }: {
        requestBody: ExternalShareDownloadRequest,
        xDriveTransferProtocol?: (string | null),
    }): CancelablePromise<ExternalShareDownloadResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/public/shares/download',
            headers: {
                'X-Drive-Transfer-Protocol': xDriveTransferProtocol,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
