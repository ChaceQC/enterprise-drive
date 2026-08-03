use serde::{Deserialize, Serialize};
use thiserror::Error;

pub type Result<T> = std::result::Result<T, ApiClientError>;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum KnownErrorCode {
    AuthInvalidCredentials,
    DeviceSessionInvalid,
    DeviceSessionRevoked,
    DeviceSessionExpired,
    DeviceSessionReused,
    SyncCursorInvalid,
    SyncCursorScopeMismatch,
    SyncCursorExpired,
    SyncPermissionRevoked,
    FileVersionConflict,
    ClientOperationIdReused,
    UploadPartInvalid,
    UploadPartSizeInvalid,
    Unknown(String),
}

impl KnownErrorCode {
    pub fn parse(code: &str) -> Self {
        match code {
            "AUTH_INVALID_CREDENTIALS" => Self::AuthInvalidCredentials,
            "DEVICE_SESSION_INVALID" => Self::DeviceSessionInvalid,
            "DEVICE_SESSION_REVOKED" => Self::DeviceSessionRevoked,
            "DEVICE_SESSION_EXPIRED" => Self::DeviceSessionExpired,
            "DEVICE_SESSION_REUSED" => Self::DeviceSessionReused,
            "SYNC_CURSOR_INVALID" => Self::SyncCursorInvalid,
            "SYNC_CURSOR_SCOPE_MISMATCH" => Self::SyncCursorScopeMismatch,
            "SYNC_CURSOR_EXPIRED" => Self::SyncCursorExpired,
            "SYNC_PERMISSION_REVOKED" => Self::SyncPermissionRevoked,
            "FILE_VERSION_CONFLICT" => Self::FileVersionConflict,
            "CLIENT_OPERATION_ID_REUSED" => Self::ClientOperationIdReused,
            "UPLOAD_PART_INVALID" => Self::UploadPartInvalid,
            "UPLOAD_PART_SIZE_INVALID" => Self::UploadPartSizeInvalid,
            other => Self::Unknown(other.to_string()),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ApiErrorPayload {
    pub code: String,
    pub message: String,
    pub request_id: Option<String>,
    pub details: Option<serde_json::Value>,
}

#[derive(Debug, Error)]
pub enum ApiClientError {
    #[error("HTTP transport failed: {0}")]
    Transport(#[from] reqwest::Error),
    #[error("invalid API base URL: {0}")]
    InvalidBaseUrl(#[from] url::ParseError),
    #[error("API returned {0}: {1}")]
    Api(String, String),
    #[error("device token is not available")]
    MissingDeviceToken,
    #[error("response decoding failed: {0}")]
    Decode(String),
}

impl ApiClientError {
    pub fn api_code(&self) -> Option<&str> {
        match self {
            Self::Api(code, _) => Some(code),
            _ => None,
        }
    }

    pub fn known_api_code(&self) -> Option<KnownErrorCode> {
        self.api_code().map(KnownErrorCode::parse)
    }
}

#[cfg(test)]
mod tests {
    use serde::Deserialize;

    use super::KnownErrorCode;

    #[derive(Deserialize)]
    struct Contract {
        required_error_codes: Vec<String>,
    }

    #[test]
    fn sprint7_contract_error_codes_are_mapped() {
        let contract: Contract =
            serde_json::from_str(include_str!("../../../contracts/sprint7-openapi.json")).unwrap();
        for code in contract.required_error_codes {
            assert!(
                !matches!(KnownErrorCode::parse(&code), KnownErrorCode::Unknown(_)),
                "missing Rust mapping for {code}"
            );
        }
    }
}
