/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { InternalShareItem } from './InternalShareItem';
import type { ShareListItem } from './ShareListItem';
export type InternalShareItemsResponse = {
    access_role: 'creator' | 'recipient';
    items: Array<InternalShareItem>;
    share: ShareListItem;
};
