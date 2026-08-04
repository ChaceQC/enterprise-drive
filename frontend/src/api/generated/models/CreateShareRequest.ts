/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ShareRecipientInput } from './ShareRecipientInput';
export type CreateShareRequest = {
    expires_at?: (string | null);
    item_node_ids?: Array<string>;
    max_downloads?: (number | null);
    max_views?: (number | null);
    passcode?: (string | null);
    permission?: 'preview' | 'download';
    recipients?: Array<ShareRecipientInput>;
    root_node_id: string;
    share_type: 'internal' | 'external';
};
