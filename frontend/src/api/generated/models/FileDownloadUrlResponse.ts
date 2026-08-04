/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type FileDownloadUrlResponse = {
    client_operation_id?: (string | null);
    content_hash: string;
    download_url: string;
    expires_at: string;
    file_name: string;
    hash_algo: string;
    headers: Record<string, string>;
    mime_type: (string | null);
    node_id: string;
    protocol_version?: string;
    size_bytes: number;
    version_id: string;
};
