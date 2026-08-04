/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type ExternalShareDownloadRequest = {
    delivery_mode?: 'presigned' | 'watermark';
    node_id: string;
    passcode?: (string | null);
    raw_token: string;
    tenant_slug: string;
};
