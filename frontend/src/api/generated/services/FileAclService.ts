/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AclEntryListResponse } from '../models/AclEntryListResponse';
import type { AclEntryResponse } from '../models/AclEntryResponse';
import type { CreateAclEntryRequest } from '../models/CreateAclEntryRequest';
import type { RemoveAclEntryResponse } from '../models/RemoveAclEntryResponse';
import type { UpdateAclEntryRequest } from '../models/UpdateAclEntryRequest';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class FileAclService {
    /**
     * List Node Acl Entries
     * @returns AclEntryListResponse Successful Response
     * @throws ApiError
     */
    public static listNodeAclEntriesApiV1FilesNodeIdAclGet({
        nodeId,
    }: {
        nodeId: string,
    }): CancelablePromise<AclEntryListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/files/{node_id}/acl',
            path: {
                'node_id': nodeId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Create Node Acl Entry
     * @returns AclEntryResponse Successful Response
     * @throws ApiError
     */
    public static createNodeAclEntryApiV1FilesNodeIdAclPost({
        nodeId,
        requestBody,
    }: {
        nodeId: string,
        requestBody: CreateAclEntryRequest,
    }): CancelablePromise<AclEntryResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/files/{node_id}/acl',
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
     * Remove Node Acl Entry
     * @returns RemoveAclEntryResponse Successful Response
     * @throws ApiError
     */
    public static removeNodeAclEntryApiV1FilesNodeIdAclEntryIdDelete({
        nodeId,
        entryId,
    }: {
        nodeId: string,
        entryId: string,
    }): CancelablePromise<RemoveAclEntryResponse> {
        return __request(OpenAPI, {
            method: 'DELETE',
            url: '/api/v1/files/{node_id}/acl/{entry_id}',
            path: {
                'node_id': nodeId,
                'entry_id': entryId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Update Node Acl Entry
     * @returns AclEntryResponse Successful Response
     * @throws ApiError
     */
    public static updateNodeAclEntryApiV1FilesNodeIdAclEntryIdPatch({
        nodeId,
        entryId,
        requestBody,
    }: {
        nodeId: string,
        entryId: string,
        requestBody: UpdateAclEntryRequest,
    }): CancelablePromise<AclEntryResponse> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/files/{node_id}/acl/{entry_id}',
            path: {
                'node_id': nodeId,
                'entry_id': entryId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
