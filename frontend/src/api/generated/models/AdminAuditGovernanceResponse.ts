/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AdminAuditArchiveResponse } from './AdminAuditArchiveResponse';
export type AdminAuditGovernanceResponse = {
    archive_delete_source: boolean;
    archives_failed: number;
    archives_total: number;
    external_delivery_enabled: boolean;
    generated_at: string;
    last_archive_succeeded_at: (string | null);
    last_delivery_failed_at: (string | null);
    last_delivery_succeeded_at: (string | null);
    oldest_pending_at: (string | null);
    outbox_dead: number;
    outbox_failed: number;
    outbox_pending: number;
    outbox_processing: number;
    outbox_sent: number;
    partition_months_ahead: number;
    recent_archives: Array<AdminAuditArchiveResponse>;
    retention_days: number;
};
