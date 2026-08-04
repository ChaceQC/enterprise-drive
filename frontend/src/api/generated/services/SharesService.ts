/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { CreateShareRequest } from '../models/CreateShareRequest';
import type { CreateShareResponse } from '../models/CreateShareResponse';
import type { InternalShareDownloadRequest } from '../models/InternalShareDownloadRequest';
import type { InternalShareDownloadResponse } from '../models/InternalShareDownloadResponse';
import type { InternalShareItemsResponse } from '../models/InternalShareItemsResponse';
import type { RevokeShareResponse } from '../models/RevokeShareResponse';
import type { ShareDetail } from '../models/ShareDetail';
import type { ShareListResponse } from '../models/ShareListResponse';
import type { ShareNotificationListResponse } from '../models/ShareNotificationListResponse';
import type { ShareNotificationReadResponse } from '../models/ShareNotificationReadResponse';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class SharesService {
    /**
     * Create Share
     * @returns CreateShareResponse Successful Response
     * @throws ApiError
     */
    public static createShareApiV1SharesPost({
        requestBody,
    }: {
        requestBody: CreateShareRequest,
    }): CancelablePromise<CreateShareResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/shares',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * List Created Shares
     * @returns ShareListResponse Successful Response
     * @throws ApiError
     */
    public static listCreatedSharesApiV1SharesCreatedGet({
        cursor,
        pageSize = 50,
    }: {
        cursor?: (string | null),
        pageSize?: number,
    }): CancelablePromise<ShareListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/shares/created',
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
     * List Share Notifications
     * @returns ShareNotificationListResponse Successful Response
     * @throws ApiError
     */
    public static listShareNotificationsApiV1SharesNotificationsGet({
        unreadOnly = false,
        cursor,
        pageSize = 50,
    }: {
        unreadOnly?: boolean,
        cursor?: (string | null),
        pageSize?: number,
    }): CancelablePromise<ShareNotificationListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/shares/notifications',
            query: {
                'unread_only': unreadOnly,
                'cursor': cursor,
                'page_size': pageSize,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Mark Share Notification Read
     * @returns ShareNotificationReadResponse Successful Response
     * @throws ApiError
     */
    public static markShareNotificationReadApiV1SharesNotificationsNotificationIdReadPost({
        notificationId,
    }: {
        notificationId: string,
    }): CancelablePromise<ShareNotificationReadResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/shares/notifications/{notification_id}/read',
            path: {
                'notification_id': notificationId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * List Received Shares
     * @returns ShareListResponse Successful Response
     * @throws ApiError
     */
    public static listReceivedSharesApiV1SharesReceivedGet({
        cursor,
        pageSize = 50,
    }: {
        cursor?: (string | null),
        pageSize?: number,
    }): CancelablePromise<ShareListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/shares/received',
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
     * Get Share Detail
     * @returns ShareDetail Successful Response
     * @throws ApiError
     */
    public static getShareDetailApiV1SharesShareIdGet({
        shareId,
    }: {
        shareId: string,
    }): CancelablePromise<ShareDetail> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/shares/{share_id}',
            path: {
                'share_id': shareId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Create Internal Share Download Url
     * @returns InternalShareDownloadResponse Successful Response
     * @throws ApiError
     */
    public static createInternalShareDownloadUrlApiV1SharesShareIdDownloadPost({
        shareId,
        requestBody,
        xDriveTransferProtocol,
    }: {
        shareId: string,
        requestBody: InternalShareDownloadRequest,
        xDriveTransferProtocol?: (string | null),
    }): CancelablePromise<InternalShareDownloadResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/shares/{share_id}/download',
            path: {
                'share_id': shareId,
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
     * List Internal Share Items
     * @returns InternalShareItemsResponse Successful Response
     * @throws ApiError
     */
    public static listInternalShareItemsApiV1SharesShareIdItemsGet({
        shareId,
    }: {
        shareId: string,
    }): CancelablePromise<InternalShareItemsResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/shares/{share_id}/items',
            path: {
                'share_id': shareId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Revoke Share
     * @returns RevokeShareResponse Successful Response
     * @throws ApiError
     */
    public static revokeShareApiV1SharesShareIdRevokePost({
        shareId,
    }: {
        shareId: string,
    }): CancelablePromise<RevokeShareResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/shares/{share_id}/revoke',
            path: {
                'share_id': shareId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
