mod bidirectional;

use std::collections::VecDeque;
use std::path::Path;
use std::sync::Arc;

use chrono::Utc;
use drive_api_client::{ApiClient, ApiClientError, FileNode, SyncChange, SyncChangeList};
use drive_local_index::{IndexError, IndexedNode, LocalIndex, SyncRoot};
use drive_platform::{validate_sync_root, PlatformError};
use drive_transfer::{TransferError, TransferManager};
use serde::Serialize;
use thiserror::Error;
use uuid::Uuid;

pub type Result<T> = std::result::Result<T, SyncEngineError>;

#[derive(Debug, Error)]
pub enum SyncEngineError {
    #[error(transparent)]
    Api(#[from] ApiClientError),
    #[error(transparent)]
    Index(#[from] IndexError),
    #[error(transparent)]
    Platform(#[from] PlatformError),
    #[error(transparent)]
    Transfer(#[from] TransferError),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Serialization(#[from] serde_json::Error),
    #[error("sync root is not configured")]
    RootNotConfigured,
    #[error("incremental sync exceeded the page safety limit")]
    PageLimitExceeded,
}

#[derive(Debug, Clone, Serialize)]
pub struct SyncRunSummary {
    pub root_node_id: Uuid,
    pub snapshot_nodes: usize,
    pub applied_changes: usize,
    pub pages: usize,
    pub cursor: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct SyncPageSummary {
    pub root_node_id: Uuid,
    pub applied_changes: usize,
    pub has_more: bool,
    pub cursor: String,
}

#[derive(Clone)]
pub struct SyncEngine {
    pub(crate) api: ApiClient,
    pub(crate) index: LocalIndex,
    pub(crate) transfers: TransferManager,
    pub(crate) runtime: Arc<bidirectional::SyncRuntimeState>,
}

impl SyncEngine {
    pub fn new(api: ApiClient, index: LocalIndex) -> Self {
        let transfers = TransferManager::new(api.clone(), index.clone());
        Self::with_transfers(api, index, transfers)
    }

    pub fn with_transfers(api: ApiClient, index: LocalIndex, transfers: TransferManager) -> Self {
        Self {
            api,
            index,
            transfers,
            runtime: Arc::new(bidirectional::SyncRuntimeState::default()),
        }
    }

    pub fn local_index(&self) -> LocalIndex {
        self.index.clone()
    }

    pub fn transfer_manager(&self) -> TransferManager {
        self.transfers.clone()
    }

    pub async fn initialize_root(
        &self,
        space_id: Uuid,
        root_node_id: Uuid,
        local_path: impl AsRef<Path>,
    ) -> Result<SyncRunSummary> {
        let local_path = validate_sync_root(local_path)?;
        let anchor = self
            .api
            .sync_changes(space_id, root_node_id, None, 1)
            .await?;
        let root = SyncRoot {
            root_node_id,
            space_id,
            local_path: local_path.to_string_lossy().into_owned(),
            cursor: Some(anchor.next_cursor.clone()),
            enabled: true,
            updated_at: Utc::now(),
        };
        self.index.upsert_sync_root(&root)?;

        let snapshot_nodes = self.snapshot_tree(space_id, root_node_id).await?;
        let (applied_changes, pages, cursor) =
            self.pull_until_current(root_node_id, 200, 10_000).await?;
        Ok(SyncRunSummary {
            root_node_id,
            snapshot_nodes,
            applied_changes,
            pages,
            cursor,
        })
    }

    pub async fn pull_once(&self, root_node_id: Uuid, page_size: i32) -> Result<SyncPageSummary> {
        let root = self
            .index
            .get_sync_root(root_node_id)?
            .ok_or(SyncEngineError::RootNotConfigured)?;
        let page = self
            .api
            .sync_changes(
                root.space_id,
                root.root_node_id,
                root.cursor.as_deref(),
                page_size.clamp(1, 200),
            )
            .await?;
        self.apply_page(&page)?;
        Ok(SyncPageSummary {
            root_node_id,
            applied_changes: page.items.len(),
            has_more: page.has_more,
            cursor: page.next_cursor,
        })
    }

    pub fn apply_page(&self, page: &SyncChangeList) -> Result<()> {
        let nodes = page.items.iter().map(change_to_node).collect::<Vec<_>>();
        self.index
            .apply_sync_page(page.root_node_id, &nodes, &page.next_cursor)?;
        Ok(())
    }

    async fn snapshot_tree(&self, space_id: Uuid, root_node_id: Uuid) -> Result<usize> {
        let mut folders = VecDeque::from([root_node_id]);
        let mut indexed = 0usize;
        while let Some(parent_id) = folders.pop_front() {
            let mut cursor = None;
            loop {
                let page = self
                    .api
                    .list_files_page(space_id, Some(parent_id), cursor.as_deref(), 100)
                    .await?;
                let mut nodes = Vec::with_capacity(page.items.len());
                for node in page.items {
                    if node.node_type == "folder" {
                        folders.push_back(node.id);
                    }
                    nodes.push(file_node_to_indexed(node));
                    indexed += 1;
                }
                self.index.upsert_nodes(&nodes)?;
                match page.next_cursor {
                    Some(next_cursor) => cursor = Some(next_cursor),
                    None => break,
                }
            }
        }
        Ok(indexed)
    }

    async fn pull_until_current(
        &self,
        root_node_id: Uuid,
        page_size: i32,
        max_pages: usize,
    ) -> Result<(usize, usize, String)> {
        let mut applied = 0usize;
        for page_number in 1..=max_pages {
            let summary = self.pull_once(root_node_id, page_size).await?;
            applied += summary.applied_changes;
            if !summary.has_more {
                return Ok((applied, page_number, summary.cursor));
            }
        }
        Err(SyncEngineError::PageLimitExceeded)
    }
}

pub use bidirectional::{
    SyncConfiguration, SyncCycleSummary, SyncInitializationSummary, SyncWatcherSummary,
};

fn file_node_to_indexed(node: FileNode) -> IndexedNode {
    IndexedNode {
        node_id: node.id,
        space_id: node.space_id,
        parent_id: node.parent_id,
        node_type: node.node_type,
        name: Some(node.name),
        current_version_id: node.current_version_id,
        permission_version: Some(node.permission_version),
        tombstone: false,
        changed_at: node.updated_at,
    }
}

fn change_to_node(change: &SyncChange) -> IndexedNode {
    IndexedNode {
        node_id: change.node_id,
        space_id: change.space_id,
        parent_id: change.parent_id,
        node_type: change
            .node_type
            .clone()
            .unwrap_or_else(|| "unknown".to_string()),
        name: change.name.clone(),
        current_version_id: change.current_version_id,
        permission_version: change.permission_version,
        tombstone: change.tombstone,
        changed_at: change.changed_at,
    }
}

#[cfg(test)]
mod tests {
    use chrono::Utc;
    use drive_api_client::{ApiClient, SyncChange, SyncChangeList};
    use drive_local_index::{LocalIndex, SyncRoot};
    use uuid::Uuid;

    use super::SyncEngine;

    #[test]
    fn tombstone_and_cursor_are_committed_together() {
        let api = ApiClient::new("https://drive.example.com/api/v1").unwrap();
        let index = LocalIndex::open_in_memory().unwrap();
        let space_id = Uuid::new_v4();
        let root_node_id = Uuid::new_v4();
        let node_id = Uuid::new_v4();
        index
            .upsert_sync_root(&SyncRoot {
                root_node_id,
                space_id,
                local_path: "C:\\Drive".to_string(),
                cursor: Some("before".to_string()),
                enabled: true,
                updated_at: Utc::now(),
            })
            .unwrap();
        let engine = SyncEngine::new(api, index.clone());
        let page = SyncChangeList {
            space_id,
            root_node_id,
            items: vec![SyncChange {
                sequence: 9,
                change_type: "deleted".to_string(),
                node_id,
                space_id,
                parent_id: Some(root_node_id),
                node_type: Some("file".to_string()),
                name: None,
                current_version_id: None,
                permission_version: Some(2),
                tombstone: true,
                client_operation_id: None,
                changed_at: Utc::now(),
            }],
            next_cursor: "after".to_string(),
            has_more: false,
            cursor_expires_at: Utc::now(),
        };

        engine.apply_page(&page).unwrap();

        assert_eq!(
            index
                .get_sync_root(root_node_id)
                .unwrap()
                .unwrap()
                .cursor
                .as_deref(),
            Some("after")
        );
        assert!(index
            .list_children(space_id, root_node_id)
            .unwrap()
            .is_empty());
    }
}
