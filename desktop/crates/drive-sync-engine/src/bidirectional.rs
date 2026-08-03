use std::collections::{HashMap, VecDeque};
use std::path::{Path, PathBuf};
use std::sync::mpsc::{self, Sender, TryRecvError};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use chrono::{Duration as ChronoDuration, Utc};
use drive_api_client::{
    ApiClientError, CreateFolderRequest, KnownErrorCode, MoveNodeRequest, RenameNodeRequest,
    SyncChange, SyncChangeList,
};
use drive_local_index::{
    PendingOperation, PendingOperationAction, PendingOperationStatus, SyncConflict, SyncEntry,
    SyncEntryKind, SyncEntryStatus, SyncPolicy, TransferDirection, TransferStatus,
};
use drive_platform::{
    conflict_copy_path, ensure_no_links_or_reparse_points, file_modified_ns,
    relative_path_within_root, resolve_within_root, validate_relative_sync_path, FileWatchEvent,
    FileWatchKind, RootWatcher, SyncPathFilter,
};
use drive_transfer::TransferLimits;
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use serde_json::json;
use sha2::{Digest, Sha256};
use uuid::Uuid;
use walkdir::WalkDir;

use super::{
    change_to_node, file_node_to_indexed, Result, SyncEngine, SyncEngineError, SyncRunSummary,
};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SyncConfiguration {
    pub device_name: String,
    pub include_patterns: Vec<String>,
    pub ignore_patterns: Vec<String>,
    pub bandwidth_limit_bps: Option<u64>,
    pub max_concurrent_transfers: usize,
}

impl Default for SyncConfiguration {
    fn default() -> Self {
        Self {
            device_name: "Windows Desktop".to_string(),
            include_patterns: Vec::new(),
            ignore_patterns: Vec::new(),
            bandwidth_limit_bps: None,
            max_concurrent_transfers: 4,
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct SyncInitializationSummary {
    pub sync: SyncRunSummary,
    pub materialized_folders: usize,
    pub queued_downloads: usize,
    pub conflicts: usize,
    pub watcher_started: bool,
}

#[derive(Debug, Clone, Serialize, Default)]
pub struct SyncCycleSummary {
    pub root_node_id: Uuid,
    pub remote_changes: usize,
    pub local_operations_completed: usize,
    pub transfer_tasks_completed: usize,
    pub retries_scheduled: usize,
    pub conflicts_recorded: usize,
}

#[derive(Debug, Clone, Serialize)]
pub struct SyncWatcherSummary {
    pub root_node_id: Uuid,
    pub running: bool,
}

pub(crate) struct SyncRuntimeState {
    watchers: Mutex<HashMap<Uuid, WatcherHandle>>,
    suppressed_paths: Mutex<HashMap<PathBuf, Instant>>,
}

impl Default for SyncRuntimeState {
    fn default() -> Self {
        Self {
            watchers: Mutex::new(HashMap::new()),
            suppressed_paths: Mutex::new(HashMap::new()),
        }
    }
}

impl Drop for SyncRuntimeState {
    fn drop(&mut self) {
        let watchers = self.watchers.get_mut();
        for (_, watcher) in watchers.drain() {
            watcher.stop();
        }
    }
}

struct WatcherHandle {
    stop_sender: Sender<()>,
    thread: Option<JoinHandle<()>>,
}

impl WatcherHandle {
    fn stop(mut self) {
        let _ = self.stop_sender.send(());
        if let Some(thread) = self.thread.take() {
            let _ = thread.join();
        }
    }
}

impl SyncEngine {
    pub async fn configure_bidirectional_root(
        &self,
        space_id: Uuid,
        root_node_id: Uuid,
        local_path: impl AsRef<Path>,
        configuration: SyncConfiguration,
    ) -> Result<SyncInitializationSummary> {
        let sync = self
            .initialize_root(space_id, root_node_id, local_path)
            .await?;
        let policy = SyncPolicy {
            root_node_id,
            device_name: configuration.device_name,
            include_patterns: configuration.include_patterns,
            ignore_patterns: configuration.ignore_patterns,
            bandwidth_limit_bps: configuration.bandwidth_limit_bps.filter(|value| *value > 0),
            max_concurrent_transfers: configuration.max_concurrent_transfers.clamp(1, 16),
            updated_at: Utc::now(),
        };
        self.index.upsert_sync_policy(&policy)?;
        self.transfers.set_limits(TransferLimits {
            bandwidth_limit_bps: policy.bandwidth_limit_bps,
            max_concurrent_transfers: policy.max_concurrent_transfers,
        });
        let (materialized_folders, queued_downloads, conflicts) =
            self.materialize_remote_snapshot(root_node_id)?;
        let watcher_started = self.start_watcher(root_node_id)?.running;
        Ok(SyncInitializationSummary {
            sync,
            materialized_folders,
            queued_downloads,
            conflicts,
            watcher_started,
        })
    }

    pub fn start_saved_watchers(&self) -> Result<Vec<SyncWatcherSummary>> {
        let mut summaries = Vec::new();
        for root in self.index.list_sync_roots()? {
            if root.enabled {
                self.scan_root(root.root_node_id)?;
                summaries.push(self.start_watcher(root.root_node_id)?);
            }
        }
        Ok(summaries)
    }

    pub fn start_watcher(&self, root_node_id: Uuid) -> Result<SyncWatcherSummary> {
        self.stop_watcher(root_node_id);
        let root = self
            .index
            .get_sync_root(root_node_id)?
            .ok_or(SyncEngineError::RootNotConfigured)?;
        let watcher = RootWatcher::watch(&root.local_path)?;
        let (stop_sender, stop_receiver) = mpsc::channel();
        let api = self.api.clone();
        let index = self.index.clone();
        let transfers = self.transfers.clone();
        let runtime = std::sync::Arc::downgrade(&self.runtime);
        let thread = thread::Builder::new()
            .name(format!("drive-sync-{root_node_id}"))
            .spawn(move || loop {
                match stop_receiver.try_recv() {
                    Ok(()) | Err(TryRecvError::Disconnected) => break,
                    Err(TryRecvError::Empty) => {}
                }
                match watcher.recv_timeout(Duration::from_millis(400)) {
                    Ok(Some(event)) => {
                        let Some(runtime) = runtime.upgrade() else {
                            break;
                        };
                        let engine = SyncEngine {
                            api: api.clone(),
                            index: index.clone(),
                            transfers: transfers.clone(),
                            runtime,
                        };
                        let _ = engine.record_watch_event(root_node_id, &event);
                    }
                    Ok(None) => {}
                    Err(_) => break,
                }
            })?;
        self.runtime.watchers.lock().insert(
            root_node_id,
            WatcherHandle {
                stop_sender,
                thread: Some(thread),
            },
        );
        Ok(SyncWatcherSummary {
            root_node_id,
            running: true,
        })
    }

    pub fn stop_watcher(&self, root_node_id: Uuid) -> SyncWatcherSummary {
        if let Some(watcher) = self.runtime.watchers.lock().remove(&root_node_id) {
            watcher.stop();
        }
        SyncWatcherSummary {
            root_node_id,
            running: false,
        }
    }

    pub fn watcher_status(&self) -> Vec<SyncWatcherSummary> {
        self.runtime
            .watchers
            .lock()
            .keys()
            .copied()
            .map(|root_node_id| SyncWatcherSummary {
                root_node_id,
                running: true,
            })
            .collect()
    }

    pub fn scan_root(&self, root_node_id: Uuid) -> Result<usize> {
        let root = self.root(root_node_id)?;
        let filter = self.path_filter(root_node_id)?;
        let root_path = PathBuf::from(&root.local_path);
        let mut seen = std::collections::HashSet::new();
        let mut queued = 0usize;
        for entry in WalkDir::new(&root_path).follow_links(false).into_iter() {
            let entry = match entry {
                Ok(entry) => entry,
                Err(_) => continue,
            };
            if entry.path() == root_path {
                continue;
            }
            let relative_path = match relative_path_within_root(&root_path, entry.path()) {
                Ok(path) => path,
                Err(_) => continue,
            };
            if !filter.includes(&relative_path) {
                continue;
            }
            seen.insert(path_key(&relative_path));
            queued += usize::from(self.reconcile_local_path(root_node_id, &relative_path)?);
        }
        for entry in self.index.list_sync_entries(root_node_id)? {
            if !seen.contains(&entry.relative_path)
                && entry.status != SyncEntryStatus::RemotePending
            {
                queued += usize::from(
                    self.reconcile_local_path(root_node_id, Path::new(&entry.relative_path))?,
                );
            }
        }
        Ok(queued)
    }

    pub async fn run_root_once(&self, root_node_id: Uuid) -> Result<SyncCycleSummary> {
        let root = self.root(root_node_id)?;
        if !root.enabled {
            return Ok(SyncCycleSummary {
                root_node_id,
                ..SyncCycleSummary::default()
            });
        }
        match self.run_enabled_root_once(root_node_id).await {
            Err(error) => {
                if let Some(scope) = access_revocation_scope(&error) {
                    self.stop_after_access_revocation(root_node_id, scope, &error_code(&error))?;
                }
                Err(error)
            }
            Ok(summary) => Ok(summary),
        }
    }

    async fn run_enabled_root_once(&self, root_node_id: Uuid) -> Result<SyncCycleSummary> {
        if let Some(policy) = self.index.get_sync_policy(root_node_id)? {
            self.transfers.set_limits(TransferLimits {
                bandwidth_limit_bps: policy.bandwidth_limit_bps,
                max_concurrent_transfers: policy.max_concurrent_transfers,
            });
        }
        let mut summary = SyncCycleSummary {
            root_node_id,
            ..SyncCycleSummary::default()
        };
        let (changes, conflicts) = self.pull_remote_pages(root_node_id, 20).await?;
        summary.remote_changes = changes;
        summary.conflicts_recorded += conflicts;
        let (completed, retries, conflicts) = self.flush_operations(root_node_id, 64).await?;
        summary.local_operations_completed = completed;
        summary.retries_scheduled += retries;
        summary.conflicts_recorded += conflicts;
        for result in self.transfers.run_ready_for_root(root_node_id).await {
            let task = result?;
            match task.status {
                TransferStatus::Completed => summary.transfer_tasks_completed += 1,
                TransferStatus::Queued if task.retry_count > 0 => {
                    summary.retries_scheduled += 1;
                }
                _ => {}
            }
        }
        summary.local_operations_completed += self.finalize_completed_transfers(root_node_id)?;
        Ok(summary)
    }

    fn stop_after_access_revocation(
        &self,
        root_node_id: Uuid,
        scope: AccessRevocationScope,
        code: &str,
    ) -> Result<()> {
        let root_node_ids = match scope {
            AccessRevocationScope::Root => vec![root_node_id],
            AccessRevocationScope::Device => {
                self.api.set_device_token(None);
                self.index
                    .list_sync_roots()?
                    .into_iter()
                    .map(|root| root.root_node_id)
                    .collect()
            }
        };
        for root_node_id in root_node_ids {
            self.stop_watcher(root_node_id);
            self.index.disable_sync_root(root_node_id, code)?;
            self.index.fail_transfers_for_root(root_node_id, code)?;
        }
        Ok(())
    }

    pub async fn run_all_once(&self) -> Vec<(Uuid, Result<SyncCycleSummary>)> {
        let roots = match self.index.list_sync_roots() {
            Ok(roots) => roots,
            Err(error) => return vec![(Uuid::nil(), Err(error.into()))],
        };
        let mut results = Vec::new();
        for root in roots {
            if root.enabled {
                results.push((
                    root.root_node_id,
                    self.run_root_once(root.root_node_id).await,
                ));
            }
        }
        results
    }

    fn materialize_remote_snapshot(&self, root_node_id: Uuid) -> Result<(usize, usize, usize)> {
        let root = self.root(root_node_id)?;
        let policy = self.policy(root_node_id)?;
        let filter = SyncPathFilter::new(&policy.include_patterns, &policy.ignore_patterns)?;
        let root_path = PathBuf::from(&root.local_path);
        let mut folders = VecDeque::from([(root_node_id, PathBuf::new())]);
        let mut materialized_folders = 0usize;
        let mut queued_downloads = 0usize;
        let mut conflicts = 0usize;
        while let Some((parent_id, parent_path)) = folders.pop_front() {
            for node in self.index.list_children(root.space_id, parent_id)? {
                let Some(name) = node.name.clone() else {
                    continue;
                };
                let relative_path = match validate_relative_sync_path(parent_path.join(name)) {
                    Ok(path) => path,
                    Err(error) => {
                        self.record_conflict(
                            &policy,
                            node.node_id.into(),
                            "windows_path_invalid",
                            &parent_path,
                            None,
                            json!({"error": error.to_string()}),
                        )?;
                        conflicts += 1;
                        continue;
                    }
                };
                if !filter.includes(&relative_path) {
                    self.index.upsert_sync_entry(&SyncEntry {
                        root_node_id,
                        node_id: Some(node.node_id),
                        relative_path: path_key(&relative_path),
                        kind: entry_kind(&node.node_type),
                        current_version_id: node.current_version_id,
                        content_hash: None,
                        size_bytes: 0,
                        local_modified_ns: None,
                        status: SyncEntryStatus::Ignored,
                        last_error_code: None,
                        updated_at: Utc::now(),
                    })?;
                    continue;
                }
                let local_path = root_path.join(&relative_path);
                if node.node_type == "folder" {
                    std::fs::create_dir_all(&local_path)?;
                    let metadata = std::fs::metadata(&local_path)?;
                    self.index.upsert_sync_entry(&SyncEntry {
                        root_node_id,
                        node_id: Some(node.node_id),
                        relative_path: path_key(&relative_path),
                        kind: SyncEntryKind::Folder,
                        current_version_id: None,
                        content_hash: None,
                        size_bytes: 0,
                        local_modified_ns: file_modified_ns(&metadata),
                        status: SyncEntryStatus::Synced,
                        last_error_code: None,
                        updated_at: Utc::now(),
                    })?;
                    folders.push_back((node.node_id, relative_path));
                    materialized_folders += 1;
                    continue;
                }
                if local_path.exists() {
                    let conflict_path = self.preserve_local_copy(
                        root_node_id,
                        &relative_path,
                        Some(node.node_id),
                        "initial_collision",
                    )?;
                    self.record_conflict(
                        &policy,
                        Some(node.node_id),
                        "initial_collision",
                        &relative_path,
                        Some(&conflict_path),
                        json!({"remote_version_id": node.current_version_id}),
                    )?;
                    conflicts += 1;
                }
                self.suppress_path(&local_path);
                self.transfers.enqueue_sync_download(
                    root_node_id,
                    node.node_id,
                    node.current_version_id,
                    &local_path,
                )?;
                self.index.upsert_sync_entry(&SyncEntry {
                    root_node_id,
                    node_id: Some(node.node_id),
                    relative_path: path_key(&relative_path),
                    kind: SyncEntryKind::File,
                    current_version_id: node.current_version_id,
                    content_hash: None,
                    size_bytes: 0,
                    local_modified_ns: None,
                    status: SyncEntryStatus::RemotePending,
                    last_error_code: None,
                    updated_at: Utc::now(),
                })?;
                queued_downloads += 1;
            }
        }
        Ok((materialized_folders, queued_downloads, conflicts))
    }

    fn record_watch_event(&self, root_node_id: Uuid, event: &FileWatchEvent) -> Result<()> {
        let root = self.root(root_node_id)?;
        let root_path = PathBuf::from(root.local_path);
        if event.kind == FileWatchKind::Renamed && event.paths.len() >= 2 {
            let source = relative_path_within_root(&root_path, &event.paths[0])?;
            let destination = relative_path_within_root(&root_path, &event.paths[1])?;
            if self.take_suppressed(&event.paths[0]) || self.take_suppressed(&event.paths[1]) {
                return Ok(());
            }
            return self.record_local_rename(root_node_id, &source, &destination);
        }
        for path in &event.paths {
            if self.take_suppressed(path) {
                continue;
            }
            let relative_path = match relative_path_within_root(&root_path, path) {
                Ok(path) => path,
                Err(_) => continue,
            };
            let _ = self.reconcile_local_path(root_node_id, &relative_path)?;
        }
        Ok(())
    }

    fn reconcile_local_path(&self, root_node_id: Uuid, relative_path: &Path) -> Result<bool> {
        let root = self.root(root_node_id)?;
        let filter = self.path_filter(root_node_id)?;
        let relative_path = validate_relative_sync_path(relative_path)?;
        if !filter.includes(&relative_path) {
            return Ok(false);
        }
        ensure_no_links_or_reparse_points(&root.local_path, &relative_path)?;
        let local_path = resolve_within_root(&root.local_path, &relative_path)?;
        let relative_key = path_key(&relative_path);
        let entry = self
            .index
            .get_sync_entry_by_path(root_node_id, &relative_key)?;
        if entry.as_ref().is_some_and(|entry| {
            entry.status == SyncEntryStatus::LocalPending
                && self
                    .has_active_operation(root_node_id, &relative_key, None)
                    .unwrap_or(false)
        }) {
            return Ok(false);
        }
        if local_path.exists() {
            let metadata = std::fs::metadata(&local_path)?;
            if metadata.is_dir() {
                if entry.as_ref().is_some_and(|entry| entry.node_id.is_some()) {
                    return Ok(false);
                }
                let parent_node_id = self.parent_node_id(root_node_id, &relative_path)?;
                return self.queue_local_operation(
                    root_node_id,
                    PendingOperationAction::CreateFolder,
                    &relative_path,
                    None,
                    None,
                    Some(parent_node_id),
                    None,
                    json!({}),
                    SyncEntryKind::Folder,
                    &metadata,
                );
            }
            if !metadata.is_file() {
                return Ok(false);
            }
            if let Some(entry) = &entry {
                if entry.status == SyncEntryStatus::RemotePending {
                    return Ok(false);
                }
                if entry.size_bytes == i64::try_from(metadata.len()).unwrap_or(i64::MAX)
                    && entry.local_modified_ns == file_modified_ns(&metadata)
                    && entry.status == SyncEntryStatus::Synced
                {
                    return Ok(false);
                }
            }
            let parent_node_id = self.parent_node_id(root_node_id, &relative_path)?;
            return self.queue_local_operation(
                root_node_id,
                PendingOperationAction::UploadFile,
                &relative_path,
                None,
                entry.as_ref().and_then(|entry| entry.node_id),
                Some(parent_node_id),
                entry.as_ref().and_then(|entry| entry.current_version_id),
                json!({}),
                SyncEntryKind::File,
                &metadata,
            );
        }
        let Some(entry) = entry else {
            return Ok(false);
        };
        let Some(node_id) = entry.node_id else {
            self.index.delete_sync_entry(root_node_id, &relative_key)?;
            return Ok(false);
        };
        if self.has_active_operation(root_node_id, &relative_key, None)? {
            return Ok(false);
        }
        let operation = pending_operation(
            root_node_id,
            PendingOperationAction::Delete,
            &relative_path,
            None,
            Some(node_id),
            None,
            entry.current_version_id,
            json!({}),
        )?;
        self.index.enqueue_operation(&operation)?;
        self.index.upsert_sync_entry(&SyncEntry {
            status: SyncEntryStatus::LocalPending,
            updated_at: Utc::now(),
            ..entry
        })?;
        Ok(true)
    }

    fn record_local_rename(
        &self,
        root_node_id: Uuid,
        source: &Path,
        destination: &Path,
    ) -> Result<()> {
        let source = validate_relative_sync_path(source)?;
        let destination = validate_relative_sync_path(destination)?;
        let source_key = path_key(&source);
        let destination_key = path_key(&destination);
        if self.has_active_operation(root_node_id, &destination_key, Some(source_key.as_str()))? {
            return Ok(());
        }
        let Some(mut entry) = self
            .index
            .get_sync_entry_by_path(root_node_id, &source_key)?
        else {
            let _ = self.reconcile_local_path(root_node_id, &destination)?;
            return Ok(());
        };
        self.index.delete_sync_entry(root_node_id, &source_key)?;
        entry.relative_path = destination_key;
        entry.local_modified_ns = std::fs::metadata(resolve_within_root(
            &self.root(root_node_id)?.local_path,
            &destination,
        )?)
        .ok()
        .and_then(|metadata| file_modified_ns(&metadata));
        entry.status = SyncEntryStatus::LocalPending;
        entry.updated_at = Utc::now();
        self.index.upsert_sync_entry(&entry)?;
        let Some(node_id) = entry.node_id else {
            let _ = self.reconcile_local_path(root_node_id, &destination)?;
            return Ok(());
        };
        let parent_node_id = self.parent_node_id(root_node_id, &destination)?;
        let action = if source.parent() == destination.parent() {
            PendingOperationAction::Rename
        } else {
            PendingOperationAction::Move
        };
        let operation = pending_operation(
            root_node_id,
            action,
            &destination,
            Some(&source),
            Some(node_id),
            Some(parent_node_id),
            entry.current_version_id,
            json!({}),
        )?;
        self.index.enqueue_operation(&operation)?;
        Ok(())
    }

    async fn pull_remote_pages(
        &self,
        root_node_id: Uuid,
        max_pages: usize,
    ) -> Result<(usize, usize)> {
        let root = self.root(root_node_id)?;
        let mut cursor = root.cursor.clone();
        let mut changes = 0usize;
        let mut conflicts = 0usize;
        for _ in 0..max_pages {
            let page = self
                .api
                .sync_changes(root.space_id, root.root_node_id, cursor.as_deref(), 200)
                .await?;
            let page_conflicts = self.apply_remote_page(&page)?;
            cursor = Some(page.next_cursor.clone());
            changes += page.items.len();
            conflicts += page_conflicts;
            if !page.has_more {
                return Ok((changes, conflicts));
            }
        }
        Err(SyncEngineError::PageLimitExceeded)
    }

    fn apply_remote_page(&self, page: &SyncChangeList) -> Result<usize> {
        let mut conflicts = 0usize;
        for change in &page.items {
            if self.apply_own_change(page.root_node_id, change)? {
                continue;
            }
            conflicts += self.apply_remote_change(page.root_node_id, change)?;
        }
        let nodes = page.items.iter().map(change_to_node).collect::<Vec<_>>();
        self.index
            .apply_sync_page(page.root_node_id, &nodes, &page.next_cursor)?;
        Ok(conflicts)
    }

    fn apply_own_change(&self, root_node_id: Uuid, change: &SyncChange) -> Result<bool> {
        let Some(client_operation_id) = change.client_operation_id.as_deref() else {
            return Ok(false);
        };
        let base_operation_id = client_operation_id
            .strip_suffix(":init")
            .or_else(|| client_operation_id.strip_suffix(":complete"))
            .or_else(|| client_operation_id.strip_suffix(":abort"))
            .unwrap_or(client_operation_id);
        let Some(operation) = self.index.get_operation_by_client_id(base_operation_id)? else {
            return Ok(false);
        };
        if operation.root_node_id != root_node_id {
            return Ok(false);
        }
        self.index.update_operation(
            operation.id,
            PendingOperationStatus::Completed,
            operation.retry_count,
            None,
            None,
        )?;
        if change.tombstone {
            self.index
                .delete_sync_entry(root_node_id, &operation.relative_path)?;
            return Ok(true);
        }
        if let Some(mut entry) = self
            .index
            .get_sync_entry_by_path(root_node_id, &operation.relative_path)?
        {
            entry.node_id = Some(change.node_id);
            entry.current_version_id = change.current_version_id;
            entry.status = SyncEntryStatus::Synced;
            entry.last_error_code = None;
            entry.updated_at = Utc::now();
            self.index.upsert_sync_entry(&entry)?;
        }
        Ok(true)
    }

    fn apply_remote_change(&self, root_node_id: Uuid, change: &SyncChange) -> Result<usize> {
        let root = self.root(root_node_id)?;
        let policy = self.policy(root_node_id)?;
        let active_operations = self.active_operations_for_node(root_node_id, change.node_id)?;
        if change.node_id == root_node_id && change.change_type.contains("permission") {
            return Ok(0);
        }
        if change.tombstone {
            let Some(entry) = self
                .index
                .get_sync_entry_by_node(root_node_id, change.node_id)?
            else {
                return Ok(0);
            };
            let relative_path = PathBuf::from(&entry.relative_path);
            let local_path = resolve_within_root(&root.local_path, &relative_path)?;
            let mut conflicts = 0;
            if local_path.exists() && self.entry_is_locally_modified(&root.local_path, &entry)? {
                let conflict_path = self.preserve_local_copy(
                    root_node_id,
                    &relative_path,
                    Some(change.node_id),
                    "remote_deleted_local_modified",
                )?;
                self.record_conflict(
                    &policy,
                    Some(change.node_id),
                    "remote_deleted_local_modified",
                    &relative_path,
                    Some(&conflict_path),
                    json!({"change_type": change.change_type}),
                )?;
                let _ = self.reconcile_local_path(root_node_id, &conflict_path)?;
                conflicts += 1;
            } else if local_path.exists() {
                self.suppress_path(&local_path);
                safe_remove(&root.local_path, &relative_path)?;
            }
            self.index
                .delete_sync_entry(root_node_id, &entry.relative_path)?;
            let conflicting_operations = active_operations
                .iter()
                .filter(|operation| operation.action != PendingOperationAction::Delete)
                .cloned()
                .collect::<Vec<_>>();
            self.mark_operations_conflict(&conflicting_operations, "SYNC_REMOTE_DELETE_CONFLICT")?;
            for operation in active_operations
                .iter()
                .filter(|operation| operation.action == PendingOperationAction::Delete)
            {
                self.index.update_operation(
                    operation.id,
                    PendingOperationStatus::Completed,
                    operation.retry_count,
                    None,
                    None,
                )?;
            }
            return Ok(conflicts);
        }
        let Some(name) = change.name.as_deref() else {
            return Ok(0);
        };
        let parent_path = if change.parent_id == Some(root_node_id) {
            PathBuf::new()
        } else if let Some(parent_id) = change.parent_id {
            let Some(parent) = self.index.get_sync_entry_by_node(root_node_id, parent_id)? else {
                return Ok(0);
            };
            PathBuf::from(parent.relative_path)
        } else {
            PathBuf::new()
        };
        let desired_path = match validate_relative_sync_path(parent_path.join(name)) {
            Ok(path) => path,
            Err(error) => {
                self.record_conflict(
                    &policy,
                    Some(change.node_id),
                    "windows_path_invalid",
                    &parent_path,
                    None,
                    json!({"name": name, "error": error.to_string()}),
                )?;
                return Ok(1);
            }
        };
        let filter = self.path_filter(root_node_id)?;
        if !filter.includes(&desired_path) {
            return Ok(0);
        }
        let mut conflicts = 0usize;
        let existing = self
            .index
            .get_sync_entry_by_node(root_node_id, change.node_id)?;
        if let Some(entry) = &existing {
            let old_path = PathBuf::from(&entry.relative_path);
            if old_path != desired_path {
                let old_local = resolve_within_root(&root.local_path, &old_path)?;
                let new_local = resolve_within_root(&root.local_path, &desired_path)?;
                let mut path_conflict_recorded = false;
                if new_local.exists() {
                    let target_conflict_path = self.preserve_local_copy(
                        root_node_id,
                        &desired_path,
                        None,
                        "remote_move_target_exists",
                    )?;
                    self.record_conflict(
                        &policy,
                        None,
                        "remote_move_target_exists",
                        &desired_path,
                        Some(&target_conflict_path),
                        json!({"remote_node_id": change.node_id}),
                    )?;
                    let _ = self.reconcile_local_path(root_node_id, &target_conflict_path)?;
                    conflicts += 1;
                }
                if old_local.exists() && self.entry_is_locally_modified(&root.local_path, entry)? {
                    let conflict_path = self.preserve_local_copy(
                        root_node_id,
                        &old_path,
                        Some(change.node_id),
                        "rename_move_conflict",
                    )?;
                    self.record_conflict(
                        &policy,
                        Some(change.node_id),
                        "rename_move_conflict",
                        &old_path,
                        Some(&conflict_path),
                        json!({"remote_path": path_key(&desired_path)}),
                    )?;
                    let _ = self.reconcile_local_path(root_node_id, &conflict_path)?;
                    conflicts += 1;
                    path_conflict_recorded = true;
                } else if old_local.exists() {
                    if let Some(parent) = new_local.parent() {
                        std::fs::create_dir_all(parent)?;
                    }
                    self.suppress_path(&old_local);
                    self.suppress_path(&new_local);
                    std::fs::rename(&old_local, &new_local)?;
                }
                if !active_operations.is_empty() {
                    if !path_conflict_recorded {
                        self.record_conflict(
                            &policy,
                            Some(change.node_id),
                            "rename_move_conflict",
                            &old_path,
                            None,
                            json!({
                                "remote_path": path_key(&desired_path),
                                "local_operations": active_operations
                                    .iter()
                                    .map(|operation| operation.client_operation_id.clone())
                                    .collect::<Vec<_>>(),
                            }),
                        )?;
                        conflicts += 1;
                    }
                    self.mark_operations_conflict(&active_operations, "SYNC_PATH_CONFLICT")?;
                }
                self.index
                    .delete_sync_entry(root_node_id, &entry.relative_path)?;
            }
        }
        let local_path = resolve_within_root(&root.local_path, &desired_path)?;
        let kind = entry_kind(change.node_type.as_deref().unwrap_or("file"));
        if kind == SyncEntryKind::Folder {
            std::fs::create_dir_all(&local_path)?;
            let metadata = std::fs::metadata(&local_path)?;
            self.index.upsert_sync_entry(&SyncEntry {
                root_node_id,
                node_id: Some(change.node_id),
                relative_path: path_key(&desired_path),
                kind,
                current_version_id: None,
                content_hash: None,
                size_bytes: 0,
                local_modified_ns: file_modified_ns(&metadata),
                status: SyncEntryStatus::Synced,
                last_error_code: None,
                updated_at: Utc::now(),
            })?;
            return Ok(conflicts);
        }
        let version_changed = existing
            .as_ref()
            .is_none_or(|entry| entry.current_version_id != change.current_version_id);
        if version_changed {
            let content_operations = active_operations
                .iter()
                .filter(|operation| {
                    matches!(
                        operation.action,
                        PendingOperationAction::UploadFile | PendingOperationAction::Delete
                    )
                })
                .cloned()
                .collect::<Vec<_>>();
            if let Some(entry) = &existing {
                if local_path.exists() && self.entry_is_locally_modified(&root.local_path, entry)? {
                    let conflict_path = self.preserve_local_copy(
                        root_node_id,
                        &desired_path,
                        Some(change.node_id),
                        "both_modified",
                    )?;
                    self.record_conflict(
                        &policy,
                        Some(change.node_id),
                        "both_modified",
                        &desired_path,
                        Some(&conflict_path),
                        json!({
                            "local_version_id": entry.current_version_id,
                            "remote_version_id": change.current_version_id,
                        }),
                    )?;
                    let _ = self.reconcile_local_path(root_node_id, &conflict_path)?;
                    conflicts += 1;
                } else if !content_operations.is_empty() {
                    self.record_conflict(
                        &policy,
                        Some(change.node_id),
                        "local_deleted_remote_modified",
                        &desired_path,
                        None,
                        json!({
                            "local_operations": content_operations
                                .iter()
                                .map(|operation| operation.client_operation_id.clone())
                                .collect::<Vec<_>>(),
                            "remote_version_id": change.current_version_id,
                        }),
                    )?;
                    conflicts += 1;
                }
            } else if local_path.exists() {
                let conflict_path = self.preserve_local_copy(
                    root_node_id,
                    &desired_path,
                    Some(change.node_id),
                    "remote_created_local_exists",
                )?;
                self.record_conflict(
                    &policy,
                    Some(change.node_id),
                    "remote_created_local_exists",
                    &desired_path,
                    Some(&conflict_path),
                    json!({}),
                )?;
                let _ = self.reconcile_local_path(root_node_id, &conflict_path)?;
                conflicts += 1;
            }
            self.mark_operations_conflict(&content_operations, "FILE_VERSION_CONFLICT")?;
        }
        let needs_download = version_changed || !local_path.exists();
        if needs_download
            && !self.has_download_task(root_node_id, change.node_id, change.current_version_id)?
        {
            self.suppress_path(&local_path);
            self.transfers.enqueue_sync_download(
                root_node_id,
                change.node_id,
                change.current_version_id,
                &local_path,
            )?;
        }
        self.index.upsert_sync_entry(&SyncEntry {
            root_node_id,
            node_id: Some(change.node_id),
            relative_path: path_key(&desired_path),
            kind,
            current_version_id: change.current_version_id,
            content_hash: existing
                .as_ref()
                .and_then(|entry| entry.content_hash.clone()),
            size_bytes: existing.as_ref().map_or(0, |entry| entry.size_bytes),
            local_modified_ns: existing.as_ref().and_then(|entry| entry.local_modified_ns),
            status: if needs_download {
                SyncEntryStatus::RemotePending
            } else {
                SyncEntryStatus::Synced
            },
            last_error_code: None,
            updated_at: Utc::now(),
        })?;
        Ok(conflicts)
    }

    async fn flush_operations(
        &self,
        root_node_id: Uuid,
        limit: usize,
    ) -> Result<(usize, usize, usize)> {
        let operations =
            self.index
                .list_ready_operations_for_root(root_node_id, Utc::now(), limit)?;
        let mut completed = 0usize;
        let mut retries = 0usize;
        let mut conflicts = 0usize;
        for operation in operations {
            self.index.update_operation(
                operation.id,
                PendingOperationStatus::Running,
                operation.retry_count,
                None,
                None,
            )?;
            match self.execute_operation(&operation).await {
                Ok(OperationOutcome::Completed) => completed += 1,
                Ok(OperationOutcome::Retrying) => retries += 1,
                Err(error) if access_revocation_scope(&error).is_some() => return Err(error),
                Err(error) if is_version_conflict(&error) => {
                    self.resolve_operation_conflict(&operation, &error)?;
                    conflicts += 1;
                }
                Err(error) if is_retryable_api_error(&error) => {
                    self.schedule_operation_retry(&operation, error_code(&error))?;
                    retries += 1;
                }
                Err(error) => {
                    self.index.update_operation(
                        operation.id,
                        PendingOperationStatus::Failed,
                        operation.retry_count,
                        None,
                        Some(&error_code(&error)),
                    )?;
                }
            }
        }
        Ok((completed, retries, conflicts))
    }

    async fn execute_operation(&self, operation: &PendingOperation) -> Result<OperationOutcome> {
        let root = self.root(operation.root_node_id)?;
        let relative_path = PathBuf::from(&operation.relative_path);
        let file_name = relative_path
            .file_name()
            .and_then(|value| value.to_str())
            .ok_or_else(|| {
                SyncEngineError::Io(std::io::Error::new(
                    std::io::ErrorKind::InvalidInput,
                    "local operation path has no UTF-8 file name",
                ))
            })?
            .to_string();
        match operation.action {
            PendingOperationAction::CreateFolder => {
                let node = self
                    .api
                    .create_folder(
                        &CreateFolderRequest {
                            space_id: root.space_id,
                            parent_id: operation.parent_node_id,
                            name: file_name,
                            conflict_policy: "fail".to_string(),
                        },
                        &operation.client_operation_id,
                    )
                    .await?;
                self.index
                    .upsert_node(&file_node_to_indexed(node.clone()))?;
                let local_path = resolve_within_root(&root.local_path, &relative_path)?;
                let metadata = std::fs::metadata(&local_path)?;
                self.index.upsert_sync_entry(&SyncEntry {
                    root_node_id: root.root_node_id,
                    node_id: Some(node.id),
                    relative_path: operation.relative_path.clone(),
                    kind: SyncEntryKind::Folder,
                    current_version_id: None,
                    content_hash: None,
                    size_bytes: 0,
                    local_modified_ns: file_modified_ns(&metadata),
                    status: SyncEntryStatus::Synced,
                    last_error_code: None,
                    updated_at: Utc::now(),
                })?;
            }
            PendingOperationAction::UploadFile => {
                let local_path = resolve_within_root(&root.local_path, &relative_path)?;
                let task = match self
                    .index
                    .get_transfer_by_client_operation_id(&operation.client_operation_id)?
                {
                    Some(task) => task,
                    None => self.transfers.enqueue_sync_upload(
                        &local_path,
                        root.root_node_id,
                        root.space_id,
                        operation
                            .parent_node_id
                            .ok_or(SyncEngineError::RootNotConfigured)?,
                        operation.node_id,
                        operation.expected_current_version_id,
                        &operation.client_operation_id,
                    )?,
                };
                let task = self.transfers.run(task.id).await?;
                if task.status != TransferStatus::Completed {
                    self.index.update_operation(
                        operation.id,
                        PendingOperationStatus::Retrying,
                        operation.retry_count + 1,
                        task.next_attempt_at,
                        task.error_code.as_deref(),
                    )?;
                    return Ok(OperationOutcome::Retrying);
                }
                self.finalize_upload_operation(operation, &task)?;
                return Ok(OperationOutcome::Completed);
            }
            PendingOperationAction::Rename => {
                let node = self
                    .api
                    .rename_node(
                        operation
                            .node_id
                            .ok_or(SyncEngineError::RootNotConfigured)?,
                        &RenameNodeRequest {
                            name: file_name,
                            expected_current_version_id: operation.expected_current_version_id,
                        },
                        &operation.client_operation_id,
                    )
                    .await?;
                self.index.upsert_node(&file_node_to_indexed(node))?;
            }
            PendingOperationAction::Move => {
                let node = self
                    .api
                    .move_node(
                        operation
                            .node_id
                            .ok_or(SyncEngineError::RootNotConfigured)?,
                        &MoveNodeRequest {
                            target_parent_id: operation
                                .parent_node_id
                                .ok_or(SyncEngineError::RootNotConfigured)?,
                            new_name: Some(file_name),
                            conflict_policy: "fail".to_string(),
                            expected_current_version_id: operation.expected_current_version_id,
                        },
                        &operation.client_operation_id,
                    )
                    .await?;
                self.index.upsert_node(&file_node_to_indexed(node))?;
            }
            PendingOperationAction::Delete => {
                self.api
                    .delete_node(
                        operation
                            .node_id
                            .ok_or(SyncEngineError::RootNotConfigured)?,
                        operation.expected_current_version_id,
                        &operation.client_operation_id,
                    )
                    .await?;
                self.index
                    .delete_sync_entry(root.root_node_id, &operation.relative_path)?;
            }
        }
        self.index.update_operation(
            operation.id,
            PendingOperationStatus::Completed,
            operation.retry_count,
            None,
            None,
        )?;
        if let Some(mut entry) = self
            .index
            .get_sync_entry_by_path(root.root_node_id, &operation.relative_path)?
        {
            entry.status = SyncEntryStatus::Synced;
            entry.last_error_code = None;
            entry.updated_at = Utc::now();
            self.index.upsert_sync_entry(&entry)?;
        }
        Ok(OperationOutcome::Completed)
    }

    fn finalize_upload_operation(
        &self,
        operation: &PendingOperation,
        task: &drive_local_index::TransferTask,
    ) -> Result<()> {
        let root = self.root(operation.root_node_id)?;
        let local_path = resolve_within_root(&root.local_path, &operation.relative_path)?;
        let metadata = std::fs::metadata(&local_path)?;
        self.index.upsert_sync_entry(&SyncEntry {
            root_node_id: root.root_node_id,
            node_id: task.node_id,
            relative_path: operation.relative_path.clone(),
            kind: SyncEntryKind::File,
            current_version_id: task.current_version_id,
            content_hash: task.content_hash.clone(),
            size_bytes: task.size_bytes,
            local_modified_ns: file_modified_ns(&metadata),
            status: SyncEntryStatus::Synced,
            last_error_code: None,
            updated_at: Utc::now(),
        })?;
        self.index.update_operation(
            operation.id,
            PendingOperationStatus::Completed,
            operation.retry_count,
            None,
            None,
        )?;
        Ok(())
    }

    fn finalize_completed_transfers(&self, root_node_id: Uuid) -> Result<usize> {
        let root = self.root(root_node_id)?;
        let mut completed_operations = 0usize;
        for task in self.index.list_transfers()? {
            if task.root_node_id != Some(root_node_id) || task.status != TransferStatus::Completed {
                continue;
            }
            if task.direction == TransferDirection::Upload {
                if let Some(operation) = self
                    .index
                    .get_operation_by_client_id(&task.client_operation_id)?
                {
                    if operation.status != PendingOperationStatus::Completed {
                        self.finalize_upload_operation(&operation, &task)?;
                        completed_operations += 1;
                    }
                }
                continue;
            }
            let Some(node_id) = task.node_id else {
                continue;
            };
            let Some(mut entry) = self.index.get_sync_entry_by_node(root_node_id, node_id)? else {
                continue;
            };
            let local_path = resolve_within_root(&root.local_path, &entry.relative_path)?;
            let metadata = std::fs::metadata(&local_path)?;
            entry.current_version_id = task.current_version_id;
            entry.content_hash = task.content_hash.clone();
            entry.size_bytes = task.size_bytes;
            entry.local_modified_ns = file_modified_ns(&metadata);
            entry.status = SyncEntryStatus::Synced;
            entry.last_error_code = None;
            entry.updated_at = Utc::now();
            self.index.upsert_sync_entry(&entry)?;
        }
        Ok(completed_operations)
    }

    fn resolve_operation_conflict(
        &self,
        operation: &PendingOperation,
        error: &SyncEngineError,
    ) -> Result<()> {
        let policy = self.policy(operation.root_node_id)?;
        let relative_path = PathBuf::from(&operation.relative_path);
        let local_path = resolve_within_root(
            &self.root(operation.root_node_id)?.local_path,
            &relative_path,
        )?;
        let conflict_path = if local_path.exists() {
            Some(self.preserve_local_copy(
                operation.root_node_id,
                &relative_path,
                operation.node_id,
                "operation_version_conflict",
            )?)
        } else {
            None
        };
        self.record_conflict(
            &policy,
            operation.node_id,
            "operation_version_conflict",
            &relative_path,
            conflict_path.as_deref(),
            json!({"error": error.to_string()}),
        )?;
        self.index.update_operation(
            operation.id,
            PendingOperationStatus::Conflict,
            operation.retry_count,
            None,
            Some("FILE_VERSION_CONFLICT"),
        )?;
        if let Some(conflict_path) = conflict_path {
            let _ = self.reconcile_local_path(operation.root_node_id, &conflict_path)?;
        }
        Ok(())
    }

    fn schedule_operation_retry(
        &self,
        operation: &PendingOperation,
        error_code: String,
    ) -> Result<()> {
        let retry_count = operation.retry_count + 1;
        if retry_count > 8 {
            self.index.update_operation(
                operation.id,
                PendingOperationStatus::Failed,
                retry_count,
                None,
                Some(&error_code),
            )?;
            return Ok(());
        }
        let seconds = 2_i64.saturating_pow(retry_count.min(8)).clamp(2, 300);
        self.index.update_operation(
            operation.id,
            PendingOperationStatus::Retrying,
            retry_count,
            Some(Utc::now() + ChronoDuration::seconds(seconds)),
            Some(&error_code),
        )?;
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    fn queue_local_operation(
        &self,
        root_node_id: Uuid,
        action: PendingOperationAction,
        relative_path: &Path,
        source_relative_path: Option<&Path>,
        node_id: Option<Uuid>,
        parent_node_id: Option<Uuid>,
        expected_current_version_id: Option<Uuid>,
        payload: serde_json::Value,
        kind: SyncEntryKind,
        metadata: &std::fs::Metadata,
    ) -> Result<bool> {
        let relative_key = path_key(relative_path);
        if self.has_active_operation(
            root_node_id,
            &relative_key,
            source_relative_path.map(path_key).as_deref(),
        )? {
            return Ok(false);
        }
        let previous = self
            .index
            .get_sync_entry_by_path(root_node_id, &relative_key)?;
        let operation = pending_operation(
            root_node_id,
            action,
            relative_path,
            source_relative_path,
            node_id,
            parent_node_id,
            expected_current_version_id,
            payload,
        )?;
        self.index.enqueue_operation(&operation)?;
        self.index.upsert_sync_entry(&SyncEntry {
            root_node_id,
            node_id,
            relative_path: relative_key,
            kind,
            current_version_id: expected_current_version_id
                .or_else(|| previous.as_ref().and_then(|entry| entry.current_version_id)),
            content_hash: previous.and_then(|entry| entry.content_hash),
            size_bytes: i64::try_from(metadata.len()).unwrap_or(i64::MAX),
            local_modified_ns: file_modified_ns(metadata),
            status: SyncEntryStatus::LocalPending,
            last_error_code: None,
            updated_at: Utc::now(),
        })?;
        Ok(true)
    }

    fn preserve_local_copy(
        &self,
        root_node_id: Uuid,
        relative_path: &Path,
        node_id: Option<Uuid>,
        conflict_kind: &str,
    ) -> Result<PathBuf> {
        let root = self.root(root_node_id)?;
        let policy = self.policy(root_node_id)?;
        let local_path = resolve_within_root(&root.local_path, relative_path)?;
        let mut conflict_path = conflict_copy_path(relative_path, &policy.device_name, Utc::now())?;
        let mut sequence = 2usize;
        while resolve_within_root(&root.local_path, &conflict_path)?.exists() {
            conflict_path = append_copy_number(&conflict_path, sequence)?;
            sequence += 1;
        }
        let conflict_local_path = resolve_within_root(&root.local_path, &conflict_path)?;
        if let Some(parent) = conflict_local_path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        self.suppress_path(&local_path);
        self.suppress_path(&conflict_local_path);
        std::fs::rename(&local_path, &conflict_local_path)?;
        if let Some(entry) = self
            .index
            .get_sync_entry_by_path(root_node_id, &path_key(relative_path))?
        {
            self.index
                .delete_sync_entry(root_node_id, &entry.relative_path)?;
            let metadata = std::fs::metadata(&conflict_local_path)?;
            self.index.upsert_sync_entry(&SyncEntry {
                root_node_id,
                node_id: None,
                relative_path: path_key(&conflict_path),
                kind: entry.kind,
                current_version_id: None,
                content_hash: entry.content_hash,
                size_bytes: i64::try_from(metadata.len()).unwrap_or(i64::MAX),
                local_modified_ns: file_modified_ns(&metadata),
                status: SyncEntryStatus::Conflict,
                last_error_code: Some(conflict_kind.to_string()),
                updated_at: Utc::now(),
            })?;
        }
        let _ = node_id;
        Ok(conflict_path)
    }

    fn record_conflict(
        &self,
        policy: &SyncPolicy,
        node_id: Option<Uuid>,
        kind: &str,
        original_path: &Path,
        conflict_path: Option<&Path>,
        details: serde_json::Value,
    ) -> Result<()> {
        self.index.record_conflict(&SyncConflict {
            id: Uuid::new_v4(),
            root_node_id: policy.root_node_id,
            node_id,
            kind: kind.to_string(),
            original_relative_path: path_key(original_path),
            conflict_relative_path: conflict_path.map(path_key),
            device_name: policy.device_name.clone(),
            details_json: serde_json::to_string(&details)?,
            detected_at: Utc::now(),
        })?;
        Ok(())
    }

    fn entry_is_locally_modified(&self, root_path: &str, entry: &SyncEntry) -> Result<bool> {
        if entry.status == SyncEntryStatus::LocalPending
            || entry.status == SyncEntryStatus::Conflict
        {
            return Ok(true);
        }
        let local_path = resolve_within_root(root_path, &entry.relative_path)?;
        if !local_path.exists() {
            return Ok(false);
        }
        let metadata = std::fs::metadata(&local_path)?;
        if entry.size_bytes != i64::try_from(metadata.len()).unwrap_or(i64::MAX)
            || entry.local_modified_ns != file_modified_ns(&metadata)
        {
            return Ok(true);
        }
        if metadata.is_file() {
            if let Some(expected_hash) = entry.content_hash.as_deref() {
                return Ok(!sha256_file(&local_path)?.eq_ignore_ascii_case(expected_hash));
            }
        }
        Ok(false)
    }

    fn has_active_operation(
        &self,
        root_node_id: Uuid,
        relative_path: &str,
        source_relative_path: Option<&str>,
    ) -> Result<bool> {
        Ok(self
            .index
            .list_operations(root_node_id)?
            .into_iter()
            .any(|operation| {
                matches!(
                    operation.status,
                    PendingOperationStatus::Queued
                        | PendingOperationStatus::Running
                        | PendingOperationStatus::Retrying
                ) && (operation.relative_path == relative_path
                    || source_relative_path.is_some_and(|source| {
                        operation.source_relative_path.as_deref() == Some(source)
                    }))
            }))
    }

    fn active_operations_for_node(
        &self,
        root_node_id: Uuid,
        node_id: Uuid,
    ) -> Result<Vec<PendingOperation>> {
        Ok(self
            .index
            .list_operations(root_node_id)?
            .into_iter()
            .filter(|operation| {
                operation.node_id == Some(node_id)
                    && matches!(
                        operation.status,
                        PendingOperationStatus::Queued
                            | PendingOperationStatus::Running
                            | PendingOperationStatus::Retrying
                    )
            })
            .collect())
    }

    fn mark_operations_conflict(
        &self,
        operations: &[PendingOperation],
        error_code: &str,
    ) -> Result<()> {
        for operation in operations {
            self.index.update_operation(
                operation.id,
                PendingOperationStatus::Conflict,
                operation.retry_count,
                None,
                Some(error_code),
            )?;
            self.index
                .fail_transfer_by_client_operation_id(&operation.client_operation_id, error_code)?;
        }
        Ok(())
    }

    fn has_download_task(
        &self,
        root_node_id: Uuid,
        node_id: Uuid,
        version_id: Option<Uuid>,
    ) -> Result<bool> {
        Ok(self.index.list_transfers()?.into_iter().any(|task| {
            task.root_node_id == Some(root_node_id)
                && task.direction == TransferDirection::Download
                && task.node_id == Some(node_id)
                && task.current_version_id == version_id
                && !matches!(
                    task.status,
                    TransferStatus::Cancelled | TransferStatus::Failed
                )
        }))
    }

    fn parent_node_id(&self, root_node_id: Uuid, relative_path: &Path) -> Result<Uuid> {
        let Some(parent) = relative_path.parent() else {
            return Ok(root_node_id);
        };
        if parent.as_os_str().is_empty() {
            return Ok(root_node_id);
        }
        self.index
            .get_sync_entry_by_path(root_node_id, &path_key(parent))?
            .and_then(|entry| entry.node_id)
            .ok_or(SyncEngineError::RootNotConfigured)
    }

    fn root(&self, root_node_id: Uuid) -> Result<drive_local_index::SyncRoot> {
        self.index
            .get_sync_root(root_node_id)?
            .ok_or(SyncEngineError::RootNotConfigured)
    }

    fn policy(&self, root_node_id: Uuid) -> Result<SyncPolicy> {
        Ok(self
            .index
            .get_sync_policy(root_node_id)?
            .unwrap_or(SyncPolicy {
                root_node_id,
                device_name: "Windows Desktop".to_string(),
                include_patterns: Vec::new(),
                ignore_patterns: Vec::new(),
                bandwidth_limit_bps: None,
                max_concurrent_transfers: 4,
                updated_at: Utc::now(),
            }))
    }

    fn path_filter(&self, root_node_id: Uuid) -> Result<SyncPathFilter> {
        let policy = self.policy(root_node_id)?;
        Ok(SyncPathFilter::new(
            &policy.include_patterns,
            &policy.ignore_patterns,
        )?)
    }

    fn suppress_path(&self, path: &Path) {
        self.runtime
            .suppressed_paths
            .lock()
            .insert(path.to_path_buf(), Instant::now() + Duration::from_secs(90));
    }

    fn take_suppressed(&self, path: &Path) -> bool {
        let now = Instant::now();
        let mut suppressed = self.runtime.suppressed_paths.lock();
        suppressed.retain(|_, expires_at| *expires_at > now);
        suppressed.remove(path).is_some()
    }
}

enum OperationOutcome {
    Completed,
    Retrying,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum AccessRevocationScope {
    Root,
    Device,
}

#[allow(clippy::too_many_arguments)]
fn pending_operation(
    root_node_id: Uuid,
    action: PendingOperationAction,
    relative_path: &Path,
    source_relative_path: Option<&Path>,
    node_id: Option<Uuid>,
    parent_node_id: Option<Uuid>,
    expected_current_version_id: Option<Uuid>,
    payload: serde_json::Value,
) -> Result<PendingOperation> {
    let now = Utc::now();
    let id = Uuid::new_v4();
    Ok(PendingOperation {
        id,
        root_node_id,
        client_operation_id: id.to_string(),
        action,
        relative_path: path_key(relative_path),
        source_relative_path: source_relative_path.map(path_key),
        node_id,
        parent_node_id,
        expected_current_version_id,
        payload_json: serde_json::to_string(&payload)?,
        status: PendingOperationStatus::Queued,
        retry_count: 0,
        next_attempt_at: None,
        error_code: None,
        created_at: now,
        updated_at: now,
    })
}

fn entry_kind(node_type: &str) -> SyncEntryKind {
    if node_type == "folder" {
        SyncEntryKind::Folder
    } else {
        SyncEntryKind::File
    }
}

fn path_key(path: impl AsRef<Path>) -> String {
    path.as_ref()
        .components()
        .filter_map(|component| match component {
            std::path::Component::Normal(value) => value.to_str().map(ToOwned::to_owned),
            _ => None,
        })
        .collect::<Vec<_>>()
        .join("/")
}

fn append_copy_number(path: &Path, sequence: usize) -> Result<PathBuf> {
    let file_name = path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| {
            SyncEngineError::Io(std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "conflict path has no file name",
            ))
        })?;
    let source = Path::new(file_name);
    let stem = source
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or("file");
    let extension = source.extension().and_then(|value| value.to_str());
    let file_name = match extension {
        Some(extension) => format!("{stem} ({sequence}).{extension}"),
        None => format!("{stem} ({sequence})"),
    };
    let mut result = path.parent().map(Path::to_path_buf).unwrap_or_default();
    result.push(file_name);
    Ok(validate_relative_sync_path(result)?)
}

fn safe_remove(root_path: &str, relative_path: &Path) -> Result<()> {
    ensure_no_links_or_reparse_points(root_path, relative_path)?;
    let path = resolve_within_root(root_path, relative_path)?;
    if path.is_dir() {
        std::fs::remove_dir_all(path)?;
    } else if path.exists() {
        std::fs::remove_file(path)?;
    }
    Ok(())
}

fn is_version_conflict(error: &SyncEngineError) -> bool {
    matches!(
        error,
        SyncEngineError::Api(error)
            if matches!(error.known_api_code(), Some(KnownErrorCode::FileVersionConflict))
    ) || matches!(
        error,
        SyncEngineError::Transfer(drive_transfer::TransferError::Api(error))
            if matches!(error.known_api_code(), Some(KnownErrorCode::FileVersionConflict))
    )
}

fn access_revocation_scope(error: &SyncEngineError) -> Option<AccessRevocationScope> {
    let known_code = match error {
        SyncEngineError::Api(error) => error.known_api_code(),
        SyncEngineError::Transfer(drive_transfer::TransferError::Api(error)) => {
            error.known_api_code()
        }
        _ => None,
    }?;
    match known_code {
        KnownErrorCode::SyncPermissionRevoked => Some(AccessRevocationScope::Root),
        KnownErrorCode::DeviceSessionInvalid
        | KnownErrorCode::DeviceSessionRevoked
        | KnownErrorCode::DeviceSessionExpired
        | KnownErrorCode::DeviceSessionReused => Some(AccessRevocationScope::Device),
        _ => None,
    }
}

fn is_retryable_api_error(error: &SyncEngineError) -> bool {
    match error {
        SyncEngineError::Api(ApiClientError::Transport(_)) => true,
        SyncEngineError::Api(error) => error
            .api_code()
            .is_some_and(|code| code == "HTTP_429" || code.starts_with("HTTP_5")),
        SyncEngineError::Transfer(error) => error.is_retryable(),
        _ => false,
    }
}

fn error_code(error: &SyncEngineError) -> String {
    match error {
        SyncEngineError::Api(error) => error
            .api_code()
            .map(ToOwned::to_owned)
            .unwrap_or_else(|| "API_TRANSPORT_ERROR".to_string()),
        SyncEngineError::Transfer(error) => error.code(),
        SyncEngineError::Platform(_) | SyncEngineError::Io(_) => "LOCAL_IO_ERROR".to_string(),
        SyncEngineError::Index(_) => "LOCAL_INDEX_ERROR".to_string(),
        SyncEngineError::Serialization(_) => "LOCAL_SERIALIZATION_ERROR".to_string(),
        SyncEngineError::RootNotConfigured => "SYNC_ROOT_NOT_CONFIGURED".to_string(),
        SyncEngineError::PageLimitExceeded => "SYNC_PAGE_LIMIT_EXCEEDED".to_string(),
    }
}

fn sha256_file(path: &Path) -> Result<String> {
    use std::io::Read;

    let mut file = std::fs::File::open(path)?;
    let mut digest = Sha256::new();
    let mut buffer = vec![0_u8; 1024 * 1024];
    loop {
        let count = file.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        digest.update(&buffer[..count]);
    }
    Ok(hex::encode(digest.finalize()))
}

#[cfg(test)]
mod tests {
    use std::io::{Read, Write};
    use std::net::{TcpListener, TcpStream};
    use std::path::{Path, PathBuf};

    use chrono::Utc;
    use drive_api_client::{ApiClient, SyncChange};
    use drive_local_index::{
        IndexedNode, LocalIndex, PendingOperationAction, PendingOperationStatus, SyncEntry,
        SyncEntryKind, SyncEntryStatus, SyncPolicy, SyncRoot, TransferStatus,
    };
    use sha2::{Digest, Sha256};
    use uuid::Uuid;

    use super::{error_code, path_key, pending_operation};
    use crate::SyncEngine;

    fn configure_root(index: &LocalIndex, local_path: &Path, device_name: &str) -> (Uuid, Uuid) {
        std::fs::create_dir_all(local_path).unwrap();
        let space_id = Uuid::new_v4();
        let root_node_id = Uuid::new_v4();
        index
            .upsert_sync_root(&SyncRoot {
                root_node_id,
                space_id,
                local_path: local_path.to_string_lossy().into_owned(),
                cursor: Some("cursor".to_string()),
                enabled: true,
                updated_at: Utc::now(),
            })
            .unwrap();
        index
            .upsert_sync_policy(&SyncPolicy {
                root_node_id,
                device_name: device_name.to_string(),
                include_patterns: Vec::new(),
                ignore_patterns: Vec::new(),
                bandwidth_limit_bps: None,
                max_concurrent_transfers: 2,
                updated_at: Utc::now(),
            })
            .unwrap();
        (space_id, root_node_id)
    }

    fn synced_entry(
        root_node_id: Uuid,
        node_id: Uuid,
        relative_path: &str,
        kind: SyncEntryKind,
        version_id: Option<Uuid>,
        local_path: &Path,
    ) -> SyncEntry {
        let metadata = std::fs::metadata(local_path).unwrap();
        let content_hash = metadata
            .is_file()
            .then(|| hex::encode(Sha256::digest(std::fs::read(local_path).unwrap())));
        SyncEntry {
            root_node_id,
            node_id: Some(node_id),
            relative_path: relative_path.to_string(),
            kind,
            current_version_id: version_id,
            content_hash,
            size_bytes: i64::try_from(metadata.len()).unwrap(),
            local_modified_ns: drive_platform::file_modified_ns(&metadata),
            status: SyncEntryStatus::Synced,
            last_error_code: None,
            updated_at: Utc::now(),
        }
    }

    fn spawn_api_error_server(code: &str) -> (String, std::thread::JoinHandle<()>) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let base_url = format!("http://{address}/api/v1");
        let code = code.to_string();
        let handle = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let _ = read_request(&mut stream);
            let body = serde_json::json!({
                "code": code,
                "message": "device access was revoked",
                "request_id": "sync-test",
                "details": null,
            })
            .to_string();
            write!(
                stream,
                "HTTP/1.1 401 Unauthorized\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                body.len()
            )
            .unwrap();
            stream.flush().unwrap();
        });
        (base_url, handle)
    }

    fn read_request(stream: &mut TcpStream) -> String {
        let mut request = Vec::new();
        let mut buffer = [0_u8; 1024];
        loop {
            let count = stream.read(&mut buffer).unwrap();
            if count == 0 {
                break;
            }
            request.extend_from_slice(&buffer[..count]);
            if request.windows(4).any(|window| window == b"\r\n\r\n") {
                break;
            }
        }
        String::from_utf8(request).unwrap()
    }

    #[test]
    fn ten_thousand_file_initial_index_is_persisted_without_per_row_transactions() {
        let api = ApiClient::new("https://drive.example.com/api/v1").unwrap();
        let index = LocalIndex::open_in_memory().unwrap();
        let space_id = Uuid::new_v4();
        let root_node_id = Uuid::new_v4();
        index
            .upsert_sync_root(&SyncRoot {
                root_node_id,
                space_id,
                local_path: "C:\\Drive".to_string(),
                cursor: Some("cursor".to_string()),
                enabled: true,
                updated_at: Utc::now(),
            })
            .unwrap();
        let nodes = (0..10_000)
            .map(|number| IndexedNode {
                node_id: Uuid::new_v4(),
                space_id,
                parent_id: Some(root_node_id),
                node_type: "file".to_string(),
                name: Some(format!("file-{number:05}.bin")),
                current_version_id: Some(Uuid::new_v4()),
                permission_version: Some(1),
                tombstone: false,
                changed_at: Utc::now(),
            })
            .collect::<Vec<_>>();
        index.upsert_nodes(&nodes).unwrap();
        let entries = nodes
            .iter()
            .map(|node| SyncEntry {
                root_node_id,
                node_id: Some(node.node_id),
                relative_path: path_key(node.name.as_deref().unwrap()),
                kind: SyncEntryKind::File,
                current_version_id: node.current_version_id,
                content_hash: None,
                size_bytes: 0,
                local_modified_ns: None,
                status: SyncEntryStatus::RemotePending,
                last_error_code: None,
                updated_at: Utc::now(),
            })
            .collect::<Vec<_>>();
        index.upsert_sync_entries(&entries).unwrap();

        let engine = SyncEngine::new(api, index.clone());
        assert_eq!(
            engine
                .local_index()
                .list_sync_entries(root_node_id)
                .unwrap()
                .len(),
            10_000
        );
    }

    #[test]
    fn sprint8_simultaneous_local_and_remote_file_modifications_preserve_both_versions() {
        let directory = tempfile::tempdir().unwrap();
        let root_path = directory.path().join("root");
        let index = LocalIndex::open_in_memory().unwrap();
        let (space_id, root_node_id) = configure_root(&index, &root_path, "Laptop");
        let node_id = Uuid::new_v4();
        let old_version_id = Uuid::new_v4();
        let new_version_id = Uuid::new_v4();
        let local_path = root_path.join("report.txt");
        std::fs::write(&local_path, b"base").unwrap();
        index
            .upsert_sync_entry(&synced_entry(
                root_node_id,
                node_id,
                "report.txt",
                SyncEntryKind::File,
                Some(old_version_id),
                &local_path,
            ))
            .unwrap();
        let api = ApiClient::new("https://drive.example.com/api/v1").unwrap();
        let engine = SyncEngine::new(api, index.clone());

        std::fs::write(&local_path, b"local workstation edit").unwrap();
        assert!(engine
            .reconcile_local_path(root_node_id, Path::new("report.txt"))
            .unwrap());
        let original_operation = index
            .list_operations(root_node_id)
            .unwrap()
            .into_iter()
            .find(|operation| operation.node_id == Some(node_id))
            .unwrap();
        let change = SyncChange {
            sequence: 2,
            change_type: "version_created".to_string(),
            node_id,
            space_id,
            parent_id: Some(root_node_id),
            node_type: Some("file".to_string()),
            name: Some("report.txt".to_string()),
            current_version_id: Some(new_version_id),
            permission_version: Some(1),
            tombstone: false,
            client_operation_id: None,
            changed_at: Utc::now(),
        };

        assert_eq!(
            engine.apply_remote_change(root_node_id, &change).unwrap(),
            1
        );

        let conflicts = index.list_conflicts(root_node_id).unwrap();
        assert_eq!(conflicts.len(), 1);
        assert_eq!(conflicts[0].kind, "both_modified");
        let conflict_relative_path =
            PathBuf::from(conflicts[0].conflict_relative_path.as_deref().unwrap());
        assert_eq!(
            std::fs::read(root_path.join(&conflict_relative_path)).unwrap(),
            b"local workstation edit"
        );
        assert!(!local_path.exists());
        let operations = index.list_operations(root_node_id).unwrap();
        let conflicted = operations
            .iter()
            .find(|operation| operation.id == original_operation.id)
            .unwrap();
        assert_eq!(conflicted.status, PendingOperationStatus::Conflict);
        assert_eq!(
            conflicted.error_code.as_deref(),
            Some("FILE_VERSION_CONFLICT")
        );
        assert!(operations.iter().any(|operation| {
            operation.node_id.is_none()
                && operation.action == PendingOperationAction::UploadFile
                && operation.relative_path == path_key(&conflict_relative_path)
                && operation.status == PendingOperationStatus::Queued
        }));
        assert!(index.list_transfers().unwrap().iter().any(|task| {
            task.root_node_id == Some(root_node_id)
                && task.node_id == Some(node_id)
                && task.current_version_id == Some(new_version_id)
                && task.status == TransferStatus::Queued
        }));
    }

    #[test]
    fn sprint8_directory_move_and_rename_conflict_preserves_tree_and_cancels_operation() {
        let directory = tempfile::tempdir().unwrap();
        let root_path = directory.path().join("root");
        let index = LocalIndex::open_in_memory().unwrap();
        let (space_id, root_node_id) = configure_root(&index, &root_path, "Laptop");
        let source_parent_id = Uuid::new_v4();
        let local_parent_id = Uuid::new_v4();
        let remote_parent_id = Uuid::new_v4();
        let folder_node_id = Uuid::new_v4();
        for (name, node_id) in [
            ("source", source_parent_id),
            ("local", local_parent_id),
            ("remote", remote_parent_id),
        ] {
            let path = root_path.join(name);
            std::fs::create_dir_all(&path).unwrap();
            index
                .upsert_sync_entry(&synced_entry(
                    root_node_id,
                    node_id,
                    name,
                    SyncEntryKind::Folder,
                    None,
                    &path,
                ))
                .unwrap();
        }
        let original_relative_path = Path::new("source/team");
        let original_path = root_path.join(original_relative_path);
        std::fs::create_dir_all(&original_path).unwrap();
        std::fs::write(original_path.join("nested.txt"), b"local tree").unwrap();
        index
            .upsert_sync_entry(&synced_entry(
                root_node_id,
                folder_node_id,
                "source/team",
                SyncEntryKind::Folder,
                None,
                &original_path,
            ))
            .unwrap();
        let api = ApiClient::new("https://drive.example.com/api/v1").unwrap();
        let engine = SyncEngine::new(api, index.clone());
        let local_relative_path = Path::new("local/team-local");
        std::fs::rename(&original_path, root_path.join(local_relative_path)).unwrap();
        engine
            .record_local_rename(root_node_id, original_relative_path, local_relative_path)
            .unwrap();
        let original_operation = index
            .list_operations(root_node_id)
            .unwrap()
            .into_iter()
            .find(|operation| operation.node_id == Some(folder_node_id))
            .unwrap();
        assert_eq!(original_operation.action, PendingOperationAction::Move);
        let change = SyncChange {
            sequence: 3,
            change_type: "moved".to_string(),
            node_id: folder_node_id,
            space_id,
            parent_id: Some(remote_parent_id),
            node_type: Some("folder".to_string()),
            name: Some("team-remote".to_string()),
            current_version_id: None,
            permission_version: Some(1),
            tombstone: false,
            client_operation_id: None,
            changed_at: Utc::now(),
        };

        assert_eq!(
            engine.apply_remote_change(root_node_id, &change).unwrap(),
            1
        );

        let conflicted = index
            .list_operations(root_node_id)
            .unwrap()
            .into_iter()
            .find(|operation| operation.id == original_operation.id)
            .unwrap();
        assert_eq!(conflicted.status, PendingOperationStatus::Conflict);
        assert_eq!(conflicted.error_code.as_deref(), Some("SYNC_PATH_CONFLICT"));
        let conflict = index
            .list_conflicts(root_node_id)
            .unwrap()
            .into_iter()
            .next()
            .unwrap();
        assert_eq!(conflict.kind, "rename_move_conflict");
        let conflict_path = root_path.join(conflict.conflict_relative_path.as_deref().unwrap());
        assert_eq!(
            std::fs::read(conflict_path.join("nested.txt")).unwrap(),
            b"local tree"
        );
        assert!(root_path.join("remote/team-remote").is_dir());
        assert!(!root_path.join(local_relative_path).exists());
    }

    #[tokio::test]
    async fn sprint8_revoked_device_stops_all_roots_watchers_operations_and_transfers() {
        let directory = tempfile::tempdir().unwrap();
        let index = LocalIndex::open_in_memory().unwrap();
        let (base_url, server) = spawn_api_error_server("DEVICE_SESSION_REVOKED");
        let api = ApiClient::new(&base_url).unwrap();
        api.set_device_token(Some("revoked-device-token".to_string()));
        let engine = SyncEngine::new(api.clone(), index.clone());
        let mut roots = Vec::new();
        for number in 1..=2 {
            let root_path = directory.path().join(format!("root-{number}"));
            let (space_id, root_node_id) =
                configure_root(&index, &root_path, &format!("Laptop-{number}"));
            let node_id = Uuid::new_v4();
            let local_path = root_path.join("pending.txt");
            std::fs::write(&local_path, b"pending").unwrap();
            index
                .upsert_sync_entry(&synced_entry(
                    root_node_id,
                    node_id,
                    "pending.txt",
                    SyncEntryKind::File,
                    Some(Uuid::new_v4()),
                    &local_path,
                ))
                .unwrap();
            let operation = pending_operation(
                root_node_id,
                PendingOperationAction::UploadFile,
                Path::new("pending.txt"),
                None,
                Some(node_id),
                Some(root_node_id),
                Some(Uuid::new_v4()),
                serde_json::json!({}),
            )
            .unwrap();
            index.enqueue_operation(&operation).unwrap();
            let transfer = engine
                .transfer_manager()
                .enqueue_sync_download(
                    root_node_id,
                    node_id,
                    Some(Uuid::new_v4()),
                    root_path.join("remote.bin"),
                )
                .unwrap();
            engine.start_watcher(root_node_id).unwrap();
            roots.push((
                space_id,
                root_node_id,
                node_id,
                operation.client_operation_id,
                transfer.id,
            ));
        }

        let error = engine.run_root_once(roots[0].1).await.unwrap_err();

        server.join().unwrap();
        assert_eq!(error_code(&error), "DEVICE_SESSION_REVOKED");
        assert!(api.device_token().is_none());
        assert!(engine.watcher_status().is_empty());
        for (_, root_node_id, node_id, operation_id, transfer_id) in roots {
            assert!(!index.get_sync_root(root_node_id).unwrap().unwrap().enabled);
            let entry = index
                .get_sync_entry_by_node(root_node_id, node_id)
                .unwrap()
                .unwrap();
            assert_eq!(entry.status, SyncEntryStatus::PermissionRevoked);
            assert_eq!(
                entry.last_error_code.as_deref(),
                Some("DEVICE_SESSION_REVOKED")
            );
            let operation = index
                .get_operation_by_client_id(&operation_id)
                .unwrap()
                .unwrap();
            assert_eq!(operation.status, PendingOperationStatus::Failed);
            assert_eq!(
                operation.error_code.as_deref(),
                Some("DEVICE_SESSION_REVOKED")
            );
            let transfer = index.get_transfer(transfer_id).unwrap().unwrap();
            assert_eq!(transfer.status, TransferStatus::Failed);
            assert_eq!(
                transfer.error_code.as_deref(),
                Some("DEVICE_SESSION_REVOKED")
            );
        }
    }
}
