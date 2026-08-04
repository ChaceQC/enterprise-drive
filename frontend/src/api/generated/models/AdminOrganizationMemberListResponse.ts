/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AdminOrganizationMemberResponse } from './AdminOrganizationMemberResponse';
export type AdminOrganizationMemberListResponse = {
    items: Array<AdminOrganizationMemberResponse>;
    next_cursor?: (string | null);
    organization_version: number;
};
