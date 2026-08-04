/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type InternalShareDownloadResponse = {
    client_operation_id?: (string | null);
    download_count: number;
    download_url: string;
    expires_at: string;
    file_name: string;
    headers: Record<string, string>;
    mime_type: (string | null);
    node_id: string;
    protocol_version?: string;
    share_id: string;
    size_bytes: number;
    version_id: string;
};
