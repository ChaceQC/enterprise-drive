/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AdminAuditLogListResponse } from '../models/AdminAuditLogListResponse';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class AdminService {
    /**
     * List Admin Audit Logs
     * @returns AdminAuditLogListResponse Successful Response
     * @throws ApiError
     */
    public static listAdminAuditLogsApiV1AdminAuditLogsGet({
        actorId,
        actorType,
        action,
        resourceType,
        resourceId,
        result,
        riskLevel,
        requestId,
        createdFrom,
        createdTo,
        cursor,
        pageSize = 50,
    }: {
        actorId?: (string | null),
        actorType?: (string | null),
        action?: (string | null),
        resourceType?: (string | null),
        resourceId?: (string | null),
        result?: (string | null),
        riskLevel?: (string | null),
        requestId?: (string | null),
        createdFrom?: (string | null),
        createdTo?: (string | null),
        cursor?: (string | null),
        pageSize?: number,
    }): CancelablePromise<AdminAuditLogListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/admin/audit-logs',
            query: {
                'actor_id': actorId,
                'actor_type': actorType,
                'action': action,
                'resource_type': resourceType,
                'resource_id': resourceId,
                'result': result,
                'risk_level': riskLevel,
                'request_id': requestId,
                'created_from': createdFrom,
                'created_to': createdTo,
                'cursor': cursor,
                'page_size': pageSize,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
