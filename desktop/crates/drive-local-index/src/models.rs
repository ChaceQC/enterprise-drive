use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct IndexedNode {
    pub node_id: Uuid,
    pub space_id: Uuid,
    pub parent_id: Option<Uuid>,
    pub node_type: String,
    pub name: Option<String>,
    pub current_version_id: Option<Uuid>,
    pub permission_version: Option<i32>,
    pub tombstone: bool,
    pub changed_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SyncRoot {
    pub root_node_id: Uuid,
    pub space_id: Uuid,
    pub local_path: String,
    pub cursor: Option<String>,
    pub enabled: bool,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SyncPolicy {
    pub root_node_id: Uuid,
    pub device_name: String,
    pub include_patterns: Vec<String>,
    pub ignore_patterns: Vec<String>,
    pub bandwidth_limit_bps: Option<u64>,
    pub max_concurrent_transfers: usize,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum SyncEntryKind {
    File,
    Folder,
}

impl SyncEntryKind {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::File => "file",
            Self::Folder => "folder",
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum SyncEntryStatus {
    Synced,
    LocalPending,
    RemotePending,
    Conflict,
    Ignored,
    Error,
    PermissionRevoked,
}

impl SyncEntryStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Synced => "synced",
            Self::LocalPending => "local_pending",
            Self::RemotePending => "remote_pending",
            Self::Conflict => "conflict",
            Self::Ignored => "ignored",
            Self::Error => "error",
            Self::PermissionRevoked => "permission_revoked",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SyncEntry {
    pub root_node_id: Uuid,
    pub node_id: Option<Uuid>,
    pub relative_path: String,
    pub kind: SyncEntryKind,
    pub current_version_id: Option<Uuid>,
    pub content_hash: Option<String>,
    pub size_bytes: i64,
    pub local_modified_ns: Option<i64>,
    pub status: SyncEntryStatus,
    pub last_error_code: Option<String>,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum PendingOperationAction {
    CreateFolder,
    UploadFile,
    Rename,
    Move,
    Delete,
}

impl PendingOperationAction {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::CreateFolder => "create_folder",
            Self::UploadFile => "upload_file",
            Self::Rename => "rename",
            Self::Move => "move",
            Self::Delete => "delete",
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum PendingOperationStatus {
    Queued,
    Running,
    Retrying,
    Completed,
    Conflict,
    Failed,
}

impl PendingOperationStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Queued => "queued",
            Self::Running => "running",
            Self::Retrying => "retrying",
            Self::Completed => "completed",
            Self::Conflict => "conflict",
            Self::Failed => "failed",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct PendingOperation {
    pub id: Uuid,
    pub root_node_id: Uuid,
    pub client_operation_id: String,
    pub action: PendingOperationAction,
    pub relative_path: String,
    pub source_relative_path: Option<String>,
    pub node_id: Option<Uuid>,
    pub parent_node_id: Option<Uuid>,
    pub expected_current_version_id: Option<Uuid>,
    pub payload_json: String,
    pub status: PendingOperationStatus,
    pub retry_count: u32,
    pub next_attempt_at: Option<DateTime<Utc>>,
    pub error_code: Option<String>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SyncConflict {
    pub id: Uuid,
    pub root_node_id: Uuid,
    pub node_id: Option<Uuid>,
    pub kind: String,
    pub original_relative_path: String,
    pub conflict_relative_path: Option<String>,
    pub device_name: String,
    pub details_json: String,
    pub detected_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum TransferDirection {
    Upload,
    Download,
}

impl TransferDirection {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Upload => "upload",
            Self::Download => "download",
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum TransferStatus {
    Queued,
    Running,
    Paused,
    Completed,
    Cancelled,
    Failed,
}

impl TransferStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Queued => "queued",
            Self::Running => "running",
            Self::Paused => "paused",
            Self::Completed => "completed",
            Self::Cancelled => "cancelled",
            Self::Failed => "failed",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct TransferTask {
    pub id: Uuid,
    pub root_node_id: Option<Uuid>,
    pub direction: TransferDirection,
    pub status: TransferStatus,
    pub local_path: String,
    pub temp_path: Option<String>,
    pub space_id: Option<Uuid>,
    pub parent_id: Option<Uuid>,
    pub node_id: Option<Uuid>,
    pub expected_current_version_id: Option<Uuid>,
    pub current_version_id: Option<Uuid>,
    pub session_id: Option<Uuid>,
    pub size_bytes: i64,
    pub transferred_bytes: i64,
    pub content_hash: Option<String>,
    pub client_operation_id: String,
    pub retry_count: u32,
    pub next_attempt_at: Option<DateTime<Utc>>,
    pub error_code: Option<String>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ConfirmedPart {
    pub task_id: Uuid,
    pub part_no: i32,
    pub etag: String,
    pub size_bytes: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct OperationLogEntry {
    pub client_operation_id: String,
    pub action: String,
    pub payload_json: String,
    pub status: String,
    pub error_code: Option<String>,
    pub updated_at: DateTime<Utc>,
}
