/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type AdminAuditLogResponse = {
    action: string;
    actor_id: (string | null);
    actor_type: string;
    created_at: string;
    id: string;
    ip: (string | null);
    metadata?: Record<string, any>;
    request_id: (string | null);
    resource_id: (string | null);
    resource_type: string;
    result: string;
    risk_level: string;
    tenant_id: string;
    user_agent: (string | null);
};
