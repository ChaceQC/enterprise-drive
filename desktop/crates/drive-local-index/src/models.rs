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
    pub direction: TransferDirection,
    pub status: TransferStatus,
    pub local_path: String,
    pub temp_path: Option<String>,
    pub space_id: Option<Uuid>,
    pub parent_id: Option<Uuid>,
    pub node_id: Option<Uuid>,
    pub session_id: Option<Uuid>,
    pub size_bytes: i64,
    pub transferred_bytes: i64,
    pub content_hash: Option<String>,
    pub client_operation_id: String,
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
