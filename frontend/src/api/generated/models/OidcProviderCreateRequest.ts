/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type OidcProviderCreateRequest = {
    client_id: string;
    client_secret_ref?: (string | null);
    enabled?: boolean;
    issuer_url: string;
    name: string;
    scopes?: Array<string>;
    slug: string;
};
