/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type AdminQuotaPolicyCreateRequest = {
    extensions?: Array<string>;
    is_active?: boolean;
    limit_bytes: number;
    max_file_size_bytes?: (number | null);
    mime_prefixes?: Array<string>;
    name: string;
    priority?: number;
};
