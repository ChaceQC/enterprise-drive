use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use directories::ProjectDirs;
use parking_lot::RwLock;
use thiserror::Error;

pub type Result<T> = std::result::Result<T, PlatformError>;

#[derive(Debug, Error)]
pub enum PlatformError {
    #[error("the application data directory is unavailable")]
    ApplicationDataDirectoryUnavailable,
    #[error("credential store operation failed: {0}")]
    Credential(String),
    #[error("system credential storage is only available on Windows")]
    UnsupportedCredentialStore,
    #[error("sync root must be an absolute directory")]
    SyncRootNotAbsolute,
    #[error("sync root does not exist or is not a directory")]
    SyncRootNotDirectory,
    #[error("sync root may not be a symbolic link, junction, or reparse point")]
    SyncRootIsReparsePoint,
    #[error("sync root inspection failed: {0}")]
    SyncRootIo(#[from] std::io::Error),
}

pub trait CredentialStore: Send + Sync {
    fn set_secret(&self, account: &str, secret: &str) -> Result<()>;
    fn get_secret(&self, account: &str) -> Result<Option<String>>;
    fn delete_secret(&self, account: &str) -> Result<()>;
}

#[derive(Clone, Default)]
pub struct MemoryCredentialStore {
    values: Arc<RwLock<HashMap<String, String>>>,
}

impl CredentialStore for MemoryCredentialStore {
    fn set_secret(&self, account: &str, secret: &str) -> Result<()> {
        self.values
            .write()
            .insert(account.to_string(), secret.to_string());
        Ok(())
    }

    fn get_secret(&self, account: &str) -> Result<Option<String>> {
        Ok(self.values.read().get(account).cloned())
    }

    fn delete_secret(&self, account: &str) -> Result<()> {
        self.values.write().remove(account);
        Ok(())
    }
}

#[derive(Debug, Clone)]
pub struct SystemCredentialStore {
    service: String,
}

impl SystemCredentialStore {
    pub fn new(service: impl Into<String>) -> Self {
        Self {
            service: service.into(),
        }
    }
}

#[cfg(windows)]
impl CredentialStore for SystemCredentialStore {
    fn set_secret(&self, account: &str, secret: &str) -> Result<()> {
        keyring::Entry::new(&self.service, account)
            .and_then(|entry| entry.set_password(secret))
            .map_err(|error| PlatformError::Credential(error.to_string()))
    }

    fn get_secret(&self, account: &str) -> Result<Option<String>> {
        let entry = keyring::Entry::new(&self.service, account)
            .map_err(|error| PlatformError::Credential(error.to_string()))?;
        match entry.get_password() {
            Ok(secret) => Ok(Some(secret)),
            Err(keyring::Error::NoEntry) => Ok(None),
            Err(error) => Err(PlatformError::Credential(error.to_string())),
        }
    }

    fn delete_secret(&self, account: &str) -> Result<()> {
        let entry = keyring::Entry::new(&self.service, account)
            .map_err(|error| PlatformError::Credential(error.to_string()))?;
        match entry.delete_credential() {
            Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
            Err(error) => Err(PlatformError::Credential(error.to_string())),
        }
    }
}

#[cfg(not(windows))]
impl CredentialStore for SystemCredentialStore {
    fn set_secret(&self, _account: &str, _secret: &str) -> Result<()> {
        Err(PlatformError::UnsupportedCredentialStore)
    }

    fn get_secret(&self, _account: &str) -> Result<Option<String>> {
        Err(PlatformError::UnsupportedCredentialStore)
    }

    fn delete_secret(&self, _account: &str) -> Result<()> {
        Err(PlatformError::UnsupportedCredentialStore)
    }
}

pub fn application_data_dir() -> Result<PathBuf> {
    ProjectDirs::from("com", "ChaceQC", "EnterpriseDrive")
        .map(|directories| directories.data_local_dir().to_path_buf())
        .ok_or(PlatformError::ApplicationDataDirectoryUnavailable)
}

pub fn validate_sync_root(path: impl AsRef<Path>) -> Result<PathBuf> {
    let path = path.as_ref();
    if !path.is_absolute() {
        return Err(PlatformError::SyncRootNotAbsolute);
    }
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.is_dir() {
        return Err(PlatformError::SyncRootNotDirectory);
    }
    if metadata.file_type().is_symlink() || is_reparse_point(&metadata) {
        return Err(PlatformError::SyncRootIsReparsePoint);
    }
    Ok(path.canonicalize()?)
}

#[cfg(windows)]
fn is_reparse_point(metadata: &std::fs::Metadata) -> bool {
    use std::os::windows::fs::MetadataExt;

    const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x0400;
    metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0
}

#[cfg(not(windows))]
fn is_reparse_point(_metadata: &std::fs::Metadata) -> bool {
    false
}

#[cfg(test)]
mod tests {
    use super::{validate_sync_root, CredentialStore, MemoryCredentialStore};

    #[test]
    fn memory_store_round_trip_does_not_touch_files() {
        let store = MemoryCredentialStore::default();
        store.set_secret("installation", "secret-token").unwrap();
        assert_eq!(
            store.get_secret("installation").unwrap().as_deref(),
            Some("secret-token")
        );
        store.delete_secret("installation").unwrap();
        assert_eq!(store.get_secret("installation").unwrap(), None);
    }

    #[test]
    fn sync_root_is_canonicalized() {
        let directory = tempfile::tempdir().unwrap();
        assert_eq!(
            validate_sync_root(directory.path()).unwrap(),
            directory.path().canonicalize().unwrap()
        );
    }
}
