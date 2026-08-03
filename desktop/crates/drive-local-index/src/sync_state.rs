use std::str::FromStr;

use chrono::{DateTime, Utc};
use rusqlite::{params, OptionalExtension};
use uuid::Uuid;

use crate::index::{IndexError, LocalIndex, Result};
use crate::models::{
    PendingOperation, PendingOperationAction, PendingOperationStatus, SyncConflict, SyncEntry,
    SyncEntryKind, SyncEntryStatus, SyncPolicy,
};

impl LocalIndex {
    pub fn upsert_sync_policy(&self, policy: &SyncPolicy) -> Result<()> {
        self.connection.lock().execute(
            "insert into sync_policies(
                root_node_id, device_name, include_patterns_json, ignore_patterns_json,
                bandwidth_limit_bps, max_concurrent_transfers, updated_at
             ) values (?1, ?2, ?3, ?4, ?5, ?6, ?7)
             on conflict(root_node_id) do update set
                device_name = excluded.device_name,
                include_patterns_json = excluded.include_patterns_json,
                ignore_patterns_json = excluded.ignore_patterns_json,
                bandwidth_limit_bps = excluded.bandwidth_limit_bps,
                max_concurrent_transfers = excluded.max_concurrent_transfers,
                updated_at = excluded.updated_at",
            params![
                policy.root_node_id.to_string(),
                policy.device_name,
                serde_json::to_string(&policy.include_patterns).map_err(to_sql_conversion_error)?,
                serde_json::to_string(&policy.ignore_patterns).map_err(to_sql_conversion_error)?,
                policy
                    .bandwidth_limit_bps
                    .and_then(|value| i64::try_from(value).ok()),
                i64::try_from(policy.max_concurrent_transfers).unwrap_or(i64::MAX),
                policy.updated_at.to_rfc3339(),
            ],
        )?;
        Ok(())
    }

    pub fn get_sync_policy(&self, root_node_id: Uuid) -> Result<Option<SyncPolicy>> {
        self.connection
            .lock()
            .query_row(
                "select root_node_id, device_name, include_patterns_json, ignore_patterns_json,
                        bandwidth_limit_bps, max_concurrent_transfers, updated_at
                 from sync_policies where root_node_id = ?1",
                params![root_node_id.to_string()],
                map_sync_policy,
            )
            .optional()
            .map_err(IndexError::from)
    }

    pub fn upsert_sync_entry(&self, entry: &SyncEntry) -> Result<()> {
        upsert_sync_entry_on(&self.connection.lock(), entry)?;
        Ok(())
    }

    pub fn upsert_sync_entries(&self, entries: &[SyncEntry]) -> Result<()> {
        let mut connection = self.connection.lock();
        let transaction = connection.transaction()?;
        for entry in entries {
            upsert_sync_entry_on(&transaction, entry)?;
        }
        transaction.commit()?;
        Ok(())
    }

    pub fn get_sync_entry_by_path(
        &self,
        root_node_id: Uuid,
        relative_path: &str,
    ) -> Result<Option<SyncEntry>> {
        self.connection
            .lock()
            .query_row(
                "select root_node_id, node_id, relative_path, entry_kind, current_version_id,
                        content_hash, size_bytes, local_modified_ns, status, last_error_code,
                        updated_at
                 from sync_entries
                 where root_node_id = ?1 and relative_path = ?2",
                params![root_node_id.to_string(), relative_path],
                map_sync_entry,
            )
            .optional()
            .map_err(IndexError::from)
    }

    pub fn get_sync_entry_by_node(
        &self,
        root_node_id: Uuid,
        node_id: Uuid,
    ) -> Result<Option<SyncEntry>> {
        self.connection
            .lock()
            .query_row(
                "select root_node_id, node_id, relative_path, entry_kind, current_version_id,
                        content_hash, size_bytes, local_modified_ns, status, last_error_code,
                        updated_at
                 from sync_entries
                 where root_node_id = ?1 and node_id = ?2",
                params![root_node_id.to_string(), node_id.to_string()],
                map_sync_entry,
            )
            .optional()
            .map_err(IndexError::from)
    }

    pub fn list_sync_entries(&self, root_node_id: Uuid) -> Result<Vec<SyncEntry>> {
        let connection = self.connection.lock();
        let mut statement = connection.prepare(
            "select root_node_id, node_id, relative_path, entry_kind, current_version_id,
                    content_hash, size_bytes, local_modified_ns, status, last_error_code,
                    updated_at
             from sync_entries
             where root_node_id = ?1
             order by relative_path collate nocase",
        )?;
        let rows = statement.query_map(params![root_node_id.to_string()], map_sync_entry)?;
        rows.collect::<std::result::Result<Vec<_>, _>>()
            .map_err(IndexError::from)
    }

    pub fn delete_sync_entry(&self, root_node_id: Uuid, relative_path: &str) -> Result<()> {
        self.connection.lock().execute(
            "delete from sync_entries where root_node_id = ?1 and relative_path = ?2",
            params![root_node_id.to_string(), relative_path],
        )?;
        Ok(())
    }

    pub fn enqueue_operation(&self, operation: &PendingOperation) -> Result<()> {
        self.connection.lock().execute(
            "insert into pending_operations(
                id, root_node_id, client_operation_id, action, relative_path,
                source_relative_path, node_id, parent_node_id, expected_current_version_id,
                payload_json, status, retry_count, next_attempt_at, error_code,
                created_at, updated_at
             ) values (
                ?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16
             )
             on conflict(client_operation_id) do nothing",
            params![
                operation.id.to_string(),
                operation.root_node_id.to_string(),
                operation.client_operation_id,
                operation.action.as_str(),
                operation.relative_path,
                operation.source_relative_path,
                operation.node_id.map(|value| value.to_string()),
                operation.parent_node_id.map(|value| value.to_string()),
                operation
                    .expected_current_version_id
                    .map(|value| value.to_string()),
                operation.payload_json,
                operation.status.as_str(),
                i64::from(operation.retry_count),
                operation.next_attempt_at.map(|value| value.to_rfc3339()),
                operation.error_code,
                operation.created_at.to_rfc3339(),
                operation.updated_at.to_rfc3339(),
            ],
        )?;
        Ok(())
    }

    pub fn get_operation_by_client_id(
        &self,
        client_operation_id: &str,
    ) -> Result<Option<PendingOperation>> {
        self.connection
            .lock()
            .query_row(
                "select id, root_node_id, client_operation_id, action, relative_path,
                        source_relative_path, node_id, parent_node_id,
                        expected_current_version_id, payload_json, status, retry_count,
                        next_attempt_at, error_code, created_at, updated_at
                 from pending_operations where client_operation_id = ?1",
                params![client_operation_id],
                map_operation,
            )
            .optional()
            .map_err(IndexError::from)
    }

    pub fn list_ready_operations(
        &self,
        now: DateTime<Utc>,
        limit: usize,
    ) -> Result<Vec<PendingOperation>> {
        let connection = self.connection.lock();
        let mut statement = connection.prepare(
            "select id, root_node_id, client_operation_id, action, relative_path,
                    source_relative_path, node_id, parent_node_id,
                    expected_current_version_id, payload_json, status, retry_count,
                    next_attempt_at, error_code, created_at, updated_at
             from pending_operations
             where status in ('queued', 'retrying')
               and (next_attempt_at is null or next_attempt_at <= ?1)
             order by created_at, id
             limit ?2",
        )?;
        let rows = statement.query_map(
            params![
                now.to_rfc3339(),
                i64::try_from(limit.max(1)).unwrap_or(i64::MAX)
            ],
            map_operation,
        )?;
        rows.collect::<std::result::Result<Vec<_>, _>>()
            .map_err(IndexError::from)
    }

    pub fn list_ready_operations_for_root(
        &self,
        root_node_id: Uuid,
        now: DateTime<Utc>,
        limit: usize,
    ) -> Result<Vec<PendingOperation>> {
        let connection = self.connection.lock();
        let mut statement = connection.prepare(
            "select id, root_node_id, client_operation_id, action, relative_path,
                    source_relative_path, node_id, parent_node_id,
                    expected_current_version_id, payload_json, status, retry_count,
                    next_attempt_at, error_code, created_at, updated_at
             from pending_operations
             where root_node_id = ?1
               and status in ('queued', 'retrying')
               and (next_attempt_at is null or next_attempt_at <= ?2)
             order by created_at, id
             limit ?3",
        )?;
        let rows = statement.query_map(
            params![
                root_node_id.to_string(),
                now.to_rfc3339(),
                i64::try_from(limit.max(1)).unwrap_or(i64::MAX),
            ],
            map_operation,
        )?;
        rows.collect::<std::result::Result<Vec<_>, _>>()
            .map_err(IndexError::from)
    }

    pub fn list_operations(&self, root_node_id: Uuid) -> Result<Vec<PendingOperation>> {
        let connection = self.connection.lock();
        let mut statement = connection.prepare(
            "select id, root_node_id, client_operation_id, action, relative_path,
                    source_relative_path, node_id, parent_node_id,
                    expected_current_version_id, payload_json, status, retry_count,
                    next_attempt_at, error_code, created_at, updated_at
             from pending_operations
             where root_node_id = ?1
             order by created_at desc, id desc",
        )?;
        let rows = statement.query_map(params![root_node_id.to_string()], map_operation)?;
        rows.collect::<std::result::Result<Vec<_>, _>>()
            .map_err(IndexError::from)
    }

    pub fn update_operation(
        &self,
        operation_id: Uuid,
        status: PendingOperationStatus,
        retry_count: u32,
        next_attempt_at: Option<DateTime<Utc>>,
        error_code: Option<&str>,
    ) -> Result<()> {
        self.connection.lock().execute(
            "update pending_operations set
                status = ?2,
                retry_count = ?3,
                next_attempt_at = ?4,
                error_code = ?5,
                updated_at = ?6
             where id = ?1",
            params![
                operation_id.to_string(),
                status.as_str(),
                i64::from(retry_count),
                next_attempt_at.map(|value| value.to_rfc3339()),
                error_code,
                Utc::now().to_rfc3339(),
            ],
        )?;
        Ok(())
    }

    pub fn recover_interrupted_operations(&self) -> Result<usize> {
        let now = Utc::now().to_rfc3339();
        let updated = self.connection.lock().execute(
            "update pending_operations set
                status = 'retrying',
                next_attempt_at = ?1,
                error_code = 'PROCESS_INTERRUPTED',
                updated_at = ?1
             where status = 'running'",
            params![now],
        )?;
        Ok(updated)
    }

    pub fn record_conflict(&self, conflict: &SyncConflict) -> Result<()> {
        self.connection.lock().execute(
            "insert into sync_conflicts(
                id, root_node_id, node_id, conflict_kind, original_relative_path,
                conflict_relative_path, device_name, details_json, detected_at
             ) values (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)",
            params![
                conflict.id.to_string(),
                conflict.root_node_id.to_string(),
                conflict.node_id.map(|value| value.to_string()),
                conflict.kind,
                conflict.original_relative_path,
                conflict.conflict_relative_path,
                conflict.device_name,
                conflict.details_json,
                conflict.detected_at.to_rfc3339(),
            ],
        )?;
        Ok(())
    }

    pub fn list_conflicts(&self, root_node_id: Uuid) -> Result<Vec<SyncConflict>> {
        let connection = self.connection.lock();
        let mut statement = connection.prepare(
            "select id, root_node_id, node_id, conflict_kind, original_relative_path,
                    conflict_relative_path, device_name, details_json, detected_at
             from sync_conflicts where root_node_id = ?1
             order by detected_at desc, id desc",
        )?;
        let rows = statement.query_map(params![root_node_id.to_string()], map_conflict)?;
        rows.collect::<std::result::Result<Vec<_>, _>>()
            .map_err(IndexError::from)
    }

    pub fn set_sync_root_enabled(&self, root_node_id: Uuid, enabled: bool) -> Result<()> {
        if !enabled {
            return self.disable_sync_root(root_node_id, "SYNC_PERMISSION_REVOKED");
        }
        self.connection.lock().execute(
            "update sync_roots set enabled = 1, updated_at = ?2 where root_node_id = ?1",
            params![root_node_id.to_string(), Utc::now().to_rfc3339()],
        )?;
        Ok(())
    }

    pub fn disable_sync_root(&self, root_node_id: Uuid, error_code: &str) -> Result<()> {
        let mut connection = self.connection.lock();
        let transaction = connection.transaction()?;
        transaction.execute(
            "update sync_roots set enabled = 0, updated_at = ?2 where root_node_id = ?1",
            params![root_node_id.to_string(), Utc::now().to_rfc3339(),],
        )?;
        transaction.execute(
            "update sync_entries set
                status = 'permission_revoked',
                last_error_code = ?2,
                updated_at = ?3
             where root_node_id = ?1",
            params![
                root_node_id.to_string(),
                error_code,
                Utc::now().to_rfc3339(),
            ],
        )?;
        transaction.execute(
            "update pending_operations set
                status = 'failed',
                error_code = ?2,
                next_attempt_at = null,
                updated_at = ?3
             where root_node_id = ?1 and status in ('queued', 'running', 'retrying')",
            params![
                root_node_id.to_string(),
                error_code,
                Utc::now().to_rfc3339(),
            ],
        )?;
        transaction.commit()?;
        Ok(())
    }
}

fn upsert_sync_entry_on(
    connection: &rusqlite::Connection,
    entry: &SyncEntry,
) -> rusqlite::Result<usize> {
    connection.execute(
        "insert into sync_entries(
            root_node_id, node_id, relative_path, entry_kind, current_version_id,
            content_hash, size_bytes, local_modified_ns, status, last_error_code, updated_at
         ) values (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)
         on conflict(root_node_id, relative_path) do update set
            node_id = excluded.node_id,
            entry_kind = excluded.entry_kind,
            current_version_id = excluded.current_version_id,
            content_hash = excluded.content_hash,
            size_bytes = excluded.size_bytes,
            local_modified_ns = excluded.local_modified_ns,
            status = excluded.status,
            last_error_code = excluded.last_error_code,
            updated_at = excluded.updated_at",
        params![
            entry.root_node_id.to_string(),
            entry.node_id.map(|value| value.to_string()),
            entry.relative_path,
            entry.kind.as_str(),
            entry.current_version_id.map(|value| value.to_string()),
            entry.content_hash,
            entry.size_bytes,
            entry.local_modified_ns,
            entry.status.as_str(),
            entry.last_error_code,
            entry.updated_at.to_rfc3339(),
        ],
    )
}

fn map_sync_policy(row: &rusqlite::Row<'_>) -> rusqlite::Result<SyncPolicy> {
    let bandwidth = row.get::<_, Option<i64>>(4)?;
    let max_concurrent = row.get::<_, i64>(5)?;
    Ok(SyncPolicy {
        root_node_id: parse_uuid(row.get::<_, String>(0)?)?,
        device_name: row.get(1)?,
        include_patterns: serde_json::from_str(&row.get::<_, String>(2)?)
            .map_err(to_sql_conversion_error)?,
        ignore_patterns: serde_json::from_str(&row.get::<_, String>(3)?)
            .map_err(to_sql_conversion_error)?,
        bandwidth_limit_bps: bandwidth.and_then(|value| u64::try_from(value).ok()),
        max_concurrent_transfers: usize::try_from(max_concurrent).unwrap_or(1).max(1),
        updated_at: parse_timestamp(row.get::<_, String>(6)?)?,
    })
}

fn map_sync_entry(row: &rusqlite::Row<'_>) -> rusqlite::Result<SyncEntry> {
    Ok(SyncEntry {
        root_node_id: parse_uuid(row.get::<_, String>(0)?)?,
        node_id: parse_optional_uuid(row.get(1)?)?,
        relative_path: row.get(2)?,
        kind: parse_entry_kind(&row.get::<_, String>(3)?)?,
        current_version_id: parse_optional_uuid(row.get(4)?)?,
        content_hash: row.get(5)?,
        size_bytes: row.get(6)?,
        local_modified_ns: row.get(7)?,
        status: parse_entry_status(&row.get::<_, String>(8)?)?,
        last_error_code: row.get(9)?,
        updated_at: parse_timestamp(row.get::<_, String>(10)?)?,
    })
}

fn map_operation(row: &rusqlite::Row<'_>) -> rusqlite::Result<PendingOperation> {
    let retry_count = row.get::<_, i64>(11)?;
    Ok(PendingOperation {
        id: parse_uuid(row.get::<_, String>(0)?)?,
        root_node_id: parse_uuid(row.get::<_, String>(1)?)?,
        client_operation_id: row.get(2)?,
        action: parse_operation_action(&row.get::<_, String>(3)?)?,
        relative_path: row.get(4)?,
        source_relative_path: row.get(5)?,
        node_id: parse_optional_uuid(row.get(6)?)?,
        parent_node_id: parse_optional_uuid(row.get(7)?)?,
        expected_current_version_id: parse_optional_uuid(row.get(8)?)?,
        payload_json: row.get(9)?,
        status: parse_operation_status(&row.get::<_, String>(10)?)?,
        retry_count: u32::try_from(retry_count).unwrap_or(u32::MAX),
        next_attempt_at: parse_optional_timestamp(row.get(12)?)?,
        error_code: row.get(13)?,
        created_at: parse_timestamp(row.get::<_, String>(14)?)?,
        updated_at: parse_timestamp(row.get::<_, String>(15)?)?,
    })
}

fn map_conflict(row: &rusqlite::Row<'_>) -> rusqlite::Result<SyncConflict> {
    Ok(SyncConflict {
        id: parse_uuid(row.get::<_, String>(0)?)?,
        root_node_id: parse_uuid(row.get::<_, String>(1)?)?,
        node_id: parse_optional_uuid(row.get(2)?)?,
        kind: row.get(3)?,
        original_relative_path: row.get(4)?,
        conflict_relative_path: row.get(5)?,
        device_name: row.get(6)?,
        details_json: row.get(7)?,
        detected_at: parse_timestamp(row.get::<_, String>(8)?)?,
    })
}

fn parse_uuid(value: String) -> rusqlite::Result<Uuid> {
    Uuid::from_str(&value).map_err(to_sql_conversion_error)
}

fn parse_optional_uuid(value: Option<String>) -> rusqlite::Result<Option<Uuid>> {
    value.map(parse_uuid).transpose()
}

fn parse_timestamp(value: String) -> rusqlite::Result<DateTime<Utc>> {
    DateTime::parse_from_rfc3339(&value)
        .map(|value| value.with_timezone(&Utc))
        .map_err(to_sql_conversion_error)
}

fn parse_optional_timestamp(value: Option<String>) -> rusqlite::Result<Option<DateTime<Utc>>> {
    value.map(parse_timestamp).transpose()
}

fn parse_entry_kind(value: &str) -> rusqlite::Result<SyncEntryKind> {
    match value {
        "file" => Ok(SyncEntryKind::File),
        "folder" => Ok(SyncEntryKind::Folder),
        other => Err(invalid_enum(other)),
    }
}

fn parse_entry_status(value: &str) -> rusqlite::Result<SyncEntryStatus> {
    match value {
        "synced" => Ok(SyncEntryStatus::Synced),
        "local_pending" => Ok(SyncEntryStatus::LocalPending),
        "remote_pending" => Ok(SyncEntryStatus::RemotePending),
        "conflict" => Ok(SyncEntryStatus::Conflict),
        "ignored" => Ok(SyncEntryStatus::Ignored),
        "error" => Ok(SyncEntryStatus::Error),
        "permission_revoked" => Ok(SyncEntryStatus::PermissionRevoked),
        other => Err(invalid_enum(other)),
    }
}

fn parse_operation_action(value: &str) -> rusqlite::Result<PendingOperationAction> {
    match value {
        "create_folder" => Ok(PendingOperationAction::CreateFolder),
        "upload_file" => Ok(PendingOperationAction::UploadFile),
        "rename" => Ok(PendingOperationAction::Rename),
        "move" => Ok(PendingOperationAction::Move),
        "delete" => Ok(PendingOperationAction::Delete),
        other => Err(invalid_enum(other)),
    }
}

fn parse_operation_status(value: &str) -> rusqlite::Result<PendingOperationStatus> {
    match value {
        "queued" => Ok(PendingOperationStatus::Queued),
        "running" => Ok(PendingOperationStatus::Running),
        "retrying" => Ok(PendingOperationStatus::Retrying),
        "completed" => Ok(PendingOperationStatus::Completed),
        "conflict" => Ok(PendingOperationStatus::Conflict),
        "failed" => Ok(PendingOperationStatus::Failed),
        other => Err(invalid_enum(other)),
    }
}

fn invalid_enum(value: &str) -> rusqlite::Error {
    to_sql_conversion_error(IndexError::InvalidEnum(value.to_string()))
}

fn to_sql_conversion_error(
    error: impl std::error::Error + Send + Sync + 'static,
) -> rusqlite::Error {
    rusqlite::Error::FromSqlConversionFailure(0, rusqlite::types::Type::Text, Box::new(error))
}

#[cfg(test)]
mod tests {
    use chrono::Utc;
    use uuid::Uuid;

    use crate::{
        LocalIndex, PendingOperation, PendingOperationAction, PendingOperationStatus, SyncPolicy,
        SyncRoot, TransferDirection, TransferStatus, TransferTask,
    };

    #[test]
    fn offline_operations_and_transfers_recover_after_process_restart() {
        let directory = tempfile::tempdir().unwrap();
        let database = directory.path().join("desktop-index.sqlite3");
        let root_node_id = Uuid::new_v4();
        let space_id = Uuid::new_v4();
        let operation_id = Uuid::new_v4();
        let transfer_id = Uuid::new_v4();
        let now = Utc::now();
        {
            let index = LocalIndex::open(&database).unwrap();
            index
                .upsert_sync_root(&SyncRoot {
                    root_node_id,
                    space_id,
                    local_path: "C:\\Drive".to_string(),
                    cursor: Some("cursor".to_string()),
                    enabled: true,
                    updated_at: now,
                })
                .unwrap();
            index
                .upsert_sync_policy(&SyncPolicy {
                    root_node_id,
                    device_name: "Laptop".to_string(),
                    include_patterns: Vec::new(),
                    ignore_patterns: vec!["**/*.tmp".to_string()],
                    bandwidth_limit_bps: Some(1024),
                    max_concurrent_transfers: 2,
                    updated_at: now,
                })
                .unwrap();
            index
                .enqueue_operation(&PendingOperation {
                    id: operation_id,
                    root_node_id,
                    client_operation_id: operation_id.to_string(),
                    action: PendingOperationAction::UploadFile,
                    relative_path: "offline.txt".to_string(),
                    source_relative_path: None,
                    node_id: Some(Uuid::new_v4()),
                    parent_node_id: Some(root_node_id),
                    expected_current_version_id: Some(Uuid::new_v4()),
                    payload_json: "{}".to_string(),
                    status: PendingOperationStatus::Queued,
                    retry_count: 0,
                    next_attempt_at: None,
                    error_code: None,
                    created_at: now,
                    updated_at: now,
                })
                .unwrap();
            index
                .update_operation(operation_id, PendingOperationStatus::Running, 0, None, None)
                .unwrap();
            index
                .enqueue_transfer(&TransferTask {
                    id: transfer_id,
                    root_node_id: Some(root_node_id),
                    direction: TransferDirection::Upload,
                    status: TransferStatus::Running,
                    local_path: "C:\\Drive\\offline.txt".to_string(),
                    temp_path: None,
                    space_id: Some(space_id),
                    parent_id: Some(root_node_id),
                    node_id: Some(Uuid::new_v4()),
                    expected_current_version_id: Some(Uuid::new_v4()),
                    current_version_id: None,
                    session_id: None,
                    size_bytes: 128,
                    transferred_bytes: 64,
                    content_hash: Some("ab".repeat(32)),
                    client_operation_id: operation_id.to_string(),
                    retry_count: 1,
                    next_attempt_at: None,
                    error_code: None,
                    created_at: now,
                    updated_at: now,
                })
                .unwrap();
        }

        let reopened = LocalIndex::open(&database).unwrap();
        assert_eq!(reopened.recover_interrupted_operations().unwrap(), 1);
        assert_eq!(reopened.recover_automatic_transfers().unwrap(), 1);
        let operation = reopened
            .get_operation_by_client_id(&operation_id.to_string())
            .unwrap()
            .unwrap();
        let transfer = reopened.get_transfer(transfer_id).unwrap().unwrap();
        let policy = reopened.get_sync_policy(root_node_id).unwrap().unwrap();

        assert_eq!(operation.status, PendingOperationStatus::Retrying);
        assert_eq!(operation.error_code.as_deref(), Some("PROCESS_INTERRUPTED"));
        assert_eq!(transfer.status, TransferStatus::Queued);
        assert_eq!(transfer.error_code.as_deref(), Some("PROCESS_INTERRUPTED"));
        assert_eq!(policy.max_concurrent_transfers, 2);
    }

    #[test]
    fn sprint8_root_scoped_ready_queues_are_isolated() {
        let index = LocalIndex::open_in_memory().unwrap();
        let now = Utc::now();
        let first_root = Uuid::new_v4();
        let second_root = Uuid::new_v4();
        for (root_node_id, suffix) in [(first_root, "first"), (second_root, "second")] {
            index
                .upsert_sync_root(&SyncRoot {
                    root_node_id,
                    space_id: Uuid::new_v4(),
                    local_path: format!("C:\\Drive\\{suffix}"),
                    cursor: Some(format!("cursor-{suffix}")),
                    enabled: true,
                    updated_at: now,
                })
                .unwrap();
            let operation_id = Uuid::new_v4();
            index
                .enqueue_operation(&PendingOperation {
                    id: operation_id,
                    root_node_id,
                    client_operation_id: operation_id.to_string(),
                    action: PendingOperationAction::UploadFile,
                    relative_path: format!("{suffix}.txt"),
                    source_relative_path: None,
                    node_id: Some(Uuid::new_v4()),
                    parent_node_id: Some(root_node_id),
                    expected_current_version_id: Some(Uuid::new_v4()),
                    payload_json: "{}".to_string(),
                    status: PendingOperationStatus::Queued,
                    retry_count: 0,
                    next_attempt_at: None,
                    error_code: None,
                    created_at: now,
                    updated_at: now,
                })
                .unwrap();
            index
                .enqueue_transfer(&TransferTask {
                    id: Uuid::new_v4(),
                    root_node_id: Some(root_node_id),
                    direction: TransferDirection::Download,
                    status: TransferStatus::Queued,
                    local_path: format!("C:\\Drive\\{suffix}.txt"),
                    temp_path: Some(format!("C:\\Drive\\{suffix}.txt.drivepart")),
                    space_id: None,
                    parent_id: None,
                    node_id: Some(Uuid::new_v4()),
                    expected_current_version_id: None,
                    current_version_id: Some(Uuid::new_v4()),
                    session_id: None,
                    size_bytes: 128,
                    transferred_bytes: 0,
                    content_hash: None,
                    client_operation_id: Uuid::new_v4().to_string(),
                    retry_count: 0,
                    next_attempt_at: None,
                    error_code: None,
                    created_at: now,
                    updated_at: now,
                })
                .unwrap();
        }

        let operations = index
            .list_ready_operations_for_root(first_root, now, 8)
            .unwrap();
        let transfers = index
            .list_runnable_transfers_for_root(second_root, now, 8)
            .unwrap();

        assert_eq!(operations.len(), 1);
        assert_eq!(operations[0].root_node_id, first_root);
        assert_eq!(transfers.len(), 1);
        assert_eq!(transfers[0].root_node_id, Some(second_root));
    }
}
