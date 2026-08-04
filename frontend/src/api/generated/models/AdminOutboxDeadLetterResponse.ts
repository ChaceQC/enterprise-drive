/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type AdminOutboxDeadLetterResponse = {
    aggregate_id: string;
    aggregate_type: string;
    created_at: string;
    dead_at: (string | null);
    event_type: string;
    id: string;
    last_error_code: (string | null);
    last_error_kind: (string | null);
    last_failed_at: (string | null);
    last_replayed_at: (string | null);
    last_replayed_by: (string | null);
    payload_keys: Array<string>;
    replay_count: number;
    retry_count: number;
    status: string;
    updated_at: string;
};
