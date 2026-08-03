use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, Instant};

use chrono::{Duration as ChronoDuration, Utc};
use drive_api_client::{
    ApiClient, ApiClientError, CompleteUploadPart, CompleteUploadRequest, ConfirmUploadPartRequest,
    DownloadUrlResponse, InitUploadRequest, InitUploadResponse,
};
use drive_local_index::{
    ConfirmedPart, IndexError, LocalIndex, TransferDirection, TransferStatus, TransferTask,
};
use drive_platform::atomic_replace;
use futures_util::StreamExt;
use parking_lot::{Mutex, RwLock};
use reqwest::header::{ETAG, RANGE};
use sha2::{Digest, Sha256};
use thiserror::Error;
use tokio::io::{AsyncReadExt, AsyncSeekExt, AsyncWriteExt};
use uuid::Uuid;

pub type Result<T> = std::result::Result<T, TransferError>;

#[derive(Debug, Error)]
pub enum TransferError {
    #[error(transparent)]
    Api(#[from] ApiClientError),
    #[error(transparent)]
    Index(#[from] IndexError),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Platform(#[from] drive_platform::PlatformError),
    #[error("HTTPS transfer failed: {0}")]
    Http(#[from] reqwest::Error),
    #[error("transfer task was not found")]
    TaskNotFound,
    #[error("transfer task is missing {0}")]
    MissingField(&'static str),
    #[error("pre-signed HTTPS request returned HTTP {0}")]
    HttpStatus(u16),
    #[error("upload response did not contain an ETag")]
    MissingEtag,
    #[error("download hash mismatch")]
    HashMismatch,
    #[error("transfer was paused")]
    Paused,
    #[error("transfer was cancelled")]
    Cancelled,
}

impl TransferError {
    pub fn code(&self) -> String {
        match self {
            Self::Api(error) => error
                .api_code()
                .map(ToOwned::to_owned)
                .unwrap_or_else(|| "API_ERROR".to_string()),
            Self::Index(_) => "LOCAL_INDEX_ERROR".to_string(),
            Self::Io(_) | Self::Platform(_) => "LOCAL_IO_ERROR".to_string(),
            Self::Http(_) | Self::HttpStatus(_) | Self::MissingEtag => {
                "HTTPS_TRANSFER_ERROR".to_string()
            }
            Self::TaskNotFound => "TRANSFER_TASK_NOT_FOUND".to_string(),
            Self::MissingField(_) => "TRANSFER_TASK_INVALID".to_string(),
            Self::HashMismatch => "DOWNLOAD_HASH_MISMATCH".to_string(),
            Self::Paused => "TRANSFER_PAUSED".to_string(),
            Self::Cancelled => "TRANSFER_CANCELLED".to_string(),
        }
    }

    pub fn is_retryable(&self) -> bool {
        match self {
            Self::Api(ApiClientError::Transport(_)) | Self::Http(_) => true,
            Self::HttpStatus(status) => {
                matches!(status, 408 | 425 | 429) || (500..=599).contains(status)
            }
            Self::HashMismatch => true,
            _ => false,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ControlState {
    Running,
    Paused,
    Cancelled,
}

#[derive(Debug, Clone, Copy)]
pub struct TransferLimits {
    pub bandwidth_limit_bps: Option<u64>,
    pub max_concurrent_transfers: usize,
}

impl Default for TransferLimits {
    fn default() -> Self {
        Self {
            bandwidth_limit_bps: None,
            max_concurrent_transfers: 4,
        }
    }
}

#[derive(Clone)]
pub struct TransferManager {
    api: ApiClient,
    index: LocalIndex,
    controls: Arc<Mutex<HashMap<Uuid, ControlState>>>,
    limits: Arc<RwLock<TransferLimits>>,
}

impl TransferManager {
    pub fn new(api: ApiClient, index: LocalIndex) -> Self {
        Self {
            api,
            index,
            controls: Arc::new(Mutex::new(HashMap::new())),
            limits: Arc::new(RwLock::new(TransferLimits::default())),
        }
    }

    pub fn set_limits(&self, limits: TransferLimits) {
        *self.limits.write() = TransferLimits {
            bandwidth_limit_bps: limits.bandwidth_limit_bps.filter(|value| *value > 0),
            max_concurrent_transfers: limits.max_concurrent_transfers.clamp(1, 16),
        };
    }

    pub fn enqueue_upload(
        &self,
        local_path: impl AsRef<Path>,
        space_id: Uuid,
        parent_id: Uuid,
    ) -> Result<TransferTask> {
        let local_path = local_path.as_ref();
        let size_bytes = i64::try_from(std::fs::metadata(local_path)?.len())
            .map_err(|_| TransferError::MissingField("representable file size"))?;
        let task = new_task(
            None,
            TransferDirection::Upload,
            local_path,
            None,
            Some(space_id),
            Some(parent_id),
            None,
            None,
            None,
            size_bytes,
        );
        self.index.enqueue_transfer(&task)?;
        self.controls.lock().insert(task.id, ControlState::Running);
        Ok(task)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn enqueue_sync_upload(
        &self,
        local_path: impl AsRef<Path>,
        root_node_id: Uuid,
        space_id: Uuid,
        parent_id: Uuid,
        node_id: Option<Uuid>,
        expected_current_version_id: Option<Uuid>,
        client_operation_id: &str,
    ) -> Result<TransferTask> {
        let local_path = local_path.as_ref();
        let size_bytes = i64::try_from(std::fs::metadata(local_path)?.len())
            .map_err(|_| TransferError::MissingField("representable file size"))?;
        let mut task = new_task(
            Some(root_node_id),
            TransferDirection::Upload,
            local_path,
            None,
            Some(space_id),
            Some(parent_id),
            node_id,
            expected_current_version_id,
            None,
            size_bytes,
        );
        task.client_operation_id = client_operation_id.to_string();
        self.index.enqueue_transfer(&task)?;
        self.controls.lock().insert(task.id, ControlState::Running);
        Ok(task)
    }

    pub fn enqueue_download(
        &self,
        node_id: Uuid,
        destination: impl AsRef<Path>,
    ) -> Result<TransferTask> {
        let destination = destination.as_ref();
        let temp_path = partial_path(destination);
        let task = new_task(
            None,
            TransferDirection::Download,
            destination,
            Some(&temp_path),
            None,
            None,
            Some(node_id),
            None,
            None,
            0,
        );
        self.index.enqueue_transfer(&task)?;
        self.controls.lock().insert(task.id, ControlState::Running);
        Ok(task)
    }

    pub fn enqueue_sync_download(
        &self,
        root_node_id: Uuid,
        node_id: Uuid,
        current_version_id: Option<Uuid>,
        destination: impl AsRef<Path>,
    ) -> Result<TransferTask> {
        let destination = destination.as_ref();
        let temp_path = partial_path(destination);
        let task = new_task(
            Some(root_node_id),
            TransferDirection::Download,
            destination,
            Some(&temp_path),
            None,
            None,
            Some(node_id),
            None,
            current_version_id,
            0,
        );
        self.index.enqueue_transfer(&task)?;
        self.controls.lock().insert(task.id, ControlState::Running);
        Ok(task)
    }

    pub fn list(&self) -> Result<Vec<TransferTask>> {
        Ok(self.index.list_transfers()?)
    }

    pub fn recover_automatic(&self) -> Result<usize> {
        Ok(self.index.recover_automatic_transfers()?)
    }

    pub async fn run_ready(&self) -> Vec<Result<TransferTask>> {
        let limits = *self.limits.read();
        let tasks = match self
            .index
            .list_runnable_transfers(Utc::now(), limits.max_concurrent_transfers)
        {
            Ok(tasks) => tasks,
            Err(error) => return vec![Err(error.into())],
        };
        futures_util::stream::iter(tasks)
            .map(|task| {
                let manager = self.clone();
                async move { manager.run(task.id).await }
            })
            .buffer_unordered(limits.max_concurrent_transfers)
            .collect()
            .await
    }

    pub async fn run_ready_for_root(&self, root_node_id: Uuid) -> Vec<Result<TransferTask>> {
        let limits = *self.limits.read();
        let tasks = match self.index.list_runnable_transfers_for_root(
            root_node_id,
            Utc::now(),
            limits.max_concurrent_transfers,
        ) {
            Ok(tasks) => tasks,
            Err(error) => return vec![Err(error.into())],
        };
        futures_util::stream::iter(tasks)
            .map(|task| {
                let manager = self.clone();
                async move { manager.run(task.id).await }
            })
            .buffer_unordered(limits.max_concurrent_transfers)
            .collect()
            .await
    }

    pub fn pause(&self, task_id: Uuid) -> Result<TransferTask> {
        let task = self.task(task_id)?;
        if !is_terminal(task.status) {
            self.controls.lock().insert(task_id, ControlState::Paused);
            self.index.update_transfer(
                task_id,
                TransferStatus::Paused,
                task.transferred_bytes,
                task.session_id,
                task.content_hash.as_deref(),
                None,
                task.temp_path.as_deref(),
            )?;
        }
        self.task(task_id)
    }

    pub fn resume(&self, task_id: Uuid) -> Result<TransferTask> {
        let task = self.task(task_id)?;
        if matches!(task.status, TransferStatus::Paused | TransferStatus::Failed) {
            self.controls.lock().insert(task_id, ControlState::Running);
            self.index.update_transfer(
                task_id,
                TransferStatus::Queued,
                task.transferred_bytes,
                task.session_id,
                task.content_hash.as_deref(),
                None,
                task.temp_path.as_deref(),
            )?;
        }
        self.task(task_id)
    }

    pub async fn cancel(&self, task_id: Uuid) -> Result<TransferTask> {
        let task = self.task(task_id)?;
        self.controls
            .lock()
            .insert(task_id, ControlState::Cancelled);
        let abort_result = if task.direction == TransferDirection::Upload {
            if let Some(session_id) = task.session_id {
                self.api
                    .abort_upload(session_id, &operation_id(&task, "abort"))
                    .await
                    .map(|_| ())
                    .map_err(TransferError::from)
            } else {
                Ok(())
            }
        } else {
            Ok(())
        };
        self.index.update_transfer(
            task_id,
            TransferStatus::Cancelled,
            task.transferred_bytes,
            task.session_id,
            task.content_hash.as_deref(),
            None,
            task.temp_path.as_deref(),
        )?;
        abort_result?;
        self.task(task_id)
    }

    pub async fn run(&self, task_id: Uuid) -> Result<TransferTask> {
        let task = self.task(task_id)?;
        if is_terminal(task.status) {
            return Ok(task);
        }
        self.controls.lock().insert(task_id, ControlState::Running);
        self.index.update_transfer(
            task_id,
            TransferStatus::Running,
            task.transferred_bytes,
            task.session_id,
            task.content_hash.as_deref(),
            None,
            task.temp_path.as_deref(),
        )?;

        let result = match task.direction {
            TransferDirection::Upload => self.run_upload(&task).await,
            TransferDirection::Download => self.run_download(&task).await,
        };
        match result {
            Ok(()) => self.task(task_id),
            Err(TransferError::Paused) => {
                let current = self.task(task_id)?;
                self.index.update_transfer(
                    task_id,
                    TransferStatus::Paused,
                    current.transferred_bytes,
                    current.session_id,
                    current.content_hash.as_deref(),
                    None,
                    current.temp_path.as_deref(),
                )?;
                self.task(task_id)
            }
            Err(TransferError::Cancelled) => self.cancel(task_id).await,
            Err(error) => {
                let current = self.task(task_id)?;
                let code = error.code();
                if current.root_node_id.is_some() && error.is_retryable() && current.retry_count < 8
                {
                    let retry_count = current.retry_count + 1;
                    self.index.schedule_transfer_retry(
                        task_id,
                        retry_count,
                        Utc::now() + retry_delay(retry_count),
                        &code,
                    )?;
                    return self.task(task_id);
                }
                self.index.update_transfer(
                    task_id,
                    TransferStatus::Failed,
                    current.transferred_bytes,
                    current.session_id,
                    current.content_hash.as_deref(),
                    Some(&code),
                    current.temp_path.as_deref(),
                )?;
                Err(error)
            }
        }
    }

    async fn run_upload(&self, task: &TransferTask) -> Result<()> {
        self.check_control(task.id)?;
        let path = Path::new(&task.local_path);
        let file_name = path
            .file_name()
            .and_then(|value| value.to_str())
            .ok_or(TransferError::MissingField("UTF-8 file name"))?
            .to_string();
        let size_bytes = i64::try_from(tokio::fs::metadata(path).await?.len())
            .map_err(|_| TransferError::MissingField("representable file size"))?;
        let content_hash = sha256_file(path).await?;
        self.index.update_transfer_descriptor(
            task.id,
            None,
            None,
            Some(size_bytes),
            Some(&content_hash),
            None,
        )?;

        let response = self
            .api
            .init_upload(
                &InitUploadRequest {
                    space_id: task
                        .space_id
                        .ok_or(TransferError::MissingField("space_id"))?,
                    parent_id: task
                        .parent_id
                        .ok_or(TransferError::MissingField("parent_id"))?,
                    file_name,
                    size_bytes,
                    content_hash: content_hash.clone(),
                    hash_algo: "sha256".to_string(),
                    mime_type: None,
                    conflict_policy: "fail".to_string(),
                    target_node_id: task.node_id,
                    expected_current_version_id: task.expected_current_version_id,
                },
                &operation_id(task, "init"),
            )
            .await?;

        match response {
            InitUploadResponse::Instant {
                node_id,
                version_id,
                ..
            } => {
                self.index.update_transfer_descriptor(
                    task.id,
                    Some(node_id),
                    None,
                    Some(size_bytes),
                    Some(&content_hash),
                    None,
                )?;
                self.index.update_transfer_versions(
                    task.id,
                    task.expected_current_version_id,
                    Some(version_id),
                )?;
                self.index.update_transfer(
                    task.id,
                    TransferStatus::Completed,
                    size_bytes,
                    None,
                    Some(&content_hash),
                    None,
                    None,
                )?;
                Ok(())
            }
            InitUploadResponse::Multipart {
                session_id,
                part_size_bytes,
                total_parts,
                max_parallelism,
                ..
            } => {
                self.index.update_transfer_descriptor(
                    task.id,
                    None,
                    Some(session_id),
                    Some(size_bytes),
                    Some(&content_hash),
                    None,
                )?;
                self.upload_parts(
                    task,
                    path,
                    session_id,
                    size_bytes,
                    part_size_bytes,
                    total_parts,
                    max_parallelism,
                    &content_hash,
                )
                .await
            }
        }
    }

    #[allow(clippy::too_many_arguments)]
    async fn upload_parts(
        &self,
        task: &TransferTask,
        path: &Path,
        session_id: Uuid,
        size_bytes: i64,
        part_size_bytes: i64,
        total_parts: i32,
        max_parallelism: i32,
        content_hash: &str,
    ) -> Result<()> {
        let status = self.api.upload_status(session_id).await?;
        if status.status == "completed" {
            let node_id = status
                .completed_node_id
                .ok_or(TransferError::MissingField("completed_node_id"))?;
            let version_id = status
                .completed_version_id
                .ok_or(TransferError::MissingField("completed_version_id"))?;
            self.finish_upload(
                task,
                session_id,
                node_id,
                version_id,
                size_bytes,
                content_hash,
            )?;
            return Ok(());
        }

        let uploaded_on_server = status.uploaded_parts;
        let mut confirmed = self
            .index
            .confirmed_parts(task.id)?
            .into_iter()
            .filter(|part| uploaded_on_server.contains(&part.part_no))
            .map(|part| (part.part_no, part))
            .collect::<BTreeMap<_, _>>();
        let missing = (1..=total_parts)
            .filter(|part_no| !confirmed.contains_key(part_no))
            .collect::<Vec<_>>();
        let batch_size = usize::try_from(max_parallelism.clamp(1, 16) * 2)
            .unwrap_or(2)
            .min(32);
        let mut bandwidth = BandwidthLimiter::new(self.limits.read().bandwidth_limit_bps);

        for part_numbers in missing.chunks(batch_size) {
            self.check_control(task.id)?;
            let presigned = self.api.presign_parts(session_id, part_numbers).await?;
            for part in presigned.items {
                self.check_control(task.id)?;
                let body = read_part(path, part.part_no, part_size_bytes, size_bytes).await?;
                let part_size = i64::try_from(body.len())
                    .map_err(|_| TransferError::MissingField("representable part size"))?;
                let mut request = self.api.http_client().put(&part.upload_url);
                for (name, value) in part.headers {
                    request = request.header(name, value);
                }
                let response = request.body(body).send().await?;
                if !response.status().is_success() {
                    return Err(TransferError::HttpStatus(response.status().as_u16()));
                }
                bandwidth
                    .account(u64::try_from(part_size).unwrap_or(u64::MAX))
                    .await;
                let etag = response
                    .headers()
                    .get(ETAG)
                    .and_then(|value| value.to_str().ok())
                    .map(ToOwned::to_owned)
                    .ok_or(TransferError::MissingEtag)?;
                self.api
                    .confirm_part(
                        session_id,
                        part.part_no,
                        &ConfirmUploadPartRequest {
                            etag: etag.clone(),
                            size_bytes: part_size,
                        },
                    )
                    .await?;
                let confirmed_part = ConfirmedPart {
                    task_id: task.id,
                    part_no: part.part_no,
                    etag,
                    size_bytes: part_size,
                };
                self.index.save_confirmed_part(&confirmed_part)?;
                confirmed.insert(part.part_no, confirmed_part);
                let transferred_bytes = confirmed.values().map(|item| item.size_bytes).sum();
                self.index.update_transfer(
                    task.id,
                    TransferStatus::Running,
                    transferred_bytes,
                    Some(session_id),
                    Some(content_hash),
                    None,
                    None,
                )?;
            }
        }

        self.check_control(task.id)?;
        let parts = confirmed
            .into_values()
            .map(|part| CompleteUploadPart {
                part_no: part.part_no,
                etag: part.etag,
                size_bytes: Some(part.size_bytes),
            })
            .collect::<Vec<_>>();
        let completed = self
            .api
            .complete_upload(
                session_id,
                &CompleteUploadRequest { parts },
                &operation_id(task, "complete"),
            )
            .await?;
        self.finish_upload(
            task,
            session_id,
            completed.node_id,
            completed.version_id,
            size_bytes,
            content_hash,
        )
    }

    fn finish_upload(
        &self,
        task: &TransferTask,
        session_id: Uuid,
        node_id: Uuid,
        version_id: Uuid,
        size_bytes: i64,
        content_hash: &str,
    ) -> Result<()> {
        self.index.update_transfer_descriptor(
            task.id,
            Some(node_id),
            Some(session_id),
            Some(size_bytes),
            Some(content_hash),
            None,
        )?;
        self.index.update_transfer_versions(
            task.id,
            task.expected_current_version_id,
            Some(version_id),
        )?;
        self.index.update_transfer(
            task.id,
            TransferStatus::Completed,
            size_bytes,
            Some(session_id),
            Some(content_hash),
            None,
            None,
        )?;
        Ok(())
    }

    async fn run_download(&self, task: &TransferTask) -> Result<()> {
        self.check_control(task.id)?;
        let node_id = task.node_id.ok_or(TransferError::MissingField("node_id"))?;
        let descriptor = self.api.download_url(node_id).await?;
        let destination = Path::new(&task.local_path);
        let temp_path = task
            .temp_path
            .as_deref()
            .map(PathBuf::from)
            .unwrap_or_else(|| partial_path(destination));
        let expected_size = u64::try_from(descriptor.size_bytes)
            .map_err(|_| TransferError::MissingField("non-negative download size"))?;
        if let Some(parent) = destination.parent() {
            tokio::fs::create_dir_all(parent).await?;
        }
        let partial_len = tokio::fs::metadata(&temp_path)
            .await
            .ok()
            .map(|metadata| metadata.len());
        let trusted_offset = trusted_download_offset(task, &descriptor, partial_len);
        let reset_progress =
            trusted_offset.is_none() || (partial_len.is_none() && task.transferred_bytes != 0);
        if trusted_offset.is_none() {
            remove_partial_file(&temp_path).await?;
        }
        self.index.update_transfer_descriptor(
            task.id,
            Some(node_id),
            None,
            Some(descriptor.size_bytes),
            Some(&descriptor.content_hash),
            Some(&temp_path.to_string_lossy()),
        )?;
        self.index
            .update_transfer_versions(task.id, None, Some(descriptor.version_id))?;
        if reset_progress {
            self.index.update_transfer(
                task.id,
                TransferStatus::Running,
                0,
                None,
                Some(&descriptor.content_hash),
                None,
                Some(&temp_path.to_string_lossy()),
            )?;
        }

        let mut offset = trusted_offset.unwrap_or(0);
        if offset < expected_size {
            let mut request = self.api.http_client().get(&descriptor.download_url);
            for (name, value) in descriptor.headers {
                request = request.header(name, value);
            }
            if offset > 0 {
                request = request.header(RANGE, format!("bytes={offset}-"));
            }
            let response = request.send().await?;
            if offset > 0 && response.status() == reqwest::StatusCode::OK {
                offset = 0;
                self.index.update_transfer(
                    task.id,
                    TransferStatus::Running,
                    0,
                    None,
                    Some(&descriptor.content_hash),
                    None,
                    Some(&temp_path.to_string_lossy()),
                )?;
            } else if !response.status().is_success() {
                return Err(TransferError::HttpStatus(response.status().as_u16()));
            }

            let mut options = tokio::fs::OpenOptions::new();
            options.create(true).write(true);
            if offset == 0 {
                options.truncate(true);
            } else {
                options.append(true);
            }
            let mut file = options.open(&temp_path).await?;
            let mut stream = response.bytes_stream();
            let mut transferred = i64::try_from(offset).unwrap_or(i64::MAX);
            let mut bandwidth = BandwidthLimiter::new(self.limits.read().bandwidth_limit_bps);
            while let Some(chunk) = stream.next().await {
                self.check_control(task.id)?;
                let chunk = chunk?;
                file.write_all(&chunk).await?;
                bandwidth
                    .account(u64::try_from(chunk.len()).unwrap_or(u64::MAX))
                    .await;
                transferred = transferred.saturating_add(i64::try_from(chunk.len()).unwrap_or(0));
                self.index.update_transfer(
                    task.id,
                    TransferStatus::Running,
                    transferred,
                    None,
                    Some(&descriptor.content_hash),
                    None,
                    Some(&temp_path.to_string_lossy()),
                )?;
            }
            file.flush().await?;
        } else if !tokio::fs::try_exists(&temp_path).await? {
            tokio::fs::File::create(&temp_path).await?;
        }

        self.check_control(task.id)?;
        let actual_hash = sha256_file(&temp_path).await?;
        if !actual_hash.eq_ignore_ascii_case(&descriptor.content_hash) {
            remove_partial_file(&temp_path).await?;
            self.index.update_transfer(
                task.id,
                TransferStatus::Running,
                0,
                None,
                Some(&descriptor.content_hash),
                None,
                Some(&temp_path.to_string_lossy()),
            )?;
            return Err(TransferError::HashMismatch);
        }
        atomic_replace(&temp_path, destination)?;
        self.index.update_transfer(
            task.id,
            TransferStatus::Completed,
            descriptor.size_bytes,
            None,
            Some(&descriptor.content_hash),
            None,
            Some(&temp_path.to_string_lossy()),
        )?;
        Ok(())
    }

    fn check_control(&self, task_id: Uuid) -> Result<()> {
        match self
            .controls
            .lock()
            .get(&task_id)
            .copied()
            .unwrap_or(ControlState::Running)
        {
            ControlState::Running => Ok(()),
            ControlState::Paused => Err(TransferError::Paused),
            ControlState::Cancelled => Err(TransferError::Cancelled),
        }
    }

    fn task(&self, task_id: Uuid) -> Result<TransferTask> {
        self.index
            .get_transfer(task_id)?
            .ok_or(TransferError::TaskNotFound)
    }
}

struct BandwidthLimiter {
    limit_bps: Option<u64>,
    started_at: Instant,
    transferred: u64,
}

impl BandwidthLimiter {
    fn new(limit_bps: Option<u64>) -> Self {
        Self {
            limit_bps: limit_bps.filter(|value| *value > 0),
            started_at: Instant::now(),
            transferred: 0,
        }
    }

    async fn account(&mut self, bytes: u64) {
        let Some(limit_bps) = self.limit_bps else {
            return;
        };
        self.transferred = self.transferred.saturating_add(bytes);
        let expected = Duration::from_secs_f64(self.transferred as f64 / limit_bps as f64);
        if let Some(delay) = expected.checked_sub(self.started_at.elapsed()) {
            tokio::time::sleep(delay).await;
        }
    }
}

fn retry_delay(retry_count: u32) -> ChronoDuration {
    let seconds = 2_i64.saturating_pow(retry_count.min(8)).clamp(2, 300);
    ChronoDuration::seconds(seconds)
}

#[allow(clippy::too_many_arguments)]
fn new_task(
    root_node_id: Option<Uuid>,
    direction: TransferDirection,
    local_path: &Path,
    temp_path: Option<&Path>,
    space_id: Option<Uuid>,
    parent_id: Option<Uuid>,
    node_id: Option<Uuid>,
    expected_current_version_id: Option<Uuid>,
    current_version_id: Option<Uuid>,
    size_bytes: i64,
) -> TransferTask {
    let now = Utc::now();
    TransferTask {
        id: Uuid::new_v4(),
        root_node_id,
        direction,
        status: TransferStatus::Queued,
        local_path: local_path.to_string_lossy().into_owned(),
        temp_path: temp_path.map(|path| path.to_string_lossy().into_owned()),
        space_id,
        parent_id,
        node_id,
        expected_current_version_id,
        current_version_id,
        session_id: None,
        size_bytes,
        transferred_bytes: 0,
        content_hash: None,
        client_operation_id: Uuid::new_v4().to_string(),
        retry_count: 0,
        next_attempt_at: None,
        error_code: None,
        created_at: now,
        updated_at: now,
    }
}

fn operation_id(task: &TransferTask, stage: &str) -> String {
    format!("{}:{stage}", task.client_operation_id)
}

fn is_terminal(status: TransferStatus) -> bool {
    matches!(
        status,
        TransferStatus::Completed | TransferStatus::Cancelled
    )
}

fn partial_path(destination: &Path) -> PathBuf {
    let mut value = destination.as_os_str().to_os_string();
    value.push(".drivepart");
    PathBuf::from(value)
}

fn trusted_download_offset(
    task: &TransferTask,
    descriptor: &DownloadUrlResponse,
    partial_len: Option<u64>,
) -> Option<u64> {
    let Some(partial_len) = partial_len else {
        return Some(0);
    };
    let expected_size = u64::try_from(descriptor.size_bytes).ok()?;
    let persisted_bytes = u64::try_from(task.transferred_bytes).ok()?;
    if task.current_version_id != Some(descriptor.version_id)
        || task.content_hash.as_deref() != Some(descriptor.content_hash.as_str())
        || persisted_bytes != partial_len
        || partial_len > expected_size
    {
        return None;
    }
    Some(partial_len)
}

async fn remove_partial_file(path: &Path) -> Result<()> {
    match tokio::fs::remove_file(path).await {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error.into()),
    }
}

async fn read_part(
    path: &Path,
    part_no: i32,
    part_size_bytes: i64,
    total_size_bytes: i64,
) -> Result<Vec<u8>> {
    let (offset, length) = part_range(part_no, part_size_bytes, total_size_bytes)?;
    let mut file = tokio::fs::File::open(path).await?;
    file.seek(std::io::SeekFrom::Start(offset)).await?;
    let mut buffer = vec![0u8; length];
    file.read_exact(&mut buffer).await?;
    Ok(buffer)
}

fn part_range(part_no: i32, part_size_bytes: i64, total_size_bytes: i64) -> Result<(u64, usize)> {
    if part_no < 1 || part_size_bytes < 1 || total_size_bytes < 1 {
        return Err(TransferError::MissingField("valid multipart range"));
    }
    let offset = i64::from(part_no - 1)
        .checked_mul(part_size_bytes)
        .ok_or(TransferError::MissingField("multipart offset"))?;
    let remaining = total_size_bytes.saturating_sub(offset);
    if remaining <= 0 {
        return Err(TransferError::MissingField("multipart part number"));
    }
    let length = remaining.min(part_size_bytes);
    Ok((
        u64::try_from(offset).map_err(|_| TransferError::MissingField("multipart offset"))?,
        usize::try_from(length).map_err(|_| TransferError::MissingField("multipart part size"))?,
    ))
}

async fn sha256_file(path: &Path) -> Result<String> {
    let mut file = tokio::fs::File::open(path).await?;
    let mut digest = Sha256::new();
    let mut buffer = vec![0u8; 1024 * 1024];
    loop {
        let count = file.read(&mut buffer).await?;
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
    use std::path::Path;
    use std::sync::{Arc, Mutex as StdMutex};
    use std::thread::JoinHandle;

    use chrono::Utc;
    use drive_api_client::{ApiClient, DownloadUrlResponse};
    use drive_local_index::{LocalIndex, TransferDirection, TransferStatus};
    use sha2::{Digest, Sha256};
    use uuid::Uuid;

    use super::{
        new_task, part_range, partial_path, sha256_file, trusted_download_offset, TransferManager,
    };

    type CapturedRanges = Arc<StdMutex<Vec<Option<String>>>>;
    type DownloadServer = (String, CapturedRanges, JoinHandle<()>);

    fn spawn_download_server(
        expected_content: &[u8],
        attempt_bodies: Vec<Vec<u8>>,
        version_id: Uuid,
    ) -> DownloadServer {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let base_url = format!("http://{address}/api/v1");
        let download_url = format!("http://{address}/blob");
        let content_hash = hex::encode(Sha256::digest(expected_content));
        let size_bytes = i64::try_from(expected_content.len()).unwrap();
        let node_id = Uuid::new_v4();
        let ranges = Arc::new(StdMutex::new(Vec::new()));
        let captured_ranges = ranges.clone();
        let handle = std::thread::spawn(move || {
            for body in attempt_bodies {
                let (mut descriptor_stream, _) = listener.accept().unwrap();
                let _ = read_request(&mut descriptor_stream);
                let descriptor = serde_json::json!({
                    "protocol_version": "DTP/1",
                    "client_operation_id": null,
                    "node_id": node_id,
                    "version_id": version_id,
                    "file_name": "download.bin",
                    "size_bytes": size_bytes,
                    "hash_algo": "sha256",
                    "content_hash": content_hash,
                    "mime_type": "application/octet-stream",
                    "download_url": download_url,
                    "expires_at": Utc::now().to_rfc3339(),
                    "headers": {},
                })
                .to_string();
                write_response(
                    &mut descriptor_stream,
                    "200 OK",
                    "application/json",
                    descriptor.as_bytes(),
                );

                let (mut data_stream, _) = listener.accept().unwrap();
                let request = read_request(&mut data_stream);
                let range = request.lines().find_map(|line| {
                    let (name, value) = line.split_once(':')?;
                    name.eq_ignore_ascii_case("range")
                        .then(|| value.trim().to_string())
                });
                captured_ranges.lock().unwrap().push(range.clone());
                let status = if range.is_some() {
                    "206 Partial Content"
                } else {
                    "200 OK"
                };
                write_response(&mut data_stream, status, "application/octet-stream", &body);
            }
        });
        (base_url, ranges, handle)
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

    fn write_response(stream: &mut TcpStream, status: &str, content_type: &str, body: &[u8]) {
        write!(
            stream,
            "HTTP/1.1 {status}\r\nContent-Type: {content_type}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
            body.len()
        )
        .unwrap();
        stream.write_all(body).unwrap();
        stream.flush().unwrap();
    }

    #[test]
    fn one_gib_part_ranges_cover_the_file_without_allocating_it() {
        let gib = 1_073_741_824_i64;
        let part_size = 8 * 1024 * 1024_i64;
        let total_parts = gib / part_size;
        let first = part_range(1, part_size, gib).unwrap();
        let last = part_range(i32::try_from(total_parts).unwrap(), part_size, gib).unwrap();
        assert_eq!(first, (0, usize::try_from(part_size).unwrap()));
        assert_eq!(
            last,
            (
                u64::try_from(gib - part_size).unwrap(),
                usize::try_from(part_size).unwrap()
            )
        );
    }

    #[test]
    fn sprint8_one_gib_interrupted_download_uses_the_persisted_range_without_allocating_it() {
        let gib = 1_073_741_824_i64;
        let persisted = 640 * 1024 * 1024_i64;
        let version_id = Uuid::new_v4();
        let node_id = Uuid::new_v4();
        let content_hash = "ab".repeat(32);
        let mut task = new_task(
            Some(Uuid::new_v4()),
            TransferDirection::Download,
            Path::new("C:\\Drive\\large.bin"),
            Some(Path::new("C:\\Drive\\large.bin.drivepart")),
            None,
            None,
            Some(node_id),
            None,
            Some(version_id),
            gib,
        );
        task.transferred_bytes = persisted;
        task.content_hash = Some(content_hash.clone());
        let descriptor = DownloadUrlResponse {
            protocol_version: "DTP/1".to_string(),
            client_operation_id: None,
            node_id,
            version_id,
            file_name: "large.bin".to_string(),
            size_bytes: gib,
            hash_algo: "sha256".to_string(),
            content_hash,
            mime_type: Some("application/octet-stream".to_string()),
            download_url: "https://download.example.com/large.bin".to_string(),
            expires_at: Utc::now(),
            headers: Default::default(),
        };

        let offset =
            trusted_download_offset(&task, &descriptor, Some(u64::try_from(persisted).unwrap()))
                .unwrap();

        assert_eq!(offset, u64::try_from(persisted).unwrap());
        assert_eq!(format!("bytes={offset}-"), "bytes=671088640-");
    }

    #[tokio::test]
    async fn sprint8_interrupted_download_resumes_after_restart_and_atomically_replaces() {
        let directory = tempfile::tempdir().unwrap();
        let database = directory.path().join("index.sqlite3");
        let destination = directory.path().join("resumed.bin");
        let temp_path = partial_path(&destination);
        let content = b"enterprise-drive-resume";
        let offset = 11_usize;
        let version_id = Uuid::new_v4();
        let node_id = Uuid::new_v4();
        let root_node_id = Uuid::new_v4();
        let content_hash = hex::encode(Sha256::digest(content));
        let (base_url, ranges, server) =
            spawn_download_server(content, vec![content[offset..].to_vec()], version_id);
        let api = ApiClient::new(&base_url).unwrap();
        api.set_device_token(Some("device-token".to_string()));

        let task_id = {
            let index = LocalIndex::open(&database).unwrap();
            let manager = TransferManager::new(api.clone(), index.clone());
            let task = manager
                .enqueue_sync_download(root_node_id, node_id, Some(version_id), &destination)
                .unwrap();
            tokio::fs::write(&temp_path, &content[..offset])
                .await
                .unwrap();
            index
                .update_transfer_descriptor(
                    task.id,
                    Some(node_id),
                    None,
                    Some(i64::try_from(content.len()).unwrap()),
                    Some(&content_hash),
                    Some(&temp_path.to_string_lossy()),
                )
                .unwrap();
            index
                .update_transfer_versions(task.id, None, Some(version_id))
                .unwrap();
            index
                .update_transfer(
                    task.id,
                    TransferStatus::Running,
                    i64::try_from(offset).unwrap(),
                    None,
                    Some(&content_hash),
                    None,
                    Some(&temp_path.to_string_lossy()),
                )
                .unwrap();
            task.id
        };

        let reopened = LocalIndex::open(&database).unwrap();
        assert_eq!(reopened.recover_automatic_transfers().unwrap(), 1);
        let manager = TransferManager::new(api, reopened);
        let completed = manager.run(task_id).await.unwrap();

        server.join().unwrap();
        assert_eq!(completed.status, TransferStatus::Completed);
        assert_eq!(tokio::fs::read(&destination).await.unwrap(), content);
        assert!(!tokio::fs::try_exists(&temp_path).await.unwrap());
        assert_eq!(
            ranges.lock().unwrap().as_slice(),
            &[Some(format!("bytes={offset}-"))]
        );
    }

    #[tokio::test]
    async fn sprint8_stale_partial_from_an_unbound_version_is_discarded_before_download() {
        let directory = tempfile::tempdir().unwrap();
        let destination = directory.path().join("updated.bin");
        let temp_path = partial_path(&destination);
        tokio::fs::write(&temp_path, b"stale-version")
            .await
            .unwrap();
        let content = b"current-remote-version";
        let version_id = Uuid::new_v4();
        let node_id = Uuid::new_v4();
        let (base_url, ranges, server) =
            spawn_download_server(content, vec![content.to_vec()], version_id);
        let api = ApiClient::new(&base_url).unwrap();
        api.set_device_token(Some("device-token".to_string()));
        let index = LocalIndex::open_in_memory().unwrap();
        let manager = TransferManager::new(api, index);
        let task = manager
            .enqueue_sync_download(Uuid::new_v4(), node_id, Some(version_id), &destination)
            .unwrap();

        let completed = manager.run(task.id).await.unwrap();

        server.join().unwrap();
        assert_eq!(completed.status, TransferStatus::Completed);
        assert_eq!(tokio::fs::read(&destination).await.unwrap(), content);
        assert_eq!(ranges.lock().unwrap().as_slice(), &[None]);
    }

    #[tokio::test]
    async fn sprint8_hash_mismatch_removes_partial_and_retries_from_zero() {
        let directory = tempfile::tempdir().unwrap();
        let destination = directory.path().join("retry.bin");
        let temp_path = partial_path(&destination);
        let content = b"verified-download";
        let corrupt = b"corrupted-content".to_vec();
        assert_eq!(corrupt.len(), content.len());
        let version_id = Uuid::new_v4();
        let node_id = Uuid::new_v4();
        let (base_url, ranges, server) =
            spawn_download_server(content, vec![corrupt, content.to_vec()], version_id);
        let api = ApiClient::new(&base_url).unwrap();
        api.set_device_token(Some("device-token".to_string()));
        let index = LocalIndex::open_in_memory().unwrap();
        let manager = TransferManager::new(api, index);
        let task = manager
            .enqueue_sync_download(Uuid::new_v4(), node_id, Some(version_id), &destination)
            .unwrap();

        let retry = manager.run(task.id).await.unwrap();
        assert_eq!(retry.status, TransferStatus::Queued);
        assert_eq!(retry.retry_count, 1);
        assert_eq!(retry.error_code.as_deref(), Some("DOWNLOAD_HASH_MISMATCH"));
        assert_eq!(retry.transferred_bytes, 0);
        assert!(!tokio::fs::try_exists(&temp_path).await.unwrap());

        let completed = manager.run(task.id).await.unwrap();

        server.join().unwrap();
        assert_eq!(completed.status, TransferStatus::Completed);
        assert_eq!(tokio::fs::read(&destination).await.unwrap(), content);
        assert_eq!(ranges.lock().unwrap().as_slice(), &[None, None]);
    }

    #[tokio::test]
    async fn queue_pause_resume_cancel_and_hash_are_persistent() {
        let directory = tempfile::tempdir().unwrap();
        let upload_path = directory.path().join("sample.bin");
        tokio::fs::write(&upload_path, b"enterprise-drive")
            .await
            .unwrap();
        let api = ApiClient::new("https://drive.example.com/api/v1").unwrap();
        let index = LocalIndex::open_in_memory().unwrap();
        let manager = TransferManager::new(api, index);
        let task = manager
            .enqueue_upload(&upload_path, Uuid::new_v4(), Uuid::new_v4())
            .unwrap();

        assert_eq!(
            manager.pause(task.id).unwrap().status,
            TransferStatus::Paused
        );
        assert_eq!(
            manager.resume(task.id).unwrap().status,
            TransferStatus::Queued
        );
        assert_eq!(
            manager.cancel(task.id).await.unwrap().status,
            TransferStatus::Cancelled
        );
        assert_eq!(
            sha256_file(&upload_path).await.unwrap(),
            "6cb0e17c8dc8e26f8005695ffdaf40e5d7727e79796c9211a0332700d7fa4680"
        );
    }
}
