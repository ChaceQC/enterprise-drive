use std::collections::HashMap;
use std::path::Component;
use std::path::{Path, PathBuf};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError, TryRecvError};
use std::sync::Arc;
use std::time::{Duration, SystemTime};

use chrono::{DateTime, Utc};
use directories::ProjectDirs;
use globset::{Glob, GlobSet, GlobSetBuilder};
use notify::event::{ModifyKind, RenameMode};
use notify::{Config, Event, EventKind, RecommendedWatcher, RecursiveMode, Watcher};
use parking_lot::RwLock;
use serde::{Deserialize, Serialize};
use thiserror::Error;
use unicode_normalization::UnicodeNormalization;

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
    #[error("invalid Windows sync path component: {0}")]
    InvalidPathComponent(String),
    #[error("path escapes the configured sync root")]
    PathOutsideSyncRoot,
    #[error("sync path pattern is invalid: {0}")]
    InvalidPathPattern(String),
    #[error("file system watcher failed: {0}")]
    Watcher(String),
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum FileWatchKind {
    Created,
    Modified,
    Removed,
    Renamed,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct FileWatchEvent {
    pub kind: FileWatchKind,
    pub paths: Vec<PathBuf>,
}

pub struct RootWatcher {
    _watcher: RecommendedWatcher,
    receiver: Receiver<notify::Result<Event>>,
}

impl RootWatcher {
    pub fn watch(root: impl AsRef<Path>) -> Result<Self> {
        let root = validate_sync_root(root)?;
        let (sender, receiver) = mpsc::channel();
        let mut watcher = RecommendedWatcher::new(
            move |event| {
                let _ = sender.send(event);
            },
            Config::default(),
        )
        .map_err(|error| PlatformError::Watcher(error.to_string()))?;
        watcher
            .watch(&root, RecursiveMode::Recursive)
            .map_err(|error| PlatformError::Watcher(error.to_string()))?;
        Ok(Self {
            _watcher: watcher,
            receiver,
        })
    }

    pub fn recv_timeout(&self, timeout: Duration) -> Result<Option<FileWatchEvent>> {
        match self.receiver.recv_timeout(timeout) {
            Ok(event) => event
                .map_err(|error| PlatformError::Watcher(error.to_string()))
                .map(map_watch_event),
            Err(RecvTimeoutError::Timeout) => Ok(None),
            Err(RecvTimeoutError::Disconnected) => Err(PlatformError::Watcher(
                "watcher channel disconnected".to_string(),
            )),
        }
    }

    pub fn drain(&self) -> Result<Vec<FileWatchEvent>> {
        let mut events = Vec::new();
        loop {
            match self.receiver.try_recv() {
                Ok(event) => {
                    let event = event.map_err(|error| PlatformError::Watcher(error.to_string()))?;
                    if let Some(event) = map_watch_event(event) {
                        events.push(event);
                    }
                }
                Err(TryRecvError::Empty) => return Ok(events),
                Err(TryRecvError::Disconnected) => {
                    return Err(PlatformError::Watcher(
                        "watcher channel disconnected".to_string(),
                    ));
                }
            }
        }
    }
}

#[derive(Clone)]
pub struct SyncPathFilter {
    includes: GlobSet,
    ignores: GlobSet,
    has_includes: bool,
}

impl SyncPathFilter {
    pub fn new(include_patterns: &[String], ignore_patterns: &[String]) -> Result<Self> {
        let includes = build_glob_set(include_patterns)?;
        let mut all_ignores = vec![
            ".enterprise-drive".to_string(),
            ".enterprise-drive/**".to_string(),
            "**/*.drivepart".to_string(),
        ];
        all_ignores.extend(ignore_patterns.iter().cloned());
        Ok(Self {
            includes,
            ignores: build_glob_set(&all_ignores)?,
            has_includes: !include_patterns.is_empty(),
        })
    }

    pub fn includes(&self, relative_path: impl AsRef<Path>) -> bool {
        let candidate = slash_path(relative_path.as_ref());
        if self.ignores.is_match(&candidate) {
            return false;
        }
        !self.has_includes || self.includes.is_match(&candidate)
    }
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

pub fn validate_relative_sync_path(path: impl AsRef<Path>) -> Result<PathBuf> {
    let path = path.as_ref();
    if path.is_absolute() {
        return Err(PlatformError::PathOutsideSyncRoot);
    }
    let mut normalized = PathBuf::new();
    for component in path.components() {
        match component {
            Component::Normal(value) => {
                let value = value
                    .to_str()
                    .ok_or_else(|| {
                        PlatformError::InvalidPathComponent(
                            "path component is not valid UTF-8".to_string(),
                        )
                    })?
                    .nfc()
                    .collect::<String>();
                normalized.push(validate_windows_component(&value)?);
            }
            Component::CurDir => {}
            Component::ParentDir | Component::Prefix(_) | Component::RootDir => {
                return Err(PlatformError::PathOutsideSyncRoot);
            }
        }
    }
    if normalized.as_os_str().is_empty() {
        return Err(PlatformError::InvalidPathComponent(
            "path is empty".to_string(),
        ));
    }
    let utf16_length = normalized
        .as_os_str()
        .to_string_lossy()
        .encode_utf16()
        .count();
    if utf16_length > 32_000 {
        return Err(PlatformError::InvalidPathComponent(
            "path exceeds the Windows long-path boundary".to_string(),
        ));
    }
    Ok(normalized)
}

pub fn relative_path_within_root(
    root: impl AsRef<Path>,
    path: impl AsRef<Path>,
) -> Result<PathBuf> {
    let relative = path
        .as_ref()
        .strip_prefix(root.as_ref())
        .map_err(|_| PlatformError::PathOutsideSyncRoot)?;
    validate_relative_sync_path(relative)
}

pub fn resolve_within_root(
    root: impl AsRef<Path>,
    relative_path: impl AsRef<Path>,
) -> Result<PathBuf> {
    let root = validate_sync_root(root)?;
    let relative_path = validate_relative_sync_path(relative_path)?;
    Ok(root.join(relative_path))
}

pub fn ensure_no_links_or_reparse_points(
    root: impl AsRef<Path>,
    relative_path: impl AsRef<Path>,
) -> Result<()> {
    let root = validate_sync_root(root)?;
    let relative = validate_relative_sync_path(relative_path)?;
    let mut current = root;
    for component in relative.components() {
        current.push(component.as_os_str());
        if !current.exists() {
            break;
        }
        let metadata = std::fs::symlink_metadata(&current)?;
        if metadata.file_type().is_symlink() || is_reparse_point(&metadata) {
            return Err(PlatformError::SyncRootIsReparsePoint);
        }
    }
    Ok(())
}

pub fn conflict_copy_path(
    relative_path: impl AsRef<Path>,
    device_name: &str,
    detected_at: DateTime<Utc>,
) -> Result<PathBuf> {
    let relative_path = validate_relative_sync_path(relative_path)?;
    let file_name = relative_path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| PlatformError::InvalidPathComponent("file name is missing".to_string()))?;
    let source = Path::new(file_name);
    let stem = source
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or("file");
    let extension = source.extension().and_then(|value| value.to_str());
    let device = sanitize_conflict_device_name(device_name);
    let suffix = format!(
        " (conflict-{device}-{})",
        detected_at.format("%Y%m%dT%H%M%SZ")
    );
    let extension_suffix = extension
        .map(|value| format!(".{value}"))
        .unwrap_or_default();
    let mut available = 255usize
        .saturating_sub(suffix.encode_utf16().count() + extension_suffix.encode_utf16().count());
    available = available.max(1);
    let truncated_stem = truncate_utf16(stem, available);
    let conflict_name = format!("{truncated_stem}{suffix}{extension_suffix}");
    let mut result = relative_path
        .parent()
        .map(Path::to_path_buf)
        .unwrap_or_default();
    result.push(validate_windows_component(&conflict_name)?);
    Ok(result)
}

pub fn file_modified_ns(metadata: &std::fs::Metadata) -> Option<i64> {
    metadata
        .modified()
        .ok()
        .and_then(|value| value.duration_since(SystemTime::UNIX_EPOCH).ok())
        .and_then(|value| i64::try_from(value.as_nanos()).ok())
}

pub fn atomic_replace(source: impl AsRef<Path>, destination: impl AsRef<Path>) -> Result<()> {
    atomic_replace_impl(source.as_ref(), destination.as_ref()).map_err(PlatformError::SyncRootIo)
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

fn validate_windows_component(value: &str) -> Result<String> {
    if value.is_empty() || matches!(value, "." | "..") {
        return Err(PlatformError::InvalidPathComponent(value.to_string()));
    }
    if value.ends_with([' ', '.']) {
        return Err(PlatformError::InvalidPathComponent(value.to_string()));
    }
    if value.chars().any(|character| {
        character <= '\u{1f}'
            || matches!(
                character,
                '<' | '>' | ':' | '"' | '/' | '\\' | '|' | '?' | '*'
            )
    }) {
        return Err(PlatformError::InvalidPathComponent(value.to_string()));
    }
    let base_name = value
        .split('.')
        .next()
        .unwrap_or(value)
        .trim_end_matches([' ', '.'])
        .to_ascii_uppercase();
    let reserved = matches!(
        base_name.as_str(),
        "CON"
            | "PRN"
            | "AUX"
            | "NUL"
            | "COM1"
            | "COM2"
            | "COM3"
            | "COM4"
            | "COM5"
            | "COM6"
            | "COM7"
            | "COM8"
            | "COM9"
            | "LPT1"
            | "LPT2"
            | "LPT3"
            | "LPT4"
            | "LPT5"
            | "LPT6"
            | "LPT7"
            | "LPT8"
            | "LPT9"
    );
    if reserved || value.encode_utf16().count() > 255 {
        return Err(PlatformError::InvalidPathComponent(value.to_string()));
    }
    Ok(value.to_string())
}

fn build_glob_set(patterns: &[String]) -> Result<GlobSet> {
    let mut builder = GlobSetBuilder::new();
    for pattern in patterns {
        builder.add(
            Glob::new(&pattern.replace('\\', "/"))
                .map_err(|error| PlatformError::InvalidPathPattern(error.to_string()))?,
        );
    }
    builder
        .build()
        .map_err(|error| PlatformError::InvalidPathPattern(error.to_string()))
}

fn slash_path(path: &Path) -> String {
    path.components()
        .filter_map(|component| match component {
            Component::Normal(value) => value.to_str().map(ToOwned::to_owned),
            _ => None,
        })
        .collect::<Vec<_>>()
        .join("/")
}

fn sanitize_conflict_device_name(value: &str) -> String {
    let mut result = value
        .nfc()
        .map(|character| {
            if character.is_alphanumeric() || matches!(character, '-' | '_') {
                character
            } else {
                '-'
            }
        })
        .take(32)
        .collect::<String>();
    while result.contains("--") {
        result = result.replace("--", "-");
    }
    let result = result.trim_matches('-').to_string();
    if result.is_empty() {
        "device".to_string()
    } else {
        result
    }
}

fn truncate_utf16(value: &str, max_units: usize) -> String {
    let mut result = String::new();
    let mut units = 0usize;
    for character in value.chars() {
        let next = character.len_utf16();
        if units + next > max_units {
            break;
        }
        result.push(character);
        units += next;
    }
    if result.is_empty() {
        "file".to_string()
    } else {
        result
    }
}

fn map_watch_event(event: Event) -> Option<FileWatchEvent> {
    let kind = match event.kind {
        EventKind::Create(_) => FileWatchKind::Created,
        EventKind::Remove(_) => FileWatchKind::Removed,
        EventKind::Modify(ModifyKind::Name(
            RenameMode::Any
            | RenameMode::Both
            | RenameMode::From
            | RenameMode::To
            | RenameMode::Other,
        )) => FileWatchKind::Renamed,
        EventKind::Modify(_) => FileWatchKind::Modified,
        _ => return None,
    };
    Some(FileWatchEvent {
        kind,
        paths: event.paths,
    })
}

#[cfg(windows)]
fn atomic_replace_impl(source: &Path, destination: &Path) -> std::io::Result<()> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Storage::FileSystem::{
        MoveFileExW, ReplaceFileW, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH,
        REPLACEFILE_WRITE_THROUGH,
    };

    let destination_exists = destination.exists();
    let source = source
        .as_os_str()
        .encode_wide()
        .chain(std::iter::once(0))
        .collect::<Vec<_>>();
    let destination = destination
        .as_os_str()
        .encode_wide()
        .chain(std::iter::once(0))
        .collect::<Vec<_>>();
    let result = unsafe {
        if destination_exists {
            ReplaceFileW(
                destination.as_ptr(),
                source.as_ptr(),
                std::ptr::null(),
                REPLACEFILE_WRITE_THROUGH,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
            )
        } else {
            MoveFileExW(
                source.as_ptr(),
                destination.as_ptr(),
                MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
            )
        }
    };
    if result == 0 {
        return Err(std::io::Error::last_os_error());
    }
    Ok(())
}

#[cfg(not(windows))]
fn atomic_replace_impl(source: &Path, destination: &Path) -> std::io::Result<()> {
    std::fs::rename(source, destination)
}

#[cfg(test)]
mod tests {
    use std::path::PathBuf;

    use chrono::{TimeZone, Utc};

    use super::{
        atomic_replace, conflict_copy_path, validate_relative_sync_path, validate_sync_root,
        CredentialStore, MemoryCredentialStore, SyncPathFilter,
    };

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

    #[test]
    fn windows_path_policy_rejects_reserved_and_link_escape_names() {
        assert!(validate_relative_sync_path("docs/report.txt").is_ok());
        assert!(validate_relative_sync_path("CON.txt").is_err());
        assert!(validate_relative_sync_path("docs/trailing.").is_err());
        assert!(validate_relative_sync_path("../outside.txt").is_err());
        assert!(validate_relative_sync_path("docs/stream:ads").is_err());
    }

    #[test]
    fn selective_sync_and_ignore_rules_are_applied_before_queueing() {
        let filter =
            SyncPathFilter::new(&["projects/**".to_string()], &["**/*.tmp".to_string()]).unwrap();
        assert!(filter.includes("projects/design/spec.md"));
        assert!(!filter.includes("projects/design/cache.tmp"));
        assert!(!filter.includes("private/secret.txt"));
        assert!(!filter.includes("projects/design/file.drivepart"));
    }

    #[test]
    fn conflict_copy_keeps_extension_and_uses_utc_device_suffix() {
        let timestamp = Utc.with_ymd_and_hms(2026, 8, 3, 12, 34, 56).unwrap();
        assert_eq!(
            conflict_copy_path("docs/report.txt", "Work Laptop", timestamp).unwrap(),
            PathBuf::from("docs/report (conflict-Work-Laptop-20260803T123456Z).txt")
        );
    }

    #[test]
    fn atomic_replace_never_exposes_a_missing_destination_after_success() {
        let directory = tempfile::tempdir().unwrap();
        let destination = directory.path().join("file.txt");
        let replacement = directory.path().join("file.txt.drivepart");
        std::fs::write(&destination, b"old").unwrap();
        std::fs::write(&replacement, b"new").unwrap();

        atomic_replace(&replacement, &destination).unwrap();

        assert_eq!(std::fs::read(&destination).unwrap(), b"new");
        assert!(!replacement.exists());
    }
}
