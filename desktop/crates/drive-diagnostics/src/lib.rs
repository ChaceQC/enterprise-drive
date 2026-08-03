use std::path::{Path, PathBuf};

use chrono::{DateTime, Utc};
use drive_local_index::{
    IndexError, LocalIndex, PendingOperation, SyncConflict, SyncEntry, TransferTask,
};
use serde::Serialize;
use thiserror::Error;
use uuid::Uuid;

pub type Result<T> = std::result::Result<T, DiagnosticsError>;

#[derive(Debug, Error)]
pub enum DiagnosticsError {
    #[error(transparent)]
    Index(#[from] IndexError),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
}

#[derive(Debug, Serialize)]
struct DiagnosticsBundle {
    generated_at: DateTime<Utc>,
    application_version: &'static str,
    operating_system: &'static str,
    architecture: &'static str,
    sync_roots: Vec<DiagnosticSyncRoot>,
    sync_entries: Vec<DiagnosticSyncEntry>,
    pending_operations: Vec<DiagnosticOperation>,
    conflicts: Vec<DiagnosticConflict>,
    transfers: Vec<DiagnosticTransfer>,
    recent_messages: Vec<String>,
}

#[derive(Debug, Serialize)]
struct DiagnosticSyncRoot {
    root_node_id: Uuid,
    space_id: Uuid,
    local_path: String,
    has_cursor: bool,
    enabled: bool,
    updated_at: DateTime<Utc>,
}

#[derive(Debug, Serialize)]
struct DiagnosticTransfer {
    id: Uuid,
    direction: String,
    status: String,
    local_path: String,
    node_id: Option<Uuid>,
    session_id: Option<Uuid>,
    size_bytes: i64,
    transferred_bytes: i64,
    error_code: Option<String>,
    updated_at: DateTime<Utc>,
}

#[derive(Debug, Serialize)]
struct DiagnosticSyncEntry {
    root_node_id: Uuid,
    node_id: Option<Uuid>,
    relative_path: String,
    kind: String,
    status: String,
    current_version_id: Option<Uuid>,
    size_bytes: i64,
    error_code: Option<String>,
    updated_at: DateTime<Utc>,
}

#[derive(Debug, Serialize)]
struct DiagnosticOperation {
    id: Uuid,
    root_node_id: Uuid,
    action: String,
    relative_path: String,
    status: String,
    retry_count: u32,
    error_code: Option<String>,
    updated_at: DateTime<Utc>,
}

#[derive(Debug, Serialize)]
struct DiagnosticConflict {
    id: Uuid,
    root_node_id: Uuid,
    node_id: Option<Uuid>,
    kind: String,
    original_relative_path: String,
    conflict_relative_path: Option<String>,
    detected_at: DateTime<Utc>,
}

#[derive(Clone)]
pub struct DiagnosticsExporter {
    index: LocalIndex,
}

impl DiagnosticsExporter {
    pub fn new(index: LocalIndex) -> Self {
        Self { index }
    }

    pub fn export(
        &self,
        destination: impl AsRef<Path>,
        recent_messages: &[String],
    ) -> Result<PathBuf> {
        let destination = destination.as_ref();
        if let Some(parent) = destination.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let roots = self.index.list_sync_roots()?;
        let sync_entries = roots
            .iter()
            .flat_map(|root| {
                self.index
                    .list_sync_entries(root.root_node_id)
                    .unwrap_or_default()
            })
            .map(redact_sync_entry)
            .collect();
        let pending_operations = roots
            .iter()
            .flat_map(|root| {
                self.index
                    .list_operations(root.root_node_id)
                    .unwrap_or_default()
            })
            .map(redact_operation)
            .collect();
        let conflicts = roots
            .iter()
            .flat_map(|root| {
                self.index
                    .list_conflicts(root.root_node_id)
                    .unwrap_or_default()
            })
            .map(redact_conflict)
            .collect();
        let sync_roots = roots
            .into_iter()
            .map(|root| DiagnosticSyncRoot {
                root_node_id: root.root_node_id,
                space_id: root.space_id,
                local_path: redact_path(Path::new(&root.local_path)),
                has_cursor: root.cursor.is_some(),
                enabled: root.enabled,
                updated_at: root.updated_at,
            })
            .collect();
        let transfers = self
            .index
            .list_transfers()?
            .into_iter()
            .map(redact_transfer)
            .collect();
        let recent_messages = recent_messages
            .iter()
            .map(|message| redact_message(message))
            .collect();
        let bundle = DiagnosticsBundle {
            generated_at: Utc::now(),
            application_version: env!("CARGO_PKG_VERSION"),
            operating_system: std::env::consts::OS,
            architecture: std::env::consts::ARCH,
            sync_roots,
            sync_entries,
            pending_operations,
            conflicts,
            transfers,
            recent_messages,
        };
        let payload = serde_json::to_vec_pretty(&bundle)?;
        std::fs::write(destination, payload)?;
        Ok(destination.to_path_buf())
    }
}

fn redact_sync_entry(entry: SyncEntry) -> DiagnosticSyncEntry {
    DiagnosticSyncEntry {
        root_node_id: entry.root_node_id,
        node_id: entry.node_id,
        relative_path: redact_path(Path::new(&entry.relative_path)),
        kind: entry.kind.as_str().to_string(),
        status: entry.status.as_str().to_string(),
        current_version_id: entry.current_version_id,
        size_bytes: entry.size_bytes,
        error_code: entry.last_error_code,
        updated_at: entry.updated_at,
    }
}

fn redact_operation(operation: PendingOperation) -> DiagnosticOperation {
    DiagnosticOperation {
        id: operation.id,
        root_node_id: operation.root_node_id,
        action: operation.action.as_str().to_string(),
        relative_path: redact_path(Path::new(&operation.relative_path)),
        status: operation.status.as_str().to_string(),
        retry_count: operation.retry_count,
        error_code: operation.error_code,
        updated_at: operation.updated_at,
    }
}

fn redact_conflict(conflict: SyncConflict) -> DiagnosticConflict {
    DiagnosticConflict {
        id: conflict.id,
        root_node_id: conflict.root_node_id,
        node_id: conflict.node_id,
        kind: conflict.kind,
        original_relative_path: redact_path(Path::new(&conflict.original_relative_path)),
        conflict_relative_path: conflict
            .conflict_relative_path
            .map(|path| redact_path(Path::new(&path))),
        detected_at: conflict.detected_at,
    }
}

fn redact_transfer(task: TransferTask) -> DiagnosticTransfer {
    DiagnosticTransfer {
        id: task.id,
        direction: task.direction.as_str().to_string(),
        status: task.status.as_str().to_string(),
        local_path: redact_path(Path::new(&task.local_path)),
        node_id: task.node_id,
        session_id: task.session_id,
        size_bytes: task.size_bytes,
        transferred_bytes: task.transferred_bytes,
        error_code: task.error_code,
        updated_at: task.updated_at,
    }
}

fn redact_path(path: &Path) -> String {
    path.file_name()
        .and_then(|value| value.to_str())
        .map(|name| format!("<redacted>/{name}"))
        .unwrap_or_else(|| "<redacted>".to_string())
}

fn redact_message(message: &str) -> String {
    let lowercase = message.to_ascii_lowercase();
    if [
        "authorization",
        "access_token",
        "password",
        "cookie",
        "device ",
    ]
    .iter()
    .any(|marker| lowercase.contains(marker))
    {
        "<redacted sensitive message>".to_string()
    } else {
        message.to_string()
    }
}

#[cfg(test)]
mod tests {
    use drive_local_index::{LocalIndex, TransferDirection, TransferStatus, TransferTask};
    use uuid::Uuid;

    use super::DiagnosticsExporter;

    #[test]
    fn export_redacts_paths_and_authentication_material() {
        let index = LocalIndex::open_in_memory().unwrap();
        let now = chrono::Utc::now();
        index
            .enqueue_transfer(&TransferTask {
                id: Uuid::new_v4(),
                root_node_id: None,
                direction: TransferDirection::Download,
                status: TransferStatus::Failed,
                local_path: "C:\\Users\\alice\\secret.txt".to_string(),
                temp_path: None,
                space_id: None,
                parent_id: None,
                node_id: Some(Uuid::new_v4()),
                expected_current_version_id: None,
                current_version_id: None,
                session_id: None,
                size_bytes: 10,
                transferred_bytes: 4,
                content_hash: None,
                client_operation_id: Uuid::new_v4().to_string(),
                retry_count: 0,
                next_attempt_at: None,
                error_code: Some("NETWORK_ERROR".to_string()),
                created_at: now,
                updated_at: now,
            })
            .unwrap();
        let directory = tempfile::tempdir().unwrap();
        let destination = directory.path().join("diagnostics.json");
        DiagnosticsExporter::new(index)
            .export(
                &destination,
                &["Authorization: Device opaque-secret".to_string()],
            )
            .unwrap();
        let payload = std::fs::read_to_string(destination).unwrap();
        assert!(!payload.contains("opaque-secret"));
        assert!(!payload.contains("alice"));
        assert!(payload.contains("<redacted>"));
    }
}
