use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UserProfile {
    pub id: Uuid,
    pub tenant_id: Uuid,
    pub username: String,
    pub email: Option<String>,
    pub display_name: String,
    pub is_super_admin: bool,
    pub must_change_password: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DeviceRegisterRequest {
    pub tenant_slug: String,
    pub username: String,
    pub password: String,
    pub installation_id: Uuid,
    pub device_name: String,
    pub platform: String,
    pub client_version: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DeviceRotateRequest {
    pub client_version: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Device {
    pub id: Uuid,
    pub name: String,
    pub platform: String,
    pub client_version: String,
    pub status: String,
    pub current: bool,
    pub last_seen_at: DateTime<Utc>,
    pub revoked_at: Option<DateTime<Utc>>,
    pub revoked_reason: Option<String>,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DeviceSessionResponse {
    pub token_type: String,
    pub access_token: String,
    pub expires_at: DateTime<Utc>,
    pub device: Device,
    pub user: UserProfile,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DeviceListResponse {
    pub items: Vec<Device>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DeviceRevokeResponse {
    pub revoked_device_ids: Vec<Uuid>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Space {
    pub id: Uuid,
    pub tenant_id: Uuid,
    pub owner_id: Uuid,
    pub slug: String,
    pub name: String,
    pub space_type: String,
    pub is_active: bool,
    pub version: i32,
    pub permission_version: i32,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SpaceListResponse {
    pub items: Vec<Space>,
    pub next_cursor: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileNode {
    pub id: Uuid,
    pub tenant_id: Uuid,
    pub space_id: Uuid,
    pub parent_id: Option<Uuid>,
    pub node_type: String,
    pub name: String,
    pub current_version_id: Option<Uuid>,
    pub permission_version: i32,
    pub permissions: std::collections::HashMap<String, bool>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileListResponse {
    pub space_id: Uuid,
    pub parent_id: Uuid,
    pub items: Vec<FileNode>,
    pub next_cursor: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CreateFolderRequest {
    pub space_id: Uuid,
    pub parent_id: Option<Uuid>,
    pub name: String,
    pub conflict_policy: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RenameNodeRequest {
    pub name: String,
    pub expected_current_version_id: Option<Uuid>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MoveNodeRequest {
    pub target_parent_id: Uuid,
    pub new_name: Option<String>,
    pub conflict_policy: String,
    pub expected_current_version_id: Option<Uuid>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InitUploadRequest {
    pub space_id: Uuid,
    pub parent_id: Uuid,
    pub file_name: String,
    pub size_bytes: i64,
    pub content_hash: String,
    pub hash_algo: String,
    pub mime_type: Option<String>,
    pub conflict_policy: String,
    pub target_node_id: Option<Uuid>,
    pub expected_current_version_id: Option<Uuid>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "mode")]
pub enum InitUploadResponse {
    #[serde(rename = "instant")]
    Instant {
        protocol_version: String,
        client_operation_id: Option<String>,
        node_id: Uuid,
        version_id: Uuid,
        blob_id: Uuid,
    },
    #[serde(rename = "multipart")]
    Multipart {
        protocol_version: String,
        client_operation_id: Option<String>,
        session_id: Uuid,
        part_size_bytes: i64,
        total_parts: i32,
        max_parallelism: i32,
        checksum_algorithm: String,
        expires_at: DateTime<Utc>,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UploadSessionStatus {
    pub protocol_version: String,
    pub client_operation_id: Option<String>,
    pub session_id: Uuid,
    pub status: String,
    pub file_name: String,
    pub size_bytes: i64,
    pub part_size_bytes: i64,
    pub total_parts: i32,
    pub max_parallelism: i32,
    pub checksum_algorithm: String,
    pub uploaded_parts: Vec<i32>,
    pub expires_at: DateTime<Utc>,
    pub completed_node_id: Option<Uuid>,
    pub completed_version_id: Option<Uuid>,
    pub target_node_id: Option<Uuid>,
    pub expected_current_version_id: Option<Uuid>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UploadPartUrl {
    pub protocol_version: String,
    pub client_operation_id: Option<String>,
    pub part_no: i32,
    pub upload_url: String,
    pub expires_at: DateTime<Utc>,
    pub headers: std::collections::HashMap<String, String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BatchPresignResponse {
    pub protocol_version: String,
    pub client_operation_id: Option<String>,
    pub session_id: Uuid,
    pub max_parallelism: i32,
    pub items: Vec<UploadPartUrl>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConfirmUploadPartRequest {
    pub etag: String,
    pub size_bytes: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConfirmUploadPartResponse {
    pub protocol_version: String,
    pub client_operation_id: Option<String>,
    pub session_id: Uuid,
    pub part_no: i32,
    pub uploaded_parts: Vec<i32>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CompleteUploadPart {
    pub part_no: i32,
    pub etag: String,
    pub size_bytes: Option<i64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CompleteUploadRequest {
    pub parts: Vec<CompleteUploadPart>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CompleteUploadResponse {
    pub protocol_version: String,
    pub client_operation_id: Option<String>,
    pub session_id: Uuid,
    pub status: String,
    pub node_id: Uuid,
    pub version_id: Uuid,
    pub blob_id: Uuid,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AbortUploadResponse {
    pub protocol_version: String,
    pub client_operation_id: Option<String>,
    pub session_id: Uuid,
    pub status: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DownloadUrlResponse {
    pub protocol_version: String,
    pub client_operation_id: Option<String>,
    pub node_id: Uuid,
    pub version_id: Uuid,
    pub file_name: String,
    pub size_bytes: i64,
    pub hash_algo: String,
    pub content_hash: String,
    pub mime_type: Option<String>,
    pub download_url: String,
    pub expires_at: DateTime<Utc>,
    pub headers: std::collections::HashMap<String, String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SyncChange {
    pub sequence: i64,
    pub change_type: String,
    pub node_id: Uuid,
    pub space_id: Uuid,
    pub parent_id: Option<Uuid>,
    pub node_type: Option<String>,
    pub name: Option<String>,
    pub current_version_id: Option<Uuid>,
    pub permission_version: Option<i32>,
    pub tombstone: bool,
    pub client_operation_id: Option<String>,
    pub changed_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SyncChangeList {
    pub space_id: Uuid,
    pub root_node_id: Uuid,
    pub items: Vec<SyncChange>,
    pub next_cursor: String,
    pub has_more: bool,
    pub cursor_expires_at: DateTime<Utc>,
}
