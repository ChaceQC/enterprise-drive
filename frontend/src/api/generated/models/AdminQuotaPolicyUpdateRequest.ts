/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type AdminQuotaPolicyUpdateRequest = {
    clear_max_file_size?: boolean;
    expected_limit_bytes: number;
    extensions?: (Array<string> | null);
    is_active?: (boolean | null);
    limit_bytes?: (number | null);
    max_file_size_bytes?: (number | null);
    mime_prefixes?: (Array<string> | null);
    name?: (string | null);
    priority?: (number | null);
};
