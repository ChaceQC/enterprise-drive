/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { UploadPartUrlResponse } from './UploadPartUrlResponse';
export type BatchPresignUploadPartsResponse = {
    client_operation_id?: (string | null);
    items: Array<UploadPartUrlResponse>;
    max_parallelism: number;
    protocol_version?: string;
    session_id: string;
};
