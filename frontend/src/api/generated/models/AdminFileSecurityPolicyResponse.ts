/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type AdminFileSecurityPolicyResponse = {
    classification: 'internal' | 'confidential' | 'restricted';
    created_at: string;
    dlp_action: 'audit' | 'block';
    dlp_keywords: Array<string>;
    download_mode: 'presigned' | 'proxy' | 'watermark' | 'blocked';
    extensions: Array<string>;
    fail_closed: boolean;
    id: string;
    is_active: boolean;
    mime_prefixes: Array<string>;
    name: string;
    priority: number;
    tenant_id: string;
    updated_at: string;
    version: number;
    watermark_text: (string | null);
};
