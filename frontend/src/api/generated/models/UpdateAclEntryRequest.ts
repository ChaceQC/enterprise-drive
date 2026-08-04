/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type UpdateAclEntryRequest = {
    actions: Array<'delete' | 'download' | 'grant' | 'list' | 'manage' | 'preview' | 'read_meta' | 'restore' | 'share' | 'update' | 'upload'>;
    effect: 'allow' | 'deny';
    inherit?: boolean;
};
