/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type UploadSessionStatusResponse = {
    checksum_algorithm?: string;
    client_operation_id?: (string | null);
    completed_node_id: (string | null);
    completed_version_id: (string | null);
    expected_current_version_id: (string | null);
    expires_at: string;
    file_name: string;
    max_parallelism: number;
    part_size_bytes: number;
    protocol_version?: string;
    session_id: string;
    size_bytes: number;
    status: string;
    target_node_id: (string | null);
    total_parts: number;
    uploaded_parts: Array<number>;
};
