/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AbortUploadResponse } from '../models/AbortUploadResponse';
import type { BatchPresignUploadPartsRequest } from '../models/BatchPresignUploadPartsRequest';
import type { BatchPresignUploadPartsResponse } from '../models/BatchPresignUploadPartsResponse';
import type { CompleteUploadRequest } from '../models/CompleteUploadRequest';
import type { CompleteUploadResponse } from '../models/CompleteUploadResponse';
import type { ConfirmUploadPartRequest } from '../models/ConfirmUploadPartRequest';
import type { ConfirmUploadPartResponse } from '../models/ConfirmUploadPartResponse';
import type { InitUploadRequest } from '../models/InitUploadRequest';
import type { InstantUploadResponse } from '../models/InstantUploadResponse';
import type { MultipartUploadResponse } from '../models/MultipartUploadResponse';
import type { UploadPartUrlResponse } from '../models/UploadPartUrlResponse';
import type { UploadSessionStatusResponse } from '../models/UploadSessionStatusResponse';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class UploadsService {
    /**
     * Init Upload
     * @returns any Successful Response
     * @throws ApiError
     */
    public static initUploadApiV1UploadsInitPost({
        requestBody,
        xClientOperationId,
        xDriveTransferProtocol,
    }: {
        requestBody: InitUploadRequest,
        xClientOperationId?: (string | null),
        xDriveTransferProtocol?: (string | null),
    }): CancelablePromise<(InstantUploadResponse | MultipartUploadResponse)> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/uploads/init',
            headers: {
                'X-Client-Operation-ID': xClientOperationId,
                'X-Drive-Transfer-Protocol': xDriveTransferProtocol,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get Upload Status
     * @returns UploadSessionStatusResponse Successful Response
     * @throws ApiError
     */
    public static getUploadStatusApiV1UploadsSessionIdGet({
        sessionId,
        xDriveTransferProtocol,
    }: {
        sessionId: string,
        xDriveTransferProtocol?: (string | null),
    }): CancelablePromise<UploadSessionStatusResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/uploads/{session_id}',
            path: {
                'session_id': sessionId,
            },
            headers: {
                'X-Drive-Transfer-Protocol': xDriveTransferProtocol,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Abort Upload
     * @returns AbortUploadResponse Successful Response
     * @throws ApiError
     */
    public static abortUploadApiV1UploadsSessionIdAbortPost({
        sessionId,
        xClientOperationId,
        xDriveTransferProtocol,
    }: {
        sessionId: string,
        xClientOperationId?: (string | null),
        xDriveTransferProtocol?: (string | null),
    }): CancelablePromise<AbortUploadResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/uploads/{session_id}/abort',
            path: {
                'session_id': sessionId,
            },
            headers: {
                'X-Client-Operation-ID': xClientOperationId,
                'X-Drive-Transfer-Protocol': xDriveTransferProtocol,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Complete Upload
     * @returns CompleteUploadResponse Successful Response
     * @throws ApiError
     */
    public static completeUploadApiV1UploadsSessionIdCompletePost({
        sessionId,
        requestBody,
        xClientOperationId,
        xDriveTransferProtocol,
    }: {
        sessionId: string,
        requestBody: CompleteUploadRequest,
        xClientOperationId?: (string | null),
        xDriveTransferProtocol?: (string | null),
    }): CancelablePromise<CompleteUploadResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/uploads/{session_id}/complete',
            path: {
                'session_id': sessionId,
            },
            headers: {
                'X-Client-Operation-ID': xClientOperationId,
                'X-Drive-Transfer-Protocol': xDriveTransferProtocol,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Presign Upload Parts
     * @returns BatchPresignUploadPartsResponse Successful Response
     * @throws ApiError
     */
    public static presignUploadPartsApiV1UploadsSessionIdPartsPresignPost({
        sessionId,
        requestBody,
        xDriveTransferProtocol,
    }: {
        sessionId: string,
        requestBody: BatchPresignUploadPartsRequest,
        xDriveTransferProtocol?: (string | null),
    }): CancelablePromise<BatchPresignUploadPartsResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/uploads/{session_id}/parts/presign',
            path: {
                'session_id': sessionId,
            },
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
    /**
     * Confirm Upload Part
     * @returns ConfirmUploadPartResponse Successful Response
     * @throws ApiError
     */
    public static confirmUploadPartApiV1UploadsSessionIdPartsPartNoConfirmPost({
        sessionId,
        partNo,
        requestBody,
        xDriveTransferProtocol,
    }: {
        sessionId: string,
        partNo: number,
        requestBody: ConfirmUploadPartRequest,
        xDriveTransferProtocol?: (string | null),
    }): CancelablePromise<ConfirmUploadPartResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/uploads/{session_id}/parts/{part_no}/confirm',
            path: {
                'session_id': sessionId,
                'part_no': partNo,
            },
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
    /**
     * Presign Upload Part
     * @returns UploadPartUrlResponse Successful Response
     * @throws ApiError
     */
    public static presignUploadPartApiV1UploadsSessionIdPartsPartNoPresignPost({
        sessionId,
        partNo,
        xDriveTransferProtocol,
    }: {
        sessionId: string,
        partNo: number,
        xDriveTransferProtocol?: (string | null),
    }): CancelablePromise<UploadPartUrlResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/uploads/{session_id}/parts/{part_no}/presign',
            path: {
                'session_id': sessionId,
                'part_no': partNo,
            },
            headers: {
                'X-Drive-Transfer-Protocol': xDriveTransferProtocol,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
