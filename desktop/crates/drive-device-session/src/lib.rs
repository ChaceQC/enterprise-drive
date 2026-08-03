use std::sync::Arc;

use drive_api_client::{
    ApiClient, ApiClientError, DeviceListResponse, DeviceRegisterRequest, DeviceRevokeResponse,
    DeviceRotateRequest, DeviceSessionResponse, KnownErrorCode,
};
use drive_platform::{CredentialStore, PlatformError};
use thiserror::Error;
use uuid::Uuid;

pub type Result<T> = std::result::Result<T, DeviceSessionError>;

#[derive(Debug, Error)]
pub enum DeviceSessionError {
    #[error(transparent)]
    Api(#[from] ApiClientError),
    #[error(transparent)]
    Platform(#[from] PlatformError),
}

#[derive(Clone)]
pub struct DeviceSessionManager {
    api: ApiClient,
    credentials: Arc<dyn CredentialStore>,
    credential_account: String,
}

impl DeviceSessionManager {
    pub fn new(
        api: ApiClient,
        credentials: Arc<dyn CredentialStore>,
        installation_id: Uuid,
    ) -> Self {
        Self {
            api,
            credentials,
            credential_account: format!("device-session:{installation_id}"),
        }
    }

    pub fn api_client(&self) -> ApiClient {
        self.api.clone()
    }

    pub fn restore(&self) -> Result<bool> {
        let token = self.credentials.get_secret(&self.credential_account)?;
        self.api.set_device_token(token.clone());
        Ok(token.is_some())
    }

    pub async fn register(&self, request: &DeviceRegisterRequest) -> Result<DeviceSessionResponse> {
        let response = self.api.register_device(request).await?;
        self.persist_token(&response.access_token)?;
        Ok(response)
    }

    pub async fn rotate(&self, client_version: Option<String>) -> Result<DeviceSessionResponse> {
        let result = self
            .api
            .rotate_device(&DeviceRotateRequest { client_version })
            .await;
        match result {
            Ok(response) => {
                self.persist_token(&response.access_token)?;
                Ok(response)
            }
            Err(error) => {
                if matches!(
                    error.known_api_code(),
                    Some(
                        KnownErrorCode::DeviceSessionInvalid
                            | KnownErrorCode::DeviceSessionRevoked
                            | KnownErrorCode::DeviceSessionExpired
                            | KnownErrorCode::DeviceSessionReused
                    )
                ) {
                    self.clear()?;
                }
                Err(error.into())
            }
        }
    }

    pub async fn list_devices(&self) -> Result<DeviceListResponse> {
        Ok(self.api.list_devices().await?)
    }

    pub async fn revoke_device(&self, device_id: Uuid) -> Result<DeviceRevokeResponse> {
        let revokes_current = self
            .api
            .list_devices()
            .await?
            .items
            .into_iter()
            .any(|device| device.current && device.id == device_id);
        let response = self.api.revoke_device(device_id).await?;
        if revokes_current && response.revoked_device_ids.contains(&device_id) {
            self.clear()?;
        }
        Ok(response)
    }

    pub async fn revoke_all(&self) -> Result<DeviceRevokeResponse> {
        let response = self.api.revoke_all_devices().await?;
        self.clear()?;
        Ok(response)
    }

    pub fn clear(&self) -> Result<()> {
        self.credentials.delete_secret(&self.credential_account)?;
        self.api.set_device_token(None);
        Ok(())
    }

    fn persist_token(&self, token: &str) -> Result<()> {
        self.credentials
            .set_secret(&self.credential_account, token)?;
        self.api.set_device_token(Some(token.to_string()));
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use drive_api_client::ApiClient;
    use drive_platform::{CredentialStore, MemoryCredentialStore};
    use uuid::Uuid;

    use super::DeviceSessionManager;

    #[test]
    fn restore_and_clear_only_use_the_credential_store() {
        let api = ApiClient::new("https://drive.example.com/api/v1").unwrap();
        let credentials = Arc::new(MemoryCredentialStore::default());
        let installation_id = Uuid::new_v4();
        let account = format!("device-session:{installation_id}");
        credentials.set_secret(&account, "opaque-secret").unwrap();

        let manager = DeviceSessionManager::new(api.clone(), credentials.clone(), installation_id);
        assert!(manager.restore().unwrap());
        assert_eq!(api.device_token().as_deref(), Some("opaque-secret"));

        manager.clear().unwrap();
        assert_eq!(api.device_token(), None);
        assert_eq!(credentials.get_secret(&account).unwrap(), None);
    }
}
