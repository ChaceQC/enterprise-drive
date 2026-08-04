/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type AdminFileSecurityPolicyCreateRequest = {
    classification?: 'internal' | 'confidential' | 'restricted';
    dlp_action?: 'audit' | 'block';
    dlp_keywords?: Array<string>;
    download_mode?: 'presigned' | 'proxy' | 'watermark' | 'blocked';
    extensions?: Array<string>;
    fail_closed?: boolean;
    is_active?: boolean;
    mime_prefixes?: Array<string>;
    name: string;
    priority?: number;
    watermark_text?: (string | null);
};
