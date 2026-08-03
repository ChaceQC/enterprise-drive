use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};
use std::sync::Arc;

use chrono::Utc;
use drive_api_client::{
    ApiClient, ApiClientError, CompleteUploadPart, CompleteUploadRequest, ConfirmUploadPartRequest,
    InitUploadRequest, InitUploadResponse,
};
use drive_local_index::{
    ConfirmedPart, IndexError, LocalIndex, TransferDirection, TransferStatus, TransferTask,
};
use futures_util::StreamExt;
use parking_lot::Mutex;
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
            Self::Io(_) => "LOCAL_IO_ERROR".to_string(),
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
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ControlState {
    Running,
    Paused,
    Cancelled,
}

#[derive(Clone)]
pub struct TransferManager {
    api: ApiClient,
    index: LocalIndex,
    controls: Arc<Mutex<HashMap<Uuid, ControlState>>>,
}

impl TransferManager {
    pub fn new(api: ApiClient, index: LocalIndex) -> Self {
        Self {
            api,
            index,
            controls: Arc::new(Mutex::new(HashMap::new())),
        }
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
            TransferDirection::Upload,
            local_path,
            None,
            Some(space_id),
            Some(parent_id),
            None,
            size_bytes,
        );
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
            TransferDirection::Download,
            destination,
            Some(&temp_path),
            None,
            None,
            Some(node_id),
            0,
        );
        self.index.enqueue_transfer(&task)?;
        self.controls.lock().insert(task.id, ControlState::Running);
        Ok(task)
    }

    pub fn list(&self) -> Result<Vec<TransferTask>> {
        Ok(self.index.list_transfers()?)
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
                },
                &operation_id(task, "init"),
            )
            .await?;

        match response {
            InitUploadResponse::Instant { node_id, .. } => {
                self.index.update_transfer_descriptor(
                    task.id,
                    Some(node_id),
                    None,
                    Some(size_bytes),
                    Some(&content_hash),
                    None,
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
            self.finish_upload(task, session_id, node_id, size_bytes, content_hash)?;
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
            size_bytes,
            content_hash,
        )
    }

    fn finish_upload(
        &self,
        task: &TransferTask,
        session_id: Uuid,
        node_id: Uuid,
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
        if let Some(parent) = destination.parent() {
            tokio::fs::create_dir_all(parent).await?;
        }
        self.index.update_transfer_descriptor(
            task.id,
            Some(node_id),
            None,
            Some(descriptor.size_bytes),
            Some(&descriptor.content_hash),
            Some(&temp_path.to_string_lossy()),
        )?;

        let mut offset = tokio::fs::metadata(&temp_path)
            .await
            .map(|metadata| metadata.len())
            .unwrap_or(0)
            .min(u64::try_from(descriptor.size_bytes).unwrap_or(0));
        if offset < u64::try_from(descriptor.size_bytes).unwrap_or(0) {
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
            while let Some(chunk) = stream.next().await {
                self.check_control(task.id)?;
                let chunk = chunk?;
                file.write_all(&chunk).await?;
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
        }

        self.check_control(task.id)?;
        let actual_hash = sha256_file(&temp_path).await?;
        if !actual_hash.eq_ignore_ascii_case(&descriptor.content_hash) {
            return Err(TransferError::HashMismatch);
        }
        if tokio::fs::try_exists(destination).await? {
            tokio::fs::remove_file(destination).await?;
        }
        tokio::fs::rename(&temp_path, destination).await?;
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

fn new_task(
    direction: TransferDirection,
    local_path: &Path,
    temp_path: Option<&Path>,
    space_id: Option<Uuid>,
    parent_id: Option<Uuid>,
    node_id: Option<Uuid>,
    size_bytes: i64,
) -> TransferTask {
    let now = Utc::now();
    TransferTask {
        id: Uuid::new_v4(),
        direction,
        status: TransferStatus::Queued,
        local_path: local_path.to_string_lossy().into_owned(),
        temp_path: temp_path.map(|path| path.to_string_lossy().into_owned()),
        space_id,
        parent_id,
        node_id,
        session_id: None,
        size_bytes,
        transferred_bytes: 0,
        content_hash: None,
        client_operation_id: Uuid::new_v4().to_string(),
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
    use drive_api_client::ApiClient;
    use drive_local_index::{LocalIndex, TransferStatus};
    use uuid::Uuid;

    use super::{part_range, sha256_file, TransferManager};

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
