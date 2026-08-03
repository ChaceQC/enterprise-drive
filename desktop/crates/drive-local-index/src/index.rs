use std::path::Path;
use std::str::FromStr;
use std::sync::Arc;

use chrono::{DateTime, Utc};
use parking_lot::Mutex;
use rusqlite::{params, Connection, OptionalExtension};
use thiserror::Error;
use uuid::Uuid;

use crate::models::{
    ConfirmedPart, IndexedNode, OperationLogEntry, SyncRoot, TransferDirection, TransferStatus,
    TransferTask,
};

pub type Result<T> = std::result::Result<T, IndexError>;

#[derive(Debug, Error)]
pub enum IndexError {
    #[error("SQLite operation failed: {0}")]
    Sqlite(#[from] rusqlite::Error),
    #[error("invalid UUID stored in local index: {0}")]
    InvalidUuid(#[from] uuid::Error),
    #[error("invalid timestamp stored in local index: {0}")]
    InvalidTimestamp(#[from] chrono::ParseError),
    #[error("invalid enum value stored in local index: {0}")]
    InvalidEnum(String),
}

#[derive(Clone)]
pub struct LocalIndex {
    connection: Arc<Mutex<Connection>>,
}

impl LocalIndex {
    pub fn open(path: impl AsRef<Path>) -> Result<Self> {
        let connection = Connection::open(path)?;
        let index = Self {
            connection: Arc::new(Mutex::new(connection)),
        };
        index.migrate()?;
        Ok(index)
    }

    pub fn open_in_memory() -> Result<Self> {
        let connection = Connection::open_in_memory()?;
        let index = Self {
            connection: Arc::new(Mutex::new(connection)),
        };
        index.migrate()?;
        Ok(index)
    }

    pub fn installation_id(&self) -> Result<Uuid> {
        if let Some(value) = self.get_metadata("installation_id")? {
            return Ok(Uuid::from_str(&value)?);
        }
        let installation_id = Uuid::new_v4();
        self.set_metadata("installation_id", &installation_id.to_string())?;
        Ok(installation_id)
    }

    pub fn set_metadata(&self, key: &str, value: &str) -> Result<()> {
        self.connection.lock().execute(
            "insert into metadata(key, value) values (?1, ?2)
             on conflict(key) do update set value = excluded.value",
            params![key, value],
        )?;
        Ok(())
    }

    pub fn get_metadata(&self, key: &str) -> Result<Option<String>> {
        Ok(self
            .connection
            .lock()
            .query_row(
                "select value from metadata where key = ?1",
                params![key],
                |row| row.get(0),
            )
            .optional()?)
    }

    pub fn upsert_node(&self, node: &IndexedNode) -> Result<()> {
        upsert_node_on(&self.connection.lock(), node)?;
        Ok(())
    }

    pub fn list_children(&self, space_id: Uuid, parent_id: Uuid) -> Result<Vec<IndexedNode>> {
        let connection = self.connection.lock();
        let mut statement = connection.prepare(
            "select node_id, space_id, parent_id, node_type, name, current_version_id,
                    permission_version, tombstone, changed_at
             from nodes
             where space_id = ?1 and parent_id = ?2 and tombstone = 0
             order by name collate nocase, node_id",
        )?;
        let rows = statement.query_map(
            params![space_id.to_string(), parent_id.to_string()],
            map_node,
        )?;
        rows.collect::<std::result::Result<Vec<_>, _>>()
            .map_err(IndexError::from)
    }

    pub fn upsert_sync_root(&self, root: &SyncRoot) -> Result<()> {
        self.connection.lock().execute(
            "insert into sync_roots(root_node_id, space_id, local_path, cursor, enabled, updated_at)
             values (?1, ?2, ?3, ?4, ?5, ?6)
             on conflict(root_node_id) do update set
                space_id = excluded.space_id,
                local_path = excluded.local_path,
                cursor = excluded.cursor,
                enabled = excluded.enabled,
                updated_at = excluded.updated_at",
            params![
                root.root_node_id.to_string(),
                root.space_id.to_string(),
                root.local_path,
                root.cursor,
                i32::from(root.enabled),
                root.updated_at.to_rfc3339(),
            ],
        )?;
        Ok(())
    }

    pub fn get_sync_root(&self, root_node_id: Uuid) -> Result<Option<SyncRoot>> {
        self.connection
            .lock()
            .query_row(
                "select root_node_id, space_id, local_path, cursor, enabled, updated_at
                 from sync_roots where root_node_id = ?1",
                params![root_node_id.to_string()],
                |row| {
                    Ok(SyncRoot {
                        root_node_id: parse_uuid(row.get::<_, String>(0)?)?,
                        space_id: parse_uuid(row.get::<_, String>(1)?)?,
                        local_path: row.get(2)?,
                        cursor: row.get(3)?,
                        enabled: row.get::<_, i32>(4)? != 0,
                        updated_at: parse_timestamp(row.get::<_, String>(5)?)?,
                    })
                },
            )
            .optional()
            .map_err(IndexError::from)
    }

    pub fn list_sync_roots(&self) -> Result<Vec<SyncRoot>> {
        let connection = self.connection.lock();
        let mut statement = connection.prepare(
            "select root_node_id, space_id, local_path, cursor, enabled, updated_at
             from sync_roots order by updated_at desc, root_node_id",
        )?;
        let rows = statement.query_map([], map_sync_root)?;
        rows.collect::<std::result::Result<Vec<_>, _>>()
            .map_err(IndexError::from)
    }

    pub fn save_cursor(&self, root_node_id: Uuid, cursor: &str) -> Result<()> {
        self.connection.lock().execute(
            "update sync_roots set cursor = ?2, updated_at = ?3 where root_node_id = ?1",
            params![root_node_id.to_string(), cursor, Utc::now().to_rfc3339()],
        )?;
        Ok(())
    }

    pub fn apply_sync_page(
        &self,
        root_node_id: Uuid,
        nodes: &[IndexedNode],
        cursor: &str,
    ) -> Result<()> {
        let mut connection = self.connection.lock();
        let transaction = connection.transaction()?;
        for node in nodes {
            upsert_node_on(&transaction, node)?;
        }
        transaction.execute(
            "update sync_roots set cursor = ?2, updated_at = ?3 where root_node_id = ?1",
            params![root_node_id.to_string(), cursor, Utc::now().to_rfc3339()],
        )?;
        transaction.commit()?;
        Ok(())
    }

    pub fn append_operation(&self, operation: &OperationLogEntry) -> Result<()> {
        self.connection.lock().execute(
            "insert into operation_log(
                client_operation_id, action, payload_json, status, error_code, updated_at
             ) values (?1, ?2, ?3, ?4, ?5, ?6)
             on conflict(client_operation_id) do update set
                status = excluded.status,
                error_code = excluded.error_code,
                updated_at = excluded.updated_at",
            params![
                operation.client_operation_id,
                operation.action,
                operation.payload_json,
                operation.status,
                operation.error_code,
                operation.updated_at.to_rfc3339(),
            ],
        )?;
        Ok(())
    }

    pub fn enqueue_transfer(&self, task: &TransferTask) -> Result<()> {
        self.connection.lock().execute(
            "insert into transfer_tasks(
                id, direction, status, local_path, temp_path, space_id, parent_id, node_id,
                session_id, size_bytes, transferred_bytes, content_hash,
                client_operation_id, error_code, created_at, updated_at
             ) values (
                ?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16
             )",
            params![
                task.id.to_string(),
                task.direction.as_str(),
                task.status.as_str(),
                task.local_path,
                task.temp_path,
                task.space_id.map(|value| value.to_string()),
                task.parent_id.map(|value| value.to_string()),
                task.node_id.map(|value| value.to_string()),
                task.session_id.map(|value| value.to_string()),
                task.size_bytes,
                task.transferred_bytes,
                task.content_hash,
                task.client_operation_id,
                task.error_code,
                task.created_at.to_rfc3339(),
                task.updated_at.to_rfc3339(),
            ],
        )?;
        Ok(())
    }

    pub fn get_transfer(&self, task_id: Uuid) -> Result<Option<TransferTask>> {
        self.connection
            .lock()
            .query_row(
                "select id, direction, status, local_path, temp_path, space_id, parent_id,
                        node_id, session_id, size_bytes, transferred_bytes, content_hash,
                        client_operation_id, error_code, created_at, updated_at
                 from transfer_tasks where id = ?1",
                params![task_id.to_string()],
                map_transfer,
            )
            .optional()
            .map_err(IndexError::from)
    }

    pub fn list_transfers(&self) -> Result<Vec<TransferTask>> {
        let connection = self.connection.lock();
        let mut statement = connection.prepare(
            "select id, direction, status, local_path, temp_path, space_id, parent_id,
                    node_id, session_id, size_bytes, transferred_bytes, content_hash,
                    client_operation_id, error_code, created_at, updated_at
             from transfer_tasks order by created_at desc, id desc",
        )?;
        let rows = statement.query_map([], map_transfer)?;
        rows.collect::<std::result::Result<Vec<_>, _>>()
            .map_err(IndexError::from)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn update_transfer(
        &self,
        task_id: Uuid,
        status: TransferStatus,
        transferred_bytes: i64,
        session_id: Option<Uuid>,
        content_hash: Option<&str>,
        error_code: Option<&str>,
        temp_path: Option<&str>,
    ) -> Result<()> {
        self.connection.lock().execute(
            "update transfer_tasks set
                status = ?2,
                transferred_bytes = ?3,
                session_id = coalesce(?4, session_id),
                content_hash = coalesce(?5, content_hash),
                error_code = ?6,
                temp_path = coalesce(?7, temp_path),
                updated_at = ?8
             where id = ?1",
            params![
                task_id.to_string(),
                status.as_str(),
                transferred_bytes,
                session_id.map(|value| value.to_string()),
                content_hash,
                error_code,
                temp_path,
                Utc::now().to_rfc3339(),
            ],
        )?;
        Ok(())
    }

    pub fn update_transfer_descriptor(
        &self,
        task_id: Uuid,
        node_id: Option<Uuid>,
        session_id: Option<Uuid>,
        size_bytes: Option<i64>,
        content_hash: Option<&str>,
        temp_path: Option<&str>,
    ) -> Result<()> {
        self.connection.lock().execute(
            "update transfer_tasks set
                node_id = coalesce(?2, node_id),
                session_id = coalesce(?3, session_id),
                size_bytes = coalesce(?4, size_bytes),
                content_hash = coalesce(?5, content_hash),
                temp_path = coalesce(?6, temp_path),
                updated_at = ?7
             where id = ?1",
            params![
                task_id.to_string(),
                node_id.map(|value| value.to_string()),
                session_id.map(|value| value.to_string()),
                size_bytes,
                content_hash,
                temp_path,
                Utc::now().to_rfc3339(),
            ],
        )?;
        Ok(())
    }

    pub fn save_confirmed_part(&self, part: &ConfirmedPart) -> Result<()> {
        self.connection.lock().execute(
            "insert into transfer_parts(task_id, part_no, etag, size_bytes)
             values (?1, ?2, ?3, ?4)
             on conflict(task_id, part_no) do update set
                etag = excluded.etag,
                size_bytes = excluded.size_bytes",
            params![
                part.task_id.to_string(),
                part.part_no,
                part.etag,
                part.size_bytes
            ],
        )?;
        Ok(())
    }

    pub fn confirmed_parts(&self, task_id: Uuid) -> Result<Vec<ConfirmedPart>> {
        let connection = self.connection.lock();
        let mut statement = connection.prepare(
            "select task_id, part_no, etag, size_bytes
             from transfer_parts where task_id = ?1 order by part_no",
        )?;
        let rows = statement.query_map(params![task_id.to_string()], |row| {
            Ok(ConfirmedPart {
                task_id: parse_uuid(row.get::<_, String>(0)?)?,
                part_no: row.get(1)?,
                etag: row.get(2)?,
                size_bytes: row.get(3)?,
            })
        })?;
        rows.collect::<std::result::Result<Vec<_>, _>>()
            .map_err(IndexError::from)
    }

    pub fn recover_interrupted(&self) -> Result<usize> {
        let updated = self.connection.lock().execute(
            "update transfer_tasks set
                status = 'paused',
                error_code = 'PROCESS_INTERRUPTED',
                updated_at = ?1
             where status = 'running'",
            params![Utc::now().to_rfc3339()],
        )?;
        Ok(updated)
    }

    fn migrate(&self) -> Result<()> {
        let connection = self.connection.lock();
        connection.execute_batch(
            "pragma foreign_keys = on;
             pragma journal_mode = wal;
             create table if not exists metadata(
                key text primary key,
                value text not null
             );
             create table if not exists nodes(
                node_id text primary key,
                space_id text not null,
                parent_id text,
                node_type text not null,
                name text,
                current_version_id text,
                permission_version integer,
                tombstone integer not null,
                changed_at text not null
             );
             create index if not exists idx_nodes_parent
                on nodes(space_id, parent_id, tombstone);
             create table if not exists sync_roots(
                root_node_id text primary key,
                space_id text not null,
                local_path text not null,
                cursor text,
                enabled integer not null,
                updated_at text not null
             );
             create table if not exists operation_log(
                client_operation_id text primary key,
                action text not null,
                payload_json text not null,
                status text not null,
                error_code text,
                updated_at text not null
             );
             create table if not exists transfer_tasks(
                id text primary key,
                direction text not null,
                status text not null,
                local_path text not null,
                temp_path text,
                space_id text,
                parent_id text,
                node_id text,
                session_id text,
                size_bytes integer not null,
                transferred_bytes integer not null,
                content_hash text,
                client_operation_id text not null unique,
                error_code text,
                created_at text not null,
                updated_at text not null
             );
             create index if not exists idx_transfer_tasks_status
                on transfer_tasks(status, created_at);
             create table if not exists transfer_parts(
                task_id text not null,
                part_no integer not null,
                etag text not null,
                size_bytes integer not null,
                primary key(task_id, part_no),
                foreign key(task_id) references transfer_tasks(id) on delete cascade
             );
             pragma user_version = 1;",
        )?;
        Ok(())
    }
}

fn map_node(row: &rusqlite::Row<'_>) -> rusqlite::Result<IndexedNode> {
    Ok(IndexedNode {
        node_id: parse_uuid(row.get::<_, String>(0)?)?,
        space_id: parse_uuid(row.get::<_, String>(1)?)?,
        parent_id: parse_optional_uuid(row.get(2)?)?,
        node_type: row.get(3)?,
        name: row.get(4)?,
        current_version_id: parse_optional_uuid(row.get(5)?)?,
        permission_version: row.get(6)?,
        tombstone: row.get::<_, i32>(7)? != 0,
        changed_at: parse_timestamp(row.get::<_, String>(8)?)?,
    })
}

fn map_sync_root(row: &rusqlite::Row<'_>) -> rusqlite::Result<SyncRoot> {
    Ok(SyncRoot {
        root_node_id: parse_uuid(row.get::<_, String>(0)?)?,
        space_id: parse_uuid(row.get::<_, String>(1)?)?,
        local_path: row.get(2)?,
        cursor: row.get(3)?,
        enabled: row.get::<_, i32>(4)? != 0,
        updated_at: parse_timestamp(row.get::<_, String>(5)?)?,
    })
}

fn map_transfer(row: &rusqlite::Row<'_>) -> rusqlite::Result<TransferTask> {
    Ok(TransferTask {
        id: parse_uuid(row.get::<_, String>(0)?)?,
        direction: parse_direction(&row.get::<_, String>(1)?)?,
        status: parse_status(&row.get::<_, String>(2)?)?,
        local_path: row.get(3)?,
        temp_path: row.get(4)?,
        space_id: parse_optional_uuid(row.get(5)?)?,
        parent_id: parse_optional_uuid(row.get(6)?)?,
        node_id: parse_optional_uuid(row.get(7)?)?,
        session_id: parse_optional_uuid(row.get(8)?)?,
        size_bytes: row.get(9)?,
        transferred_bytes: row.get(10)?,
        content_hash: row.get(11)?,
        client_operation_id: row.get(12)?,
        error_code: row.get(13)?,
        created_at: parse_timestamp(row.get::<_, String>(14)?)?,
        updated_at: parse_timestamp(row.get::<_, String>(15)?)?,
    })
}

fn upsert_node_on(connection: &Connection, node: &IndexedNode) -> rusqlite::Result<usize> {
    connection.execute(
        "insert into nodes(
            node_id, space_id, parent_id, node_type, name, current_version_id,
            permission_version, tombstone, changed_at
         ) values (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)
         on conflict(node_id) do update set
            space_id = excluded.space_id,
            parent_id = excluded.parent_id,
            node_type = excluded.node_type,
            name = excluded.name,
            current_version_id = excluded.current_version_id,
            permission_version = excluded.permission_version,
            tombstone = excluded.tombstone,
            changed_at = excluded.changed_at",
        params![
            node.node_id.to_string(),
            node.space_id.to_string(),
            node.parent_id.map(|value| value.to_string()),
            node.node_type,
            node.name,
            node.current_version_id.map(|value| value.to_string()),
            node.permission_version,
            i32::from(node.tombstone),
            node.changed_at.to_rfc3339(),
        ],
    )
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

fn parse_direction(value: &str) -> rusqlite::Result<TransferDirection> {
    match value {
        "upload" => Ok(TransferDirection::Upload),
        "download" => Ok(TransferDirection::Download),
        other => Err(to_sql_conversion_error(IndexError::InvalidEnum(
            other.to_string(),
        ))),
    }
}

fn parse_status(value: &str) -> rusqlite::Result<TransferStatus> {
    match value {
        "queued" => Ok(TransferStatus::Queued),
        "running" => Ok(TransferStatus::Running),
        "paused" => Ok(TransferStatus::Paused),
        "completed" => Ok(TransferStatus::Completed),
        "cancelled" => Ok(TransferStatus::Cancelled),
        "failed" => Ok(TransferStatus::Failed),
        other => Err(to_sql_conversion_error(IndexError::InvalidEnum(
            other.to_string(),
        ))),
    }
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

    use super::LocalIndex;
    use crate::models::{SyncRoot, TransferDirection, TransferStatus, TransferTask};

    #[test]
    fn migration_cursor_and_crash_recovery_work() {
        let index = LocalIndex::open_in_memory().unwrap();
        let installation_id = index.installation_id().unwrap();
        assert_eq!(installation_id, index.installation_id().unwrap());

        let root = SyncRoot {
            root_node_id: Uuid::new_v4(),
            space_id: Uuid::new_v4(),
            local_path: "C:\\Drive".to_string(),
            cursor: Some("cursor-1".to_string()),
            enabled: true,
            updated_at: Utc::now(),
        };
        index.upsert_sync_root(&root).unwrap();
        index.save_cursor(root.root_node_id, "cursor-2").unwrap();
        assert_eq!(
            index
                .get_sync_root(root.root_node_id)
                .unwrap()
                .unwrap()
                .cursor
                .as_deref(),
            Some("cursor-2")
        );

        let now = Utc::now();
        let task = TransferTask {
            id: Uuid::new_v4(),
            direction: TransferDirection::Upload,
            status: TransferStatus::Running,
            local_path: "C:\\Drive\\large.bin".to_string(),
            temp_path: None,
            space_id: Some(root.space_id),
            parent_id: Some(root.root_node_id),
            node_id: None,
            session_id: None,
            size_bytes: 1_073_741_824,
            transferred_bytes: 0,
            content_hash: None,
            client_operation_id: Uuid::new_v4().to_string(),
            error_code: None,
            created_at: now,
            updated_at: now,
        };
        index.enqueue_transfer(&task).unwrap();
        assert_eq!(index.recover_interrupted().unwrap(), 1);
        let recovered = index.get_transfer(task.id).unwrap().unwrap();
        assert_eq!(recovered.status, TransferStatus::Paused);
        assert_eq!(recovered.error_code.as_deref(), Some("PROCESS_INTERRUPTED"));
    }
}
