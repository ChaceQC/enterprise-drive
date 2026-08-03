use std::sync::Arc;

use parking_lot::RwLock;
use reqwest::{header, Client, RequestBuilder};
use url::Url;
use uuid::Uuid;

use crate::error::{ApiClientError, ApiErrorPayload, Result};
use crate::types::{
    AbortUploadResponse, BatchPresignResponse, CompleteUploadRequest, CompleteUploadResponse,
    ConfirmUploadPartRequest, ConfirmUploadPartResponse, CreateFolderRequest, DeviceListResponse,
    DeviceRegisterRequest, DeviceRevokeResponse, DeviceRotateRequest, DeviceSessionResponse,
    DownloadUrlResponse, FileListResponse, InitUploadRequest, InitUploadResponse, MoveNodeRequest,
    RenameNodeRequest, SpaceListResponse, SyncChangeList, UploadSessionStatus,
};

#[derive(Clone)]
pub struct ApiClient {
    http: Client,
    base_url: Url,
    device_token: Arc<RwLock<Option<String>>>,
}

impl ApiClient {
    pub fn new(base_url: &str) -> Result<Self> {
        let mut parsed = Url::parse(base_url)?;
        if !parsed.path().ends_with('/') {
            parsed.set_path(&format!("{}/", parsed.path()));
        }
        Ok(Self {
            http: Client::builder()
                .user_agent("enterprise-drive-desktop/0.5.0")
                .build()?,
            base_url: parsed,
            device_token: Arc::new(RwLock::new(None)),
        })
    }

    pub fn http_client(&self) -> Client {
        self.http.clone()
    }

    pub fn set_device_token(&self, token: Option<String>) {
        *self.device_token.write() = token;
    }

    pub fn device_token(&self) -> Option<String> {
        self.device_token.read().clone()
    }

    pub async fn register_device(
        &self,
        request: &DeviceRegisterRequest,
    ) -> Result<DeviceSessionResponse> {
        self.send(
            self.http
                .post(self.url("device-sessions/register")?)
                .json(request),
        )
        .await
    }

    pub async fn rotate_device(
        &self,
        request: &DeviceRotateRequest,
    ) -> Result<DeviceSessionResponse> {
        self.send(
            self.authenticated(self.http.post(self.url("device-sessions/rotate")?))?
                .json(request),
        )
        .await
    }

    pub async fn list_devices(&self) -> Result<DeviceListResponse> {
        self.send(self.authenticated(self.http.get(self.url("device-sessions")?))?)
            .await
    }

    pub async fn revoke_device(&self, device_id: Uuid) -> Result<DeviceRevokeResponse> {
        self.send(
            self.authenticated(
                self.http
                    .delete(self.url(&format!("device-sessions/{device_id}"))?),
            )?,
        )
        .await
    }

    pub async fn revoke_all_devices(&self) -> Result<DeviceRevokeResponse> {
        self.send(self.authenticated(self.http.delete(self.url("device-sessions")?))?)
            .await
    }

    pub async fn list_spaces(&self, cursor: Option<&str>) -> Result<SpaceListResponse> {
        let mut request = self.authenticated(self.http.get(self.url("spaces")?))?;
        if let Some(cursor) = cursor {
            request = request.query(&[("cursor", cursor)]);
        }
        self.send(request).await
    }

    pub async fn list_files(
        &self,
        space_id: Uuid,
        parent_id: Option<Uuid>,
        cursor: Option<&str>,
    ) -> Result<FileListResponse> {
        self.list_files_page(space_id, parent_id, cursor, 100).await
    }

    pub async fn list_files_page(
        &self,
        space_id: Uuid,
        parent_id: Option<Uuid>,
        cursor: Option<&str>,
        page_size: i32,
    ) -> Result<FileListResponse> {
        let mut request = self
            .authenticated(self.http.get(self.url("files")?))?
            .query(&[
                ("space_id", space_id.to_string()),
                ("page_size", page_size.clamp(1, 100).to_string()),
            ]);
        if let Some(parent_id) = parent_id {
            request = request.query(&[("parent_id", parent_id.to_string())]);
        }
        if let Some(cursor) = cursor {
            request = request.query(&[("cursor", cursor)]);
        }
        self.send(request).await
    }

    pub async fn create_folder(
        &self,
        request: &CreateFolderRequest,
        operation_id: &str,
    ) -> Result<crate::types::FileNode> {
        self.send(
            self.authenticated(self.http.post(self.url("files/folders")?))?
                .header("X-Client-Operation-ID", operation_id)
                .json(request),
        )
        .await
    }

    pub async fn rename_node(
        &self,
        node_id: Uuid,
        request: &RenameNodeRequest,
        operation_id: &str,
    ) -> Result<crate::types::FileNode> {
        self.send(
            self.authenticated(self.http.patch(self.url(&format!("files/{node_id}"))?))?
                .header("X-Client-Operation-ID", operation_id)
                .json(request),
        )
        .await
    }

    pub async fn move_node(
        &self,
        node_id: Uuid,
        request: &MoveNodeRequest,
        operation_id: &str,
    ) -> Result<crate::types::FileNode> {
        self.send(
            self.authenticated(self.http.post(self.url(&format!("files/{node_id}/move"))?))?
                .header("X-Client-Operation-ID", operation_id)
                .json(request),
        )
        .await
    }

    pub async fn delete_node(
        &self,
        node_id: Uuid,
        expected_version_id: Option<Uuid>,
        operation_id: &str,
    ) -> Result<serde_json::Value> {
        let mut request = self
            .authenticated(self.http.delete(self.url(&format!("files/{node_id}"))?))?
            .header("X-Client-Operation-ID", operation_id);
        if let Some(version_id) = expected_version_id {
            request = request.header("X-Expected-Current-Version-ID", version_id.to_string());
        }
        self.send(request).await
    }

    pub async fn init_upload(
        &self,
        request: &InitUploadRequest,
        operation_id: &str,
    ) -> Result<InitUploadResponse> {
        self.send(
            self.authenticated(self.http.post(self.url("uploads/init")?))?
                .header("X-Client-Operation-ID", operation_id)
                .header("X-Drive-Transfer-Protocol", "DTP/1")
                .json(request),
        )
        .await
    }

    pub async fn upload_status(&self, session_id: Uuid) -> Result<UploadSessionStatus> {
        self.send(self.authenticated(self.http.get(self.url(&format!("uploads/{session_id}"))?))?)
            .await
    }

    pub async fn presign_parts(
        &self,
        session_id: Uuid,
        part_numbers: &[i32],
    ) -> Result<BatchPresignResponse> {
        self.send(
            self.authenticated(
                self.http
                    .post(self.url(&format!("uploads/{session_id}/parts/presign"))?),
            )?
            .header("X-Drive-Transfer-Protocol", "DTP/1")
            .json(&serde_json::json!({ "part_numbers": part_numbers })),
        )
        .await
    }

    pub async fn confirm_part(
        &self,
        session_id: Uuid,
        part_no: i32,
        request: &ConfirmUploadPartRequest,
    ) -> Result<ConfirmUploadPartResponse> {
        self.send(
            self.authenticated(
                self.http
                    .post(self.url(&format!("uploads/{session_id}/parts/{part_no}/confirm"))?),
            )?
            .header("X-Drive-Transfer-Protocol", "DTP/1")
            .json(request),
        )
        .await
    }

    pub async fn complete_upload(
        &self,
        session_id: Uuid,
        request: &CompleteUploadRequest,
        operation_id: &str,
    ) -> Result<CompleteUploadResponse> {
        self.send(
            self.authenticated(
                self.http
                    .post(self.url(&format!("uploads/{session_id}/complete"))?),
            )?
            .header("X-Client-Operation-ID", operation_id)
            .header("X-Drive-Transfer-Protocol", "DTP/1")
            .json(request),
        )
        .await
    }

    pub async fn abort_upload(
        &self,
        session_id: Uuid,
        operation_id: &str,
    ) -> Result<AbortUploadResponse> {
        self.send(
            self.authenticated(
                self.http
                    .post(self.url(&format!("uploads/{session_id}/abort"))?),
            )?
            .header("X-Client-Operation-ID", operation_id)
            .header("X-Drive-Transfer-Protocol", "DTP/1"),
        )
        .await
    }

    pub async fn download_url(&self, node_id: Uuid) -> Result<DownloadUrlResponse> {
        self.send(
            self.authenticated(
                self.http
                    .get(self.url(&format!("files/{node_id}/download"))?),
            )?
            .header("X-Drive-Transfer-Protocol", "DTP/1"),
        )
        .await
    }

    pub async fn sync_changes(
        &self,
        space_id: Uuid,
        root_node_id: Uuid,
        cursor: Option<&str>,
        page_size: i32,
    ) -> Result<SyncChangeList> {
        let mut request = self
            .authenticated(self.http.get(self.url("sync/changes")?))?
            .query(&[
                ("space_id", space_id.to_string()),
                ("root_node_id", root_node_id.to_string()),
                ("page_size", page_size.to_string()),
            ]);
        if let Some(cursor) = cursor {
            request = request.query(&[("cursor", cursor)]);
        }
        self.send(request).await
    }

    async fn send<T: serde::de::DeserializeOwned>(&self, request: RequestBuilder) -> Result<T> {
        let response = request.send().await?;
        let status = response.status();
        if status.is_success() {
            return response
                .json::<T>()
                .await
                .map_err(|error| ApiClientError::Decode(error.to_string()));
        }
        let payload = response
            .json::<ApiErrorPayload>()
            .await
            .unwrap_or(ApiErrorPayload {
                code: format!("HTTP_{}", status.as_u16()),
                message: "API request failed".to_string(),
                request_id: None,
                details: None,
            });
        Err(ApiClientError::Api(payload.code, payload.message))
    }

    fn authenticated(&self, request: RequestBuilder) -> Result<RequestBuilder> {
        let token = self
            .device_token
            .read()
            .clone()
            .ok_or(ApiClientError::MissingDeviceToken)?;
        Ok(request.header(header::AUTHORIZATION, format!("Device {token}")))
    }

    fn url(&self, path: &str) -> Result<Url> {
        Ok(self.base_url.join(path)?)
    }
}

#[cfg(test)]
mod tests {
    use super::ApiClient;

    #[test]
    fn base_url_is_normalized() {
        let client = ApiClient::new("https://drive.example.com/api/v1").unwrap();
        assert_eq!(
            client.base_url.as_str(),
            "https://drive.example.com/api/v1/"
        );
    }
}
