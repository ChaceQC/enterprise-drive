/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type AdminFileSecurityPolicyUpdateRequest = {
    classification?: ('internal' | 'confidential' | 'restricted' | null);
    clear_watermark_text?: boolean;
    dlp_action?: ('audit' | 'block' | null);
    dlp_keywords?: (Array<string> | null);
    download_mode?: ('presigned' | 'proxy' | 'watermark' | 'blocked' | null);
    expected_version: number;
    extensions?: (Array<string> | null);
    fail_closed?: (boolean | null);
    is_active?: (boolean | null);
    mime_prefixes?: (Array<string> | null);
    name?: (string | null);
    priority?: (number | null);
    watermark_text?: (string | null);
};
