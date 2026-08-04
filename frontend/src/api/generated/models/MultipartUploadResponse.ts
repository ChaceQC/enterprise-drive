/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type MultipartUploadResponse = {
    checksum_algorithm?: string;
    client_operation_id?: (string | null);
    expires_at: string;
    max_parallelism: number;
    mode?: string;
    part_size_bytes: number;
    protocol_version?: string;
    session_id: string;
    total_parts: number;
};
