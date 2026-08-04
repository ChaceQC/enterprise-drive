/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { UserProfileResponse } from './UserProfileResponse';
export type SessionResponse = {
    authenticated?: boolean;
    expires_at: string;
    user: UserProfileResponse;
};
