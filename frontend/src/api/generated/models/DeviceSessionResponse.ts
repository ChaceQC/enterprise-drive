/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { DeviceResponse } from './DeviceResponse';
import type { UserProfileResponse } from './UserProfileResponse';
export type DeviceSessionResponse = {
    access_token: string;
    device: DeviceResponse;
    expires_at: string;
    token_type?: string;
    user: UserProfileResponse;
};
