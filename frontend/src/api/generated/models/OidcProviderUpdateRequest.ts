/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type OidcProviderUpdateRequest = {
    clear_client_secret_ref?: boolean;
    client_id?: (string | null);
    client_secret_ref?: (string | null);
    enabled?: (boolean | null);
    expected_version: number;
    issuer_url?: (string | null);
    name?: (string | null);
    scopes?: (Array<string> | null);
};
