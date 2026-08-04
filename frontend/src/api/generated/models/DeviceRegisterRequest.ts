/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type DeviceRegisterRequest = {
    client_version: string;
    device_name: string;
    installation_id: string;
    password: string;
    platform: 'windows' | 'macos' | 'linux';
    tenant_slug?: string;
    username: string;
};
