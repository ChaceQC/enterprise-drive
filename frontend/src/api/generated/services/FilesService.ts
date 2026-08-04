/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { BatchDeleteRequest } from '../models/BatchDeleteRequest';
import type { BatchMoveRequest } from '../models/BatchMoveRequest';
import type { BatchOperationResponse } from '../models/BatchOperationResponse';
import type { BatchPurgeRequest } from '../models/BatchPurgeRequest';
import type { BatchRestoreRequest } from '../models/BatchRestoreRequest';
import type { CreateFolderRequest } from '../models/CreateFolderRequest';
import type { DeleteNodeResponse } from '../models/DeleteNodeResponse';
import type { FileDownloadUrlResponse } from '../models/FileDownloadUrlResponse';
import type { FileListResponse } from '../models/FileListResponse';
import type { FileNodeResponse } from '../models/FileNodeResponse';
import type { FilePreviewResponse } from '../models/FilePreviewResponse';
import type { FileTreeOperationResponse } from '../models/FileTreeOperationResponse';
import type { FileVersionListResponse } from '../models/FileVersionListResponse';
import type { FileVersionRollbackRequest } from '../models/FileVersionRollbackRequest';
import type { FileVersionRollbackResponse } from '../models/FileVersionRollbackResponse';
import type { MoveNodeRequest } from '../models/MoveNodeRequest';
import type { PurgeNodeResponse } from '../models/PurgeNodeResponse';
import type { RenameNodeRequest } from '../models/RenameNodeRequest';
import type { RestoreNodeRequest } from '../models/RestoreNodeRequest';
import type { TrashListResponse } from '../models/TrashListResponse';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class FilesService {
    /**
     * List Files
     * @returns FileListResponse Successful Response
     * @throws ApiError
     */
    public static listFilesApiV1FilesGet({
        spaceId,
        parentId,
        cursor,
        pageSize = 50,
    }: {
        spaceId: string,
        parentId?: (string | null),
        cursor?: (string | null),
        pageSize?: number,
    }): CancelablePromise<FileListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/files',
            query: {
                'space_id': spaceId,
                'parent_id': parentId,
                'cursor': cursor,
                'page_size': pageSize,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Batch Delete
     * @returns BatchOperationResponse Successful Response
     * @throws ApiError
     */
    public static batchDeleteApiV1FilesBatchDeletePost({
        idempotencyKey,
        requestBody,
    }: {
        idempotencyKey: string,
        requestBody: BatchDeleteRequest,
    }): CancelablePromise<BatchOperationResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/files/batch-delete',
            headers: {
                'Idempotency-Key': idempotencyKey,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Batch Move
     * @returns BatchOperationResponse Successful Response
     * @throws ApiError
     */
    public static batchMoveApiV1FilesBatchMovePost({
        idempotencyKey,
        requestBody,
    }: {
        idempotencyKey: string,
        requestBody: BatchMoveRequest,
    }): CancelablePromise<BatchOperationResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/files/batch-move',
            headers: {
                'Idempotency-Key': idempotencyKey,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Batch Purge
     * @returns BatchOperationResponse Successful Response
     * @throws ApiError
     */
    public static batchPurgeApiV1FilesBatchPurgePost({
        idempotencyKey,
        requestBody,
    }: {
        idempotencyKey: string,
        requestBody: BatchPurgeRequest,
    }): CancelablePromise<BatchOperationResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/files/batch-purge',
            headers: {
                'Idempotency-Key': idempotencyKey,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Batch Restore
     * @returns BatchOperationResponse Successful Response
     * @throws ApiError
     */
    public static batchRestoreApiV1FilesBatchRestorePost({
        idempotencyKey,
        requestBody,
    }: {
        idempotencyKey: string,
        requestBody: BatchRestoreRequest,
    }): CancelablePromise<BatchOperationResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/files/batch-restore',
            headers: {
                'Idempotency-Key': idempotencyKey,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Create Folder
     * @returns FileNodeResponse Successful Response
     * @throws ApiError
     */
    public static createFolderApiV1FilesFoldersPost({
        requestBody,
        xClientOperationId,
    }: {
        requestBody: CreateFolderRequest,
        xClientOperationId?: (string | null),
    }): CancelablePromise<FileNodeResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/files/folders',
            headers: {
                'X-Client-Operation-ID': xClientOperationId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get File Tree Operation
     * @returns FileTreeOperationResponse Successful Response
     * @throws ApiError
     */
    public static getFileTreeOperationApiV1FilesOperationsOperationIdGet({
        operationId,
    }: {
        operationId: string,
    }): CancelablePromise<FileTreeOperationResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/files/operations/{operation_id}',
            path: {
                'operation_id': operationId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Retry File Tree Operation
     * @returns FileTreeOperationResponse Successful Response
     * @throws ApiError
     */
    public static retryFileTreeOperationApiV1FilesOperationsOperationIdRetryPost({
        operationId,
    }: {
        operationId: string,
    }): CancelablePromise<FileTreeOperationResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/files/operations/{operation_id}/retry',
            path: {
                'operation_id': operationId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * List Trash
     * @returns TrashListResponse Successful Response
     * @throws ApiError
     */
    public static listTrashApiV1FilesTrashGet({
        spaceId,
        cursor,
        pageSize = 50,
    }: {
        spaceId: string,
        cursor?: (string | null),
        pageSize?: number,
    }): CancelablePromise<TrashListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/files/trash',
            query: {
                'space_id': spaceId,
                'cursor': cursor,
                'page_size': pageSize,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Delete Node
     * @returns any Successful Response
     * @throws ApiError
     */
    public static deleteNodeApiV1FilesNodeIdDelete({
        nodeId,
        xExpectedCurrentVersionId,
        xClientOperationId,
    }: {
        nodeId: string,
        xExpectedCurrentVersionId?: (string | null),
        xClientOperationId?: (string | null),
    }): CancelablePromise<(DeleteNodeResponse | FileTreeOperationResponse)> {
        return __request(OpenAPI, {
            method: 'DELETE',
            url: '/api/v1/files/{node_id}',
            path: {
                'node_id': nodeId,
            },
            headers: {
                'X-Expected-Current-Version-ID': xExpectedCurrentVersionId,
                'X-Client-Operation-ID': xClientOperationId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Rename Node
     * @returns FileNodeResponse Successful Response
     * @throws ApiError
     */
    public static renameNodeApiV1FilesNodeIdPatch({
        nodeId,
        requestBody,
        xClientOperationId,
    }: {
        nodeId: string,
        requestBody: RenameNodeRequest,
        xClientOperationId?: (string | null),
    }): CancelablePromise<FileNodeResponse> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/files/{node_id}',
            path: {
                'node_id': nodeId,
            },
            headers: {
                'X-Client-Operation-ID': xClientOperationId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Proxy Download Content
     * @returns any 完整代理下载
     * @throws ApiError
     */
    public static proxyDownloadContentApiV1FilesNodeIdContentGet({
        nodeId,
        range,
        xDriveTransferProtocol,
    }: {
        nodeId: string,
        range?: (string | null),
        xDriveTransferProtocol?: (string | null),
    }): CancelablePromise<any> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/files/{node_id}/content',
            path: {
                'node_id': nodeId,
            },
            headers: {
                'Range': range,
                'X-Drive-Transfer-Protocol': xDriveTransferProtocol,
            },
            errors: {
                416: `Range 不合法、不可满足或超过单段上限`,
                422: `Validation Error`,
            },
        });
    }
    /**
     * Create Download Url
     * @returns FileDownloadUrlResponse Successful Response
     * @throws ApiError
     */
    public static createDownloadUrlApiV1FilesNodeIdDownloadGet({
        nodeId,
        xDriveTransferProtocol,
    }: {
        nodeId: string,
        xDriveTransferProtocol?: (string | null),
    }): CancelablePromise<FileDownloadUrlResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/files/{node_id}/download',
            path: {
                'node_id': nodeId,
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
     * Move Node
     * @returns FileNodeResponse Successful Response
     * @throws ApiError
     */
    public static moveNodeApiV1FilesNodeIdMovePost({
        nodeId,
        requestBody,
        xClientOperationId,
    }: {
        nodeId: string,
        requestBody: MoveNodeRequest,
        xClientOperationId?: (string | null),
    }): CancelablePromise<FileNodeResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/files/{node_id}/move',
            path: {
                'node_id': nodeId,
            },
            headers: {
                'X-Client-Operation-ID': xClientOperationId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Create Preview Url
     * @returns FilePreviewResponse Successful Response
     * @throws ApiError
     */
    public static createPreviewUrlApiV1FilesNodeIdPreviewGet({
        nodeId,
    }: {
        nodeId: string,
    }): CancelablePromise<FilePreviewResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/files/{node_id}/preview',
            path: {
                'node_id': nodeId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Purge Node
     * @returns any Successful Response
     * @throws ApiError
     */
    public static purgeNodeApiV1FilesNodeIdPurgeDelete({
        nodeId,
    }: {
        nodeId: string,
    }): CancelablePromise<(PurgeNodeResponse | FileTreeOperationResponse)> {
        return __request(OpenAPI, {
            method: 'DELETE',
            url: '/api/v1/files/{node_id}/purge',
            path: {
                'node_id': nodeId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Restore Node
     * @returns any Successful Response
     * @throws ApiError
     */
    public static restoreNodeApiV1FilesNodeIdRestorePost({
        nodeId,
        requestBody,
    }: {
        nodeId: string,
        requestBody: RestoreNodeRequest,
    }): CancelablePromise<(FileNodeResponse | FileTreeOperationResponse)> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/files/{node_id}/restore',
            path: {
                'node_id': nodeId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * List File Versions
     * @returns FileVersionListResponse Successful Response
     * @throws ApiError
     */
    public static listFileVersionsApiV1FilesNodeIdVersionsGet({
        nodeId,
        cursor,
        pageSize = 50,
    }: {
        nodeId: string,
        cursor?: (string | null),
        pageSize?: number,
    }): CancelablePromise<FileVersionListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/files/{node_id}/versions',
            path: {
                'node_id': nodeId,
            },
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
     * Create Version Download Url
     * @returns FileDownloadUrlResponse Successful Response
     * @throws ApiError
     */
    public static createVersionDownloadUrlApiV1FilesNodeIdVersionsVersionIdDownloadGet({
        nodeId,
        versionId,
        xDriveTransferProtocol,
    }: {
        nodeId: string,
        versionId: string,
        xDriveTransferProtocol?: (string | null),
    }): CancelablePromise<FileDownloadUrlResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/files/{node_id}/versions/{version_id}/download',
            path: {
                'node_id': nodeId,
                'version_id': versionId,
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
     * Rollback File Version
     * @returns FileVersionRollbackResponse Successful Response
     * @throws ApiError
     */
    public static rollbackFileVersionApiV1FilesNodeIdVersionsVersionIdRollbackPost({
        nodeId,
        versionId,
        requestBody,
    }: {
        nodeId: string,
        versionId: string,
        requestBody: FileVersionRollbackRequest,
    }): CancelablePromise<FileVersionRollbackResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/files/{node_id}/versions/{version_id}/rollback',
            path: {
                'node_id': nodeId,
                'version_id': versionId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Download Watermarked Content
     * @returns any 带水印的图片或 PDF 完整下载
     * @throws ApiError
     */
    public static downloadWatermarkedContentApiV1FilesNodeIdWatermarkedContentGet({
        nodeId,
        xDriveTransferProtocol,
    }: {
        nodeId: string,
        xDriveTransferProtocol?: (string | null),
    }): CancelablePromise<any> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/files/{node_id}/watermarked-content',
            path: {
                'node_id': nodeId,
            },
            headers: {
                'X-Drive-Transfer-Protocol': xDriveTransferProtocol,
            },
            errors: {
                409: `策略或 DLP 状态不允许水印下载`,
                422: `格式或大小不支持水印处理`,
            },
        });
    }
}
