/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type CreateAclEntryRequest = {
    actions: Array<'delete' | 'download' | 'grant' | 'list' | 'manage' | 'preview' | 'read_meta' | 'restore' | 'share' | 'update' | 'upload'>;
    effect: 'allow' | 'deny';
    inherit?: boolean;
    subject_id: string;
    subject_type: 'user' | 'department' | 'group';
};
