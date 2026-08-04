/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AdminExportCreateRequest } from '../models/AdminExportCreateRequest';
import type { AdminExportDownloadResponse } from '../models/AdminExportDownloadResponse';
import type { AdminJobListResponse } from '../models/AdminJobListResponse';
import type { AdminJobResponse } from '../models/AdminJobResponse';
import type { AdminMaintenanceOverviewResponse } from '../models/AdminMaintenanceOverviewResponse';
import type { AdminMaintenanceRunRequest } from '../models/AdminMaintenanceRunRequest';
import type { AdminOverviewStatsResponse } from '../models/AdminOverviewStatsResponse';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class AdminGovernanceService {
    /**
     * List Admin Exports
     * @returns AdminJobListResponse Successful Response
     * @throws ApiError
     */
    public static listAdminExportsApiV1AdminExportsGet({
        status,
        resource,
        cursor,
        pageSize = 50,
    }: {
        status?: ('pending' | 'running' | 'succeeded' | 'failed' | 'expired' | null),
        resource?: ('audit_logs' | 'spaces' | 'users' | null),
        cursor?: (string | null),
        pageSize?: number,
    }): CancelablePromise<AdminJobListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/admin/exports',
            query: {
                'status': status,
                'resource': resource,
                'cursor': cursor,
                'page_size': pageSize,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Create Admin Export
     * @returns AdminJobResponse Successful Response
     * @throws ApiError
     */
    public static createAdminExportApiV1AdminExportsPost({
        requestBody,
    }: {
        requestBody: AdminExportCreateRequest,
    }): CancelablePromise<AdminJobResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/admin/exports',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get Admin Export
     * @returns AdminJobResponse Successful Response
     * @throws ApiError
     */
    public static getAdminExportApiV1AdminExportsExportIdGet({
        exportId,
    }: {
        exportId: string,
    }): CancelablePromise<AdminJobResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/admin/exports/{export_id}',
            path: {
                'export_id': exportId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get Admin Export Download
     * @returns AdminExportDownloadResponse Successful Response
     * @throws ApiError
     */
    public static getAdminExportDownloadApiV1AdminExportsExportIdDownloadGet({
        exportId,
    }: {
        exportId: string,
    }): CancelablePromise<AdminExportDownloadResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/admin/exports/{export_id}/download',
            path: {
                'export_id': exportId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * List Admin Maintenance Runs
     * @returns AdminJobListResponse Successful Response
     * @throws ApiError
     */
    public static listAdminMaintenanceRunsApiV1AdminMaintenanceRunsGet({
        status,
        taskName,
        cursor,
        pageSize = 50,
    }: {
        status?: ('pending' | 'running' | 'succeeded' | 'failed' | 'expired' | null),
        taskName?: ('upload.expire_sessions' | 'file.cleanup_expired_trash' | 'share.expire_shares' | 'preview.cleanup_artifacts' | 'file.process_tree_operations' | 'file.cleanup_unreferenced_blobs' | 'file.cleanup_orphaned_objects' | 'quota.reconcile_space_usage' | 'admin.cleanup_expired_exports' | null),
        cursor?: (string | null),
        pageSize?: number,
    }): CancelablePromise<AdminJobListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/admin/maintenance/runs',
            query: {
                'status': status,
                'task_name': taskName,
                'cursor': cursor,
                'page_size': pageSize,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Create Admin Maintenance Run
     * @returns AdminJobResponse Successful Response
     * @throws ApiError
     */
    public static createAdminMaintenanceRunApiV1AdminMaintenanceRunsPost({
        requestBody,
    }: {
        requestBody: AdminMaintenanceRunRequest,
    }): CancelablePromise<AdminJobResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/admin/maintenance/runs',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get Admin Maintenance Run
     * @returns AdminJobResponse Successful Response
     * @throws ApiError
     */
    public static getAdminMaintenanceRunApiV1AdminMaintenanceRunsRunIdGet({
        runId,
    }: {
        runId: string,
    }): CancelablePromise<AdminJobResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/admin/maintenance/runs/{run_id}',
            path: {
                'run_id': runId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get Admin Maintenance Tasks
     * @returns AdminMaintenanceOverviewResponse Successful Response
     * @throws ApiError
     */
    public static getAdminMaintenanceTasksApiV1AdminMaintenanceTasksGet(): CancelablePromise<AdminMaintenanceOverviewResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/admin/maintenance/tasks',
        });
    }
    /**
     * Get Admin Overview Stats
     * @returns AdminOverviewStatsResponse Successful Response
     * @throws ApiError
     */
    public static getAdminOverviewStatsApiV1AdminStatsOverviewGet(): CancelablePromise<AdminOverviewStatsResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/admin/stats/overview',
        });
    }
}
