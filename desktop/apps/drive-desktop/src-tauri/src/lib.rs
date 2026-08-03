use std::path::PathBuf;
use std::sync::Arc;

use chrono::Utc;
use drive_api_client::{
    DeviceListResponse, DeviceRegisterRequest, DeviceSessionResponse, FileListResponse,
    SpaceListResponse,
};
use drive_device_session::DeviceSessionManager;
use drive_diagnostics::DiagnosticsExporter;
use drive_local_index::{IndexedNode, LocalIndex, TransferTask};
use drive_platform::{application_data_dir, SystemCredentialStore};
use drive_sync_engine::{SyncEngine, SyncPageSummary, SyncRunSummary};
use drive_transfer::TransferManager;
use serde::Deserialize;
use tauri::tray::TrayIconBuilder;
use tauri::State;
use uuid::Uuid;

const DEFAULT_API_URL: &str = "http://localhost:18080/api/v1";

struct AppState {
    installation_id: Uuid,
    data_dir: PathBuf,
    sessions: DeviceSessionManager,
    index: LocalIndex,
    sync: SyncEngine,
    transfers: TransferManager,
    diagnostics: DiagnosticsExporter,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct LoginCommand {
    tenant_slug: String,
    username: String,
    password: String,
    device_name: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct BrowseCommand {
    space_id: Uuid,
    parent_id: Option<Uuid>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct OfflineBrowseCommand {
    space_id: Uuid,
    parent_id: Uuid,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct SyncRootCommand {
    space_id: Uuid,
    root_node_id: Uuid,
    local_path: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct RootCommand {
    root_node_id: Uuid,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct UploadCommand {
    local_path: String,
    space_id: Uuid,
    parent_id: Uuid,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct DownloadCommand {
    node_id: Uuid,
    destination: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct TransferCommand {
    task_id: Uuid,
}

#[tauri::command]
fn app_version() -> String {
    env!("CARGO_PKG_VERSION").to_string()
}

#[tauri::command]
fn restore_session(state: State<'_, AppState>) -> Result<bool, String> {
    state.sessions.restore().map_err(display_error)
}

#[tauri::command]
async fn login(
    request: LoginCommand,
    state: State<'_, AppState>,
) -> Result<DeviceSessionResponse, String> {
    state
        .sessions
        .register(&DeviceRegisterRequest {
            tenant_slug: request.tenant_slug,
            username: request.username,
            password: request.password,
            installation_id: state.installation_id,
            device_name: request.device_name,
            platform: "windows".to_string(),
            client_version: env!("CARGO_PKG_VERSION").to_string(),
        })
        .await
        .map_err(display_error)
}

#[tauri::command]
fn sign_out(state: State<'_, AppState>) -> Result<(), String> {
    state.sessions.clear().map_err(display_error)
}

#[tauri::command]
async fn list_devices(state: State<'_, AppState>) -> Result<DeviceListResponse, String> {
    state.sessions.list_devices().await.map_err(display_error)
}

#[tauri::command]
async fn list_spaces(state: State<'_, AppState>) -> Result<SpaceListResponse, String> {
    state
        .sessions
        .api_client()
        .list_spaces(None)
        .await
        .map_err(display_error)
}

#[tauri::command]
async fn list_files(
    request: BrowseCommand,
    state: State<'_, AppState>,
) -> Result<FileListResponse, String> {
    state
        .sessions
        .api_client()
        .list_files(request.space_id, request.parent_id, None)
        .await
        .map_err(display_error)
}

#[tauri::command]
fn list_offline_files(
    request: OfflineBrowseCommand,
    state: State<'_, AppState>,
) -> Result<Vec<IndexedNode>, String> {
    state
        .index
        .list_children(request.space_id, request.parent_id)
        .map_err(display_error)
}

#[tauri::command]
async fn configure_sync_root(
    request: SyncRootCommand,
    state: State<'_, AppState>,
) -> Result<SyncRunSummary, String> {
    state
        .sync
        .initialize_root(request.space_id, request.root_node_id, request.local_path)
        .await
        .map_err(display_error)
}

#[tauri::command]
async fn pull_sync_changes(
    request: RootCommand,
    state: State<'_, AppState>,
) -> Result<SyncPageSummary, String> {
    state
        .sync
        .pull_once(request.root_node_id, 200)
        .await
        .map_err(display_error)
}

#[tauri::command]
fn start_upload(
    request: UploadCommand,
    state: State<'_, AppState>,
) -> Result<TransferTask, String> {
    let task = state
        .transfers
        .enqueue_upload(request.local_path, request.space_id, request.parent_id)
        .map_err(display_error)?;
    spawn_transfer(state.transfers.clone(), task.id);
    Ok(task)
}

#[tauri::command]
fn start_download(
    request: DownloadCommand,
    state: State<'_, AppState>,
) -> Result<TransferTask, String> {
    let task = state
        .transfers
        .enqueue_download(request.node_id, request.destination)
        .map_err(display_error)?;
    spawn_transfer(state.transfers.clone(), task.id);
    Ok(task)
}

#[tauri::command]
fn pause_transfer(
    request: TransferCommand,
    state: State<'_, AppState>,
) -> Result<TransferTask, String> {
    state
        .transfers
        .pause(request.task_id)
        .map_err(display_error)
}

#[tauri::command]
fn resume_transfer(
    request: TransferCommand,
    state: State<'_, AppState>,
) -> Result<TransferTask, String> {
    let task = state
        .transfers
        .resume(request.task_id)
        .map_err(display_error)?;
    spawn_transfer(state.transfers.clone(), task.id);
    Ok(task)
}

#[tauri::command]
async fn cancel_transfer(
    request: TransferCommand,
    state: State<'_, AppState>,
) -> Result<TransferTask, String> {
    state
        .transfers
        .cancel(request.task_id)
        .await
        .map_err(display_error)
}

#[tauri::command]
fn list_transfers(state: State<'_, AppState>) -> Result<Vec<TransferTask>, String> {
    state.transfers.list().map_err(display_error)
}

#[tauri::command]
fn export_diagnostics(state: State<'_, AppState>) -> Result<String, String> {
    let destination = state.data_dir.join("diagnostics").join(format!(
        "enterprise-drive-{}.json",
        Utc::now().format("%Y%m%dT%H%M%SZ")
    ));
    state
        .diagnostics
        .export(&destination, &[])
        .map(|path| path.to_string_lossy().into_owned())
        .map_err(display_error)
}

fn spawn_transfer(manager: TransferManager, task_id: Uuid) {
    tauri::async_runtime::spawn(async move {
        let _ = manager.run(task_id).await;
    });
}

fn display_error(error: impl std::fmt::Display) -> String {
    error.to_string()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let data_dir = application_data_dir().expect("application data directory must be available");
    std::fs::create_dir_all(&data_dir).expect("application data directory must be writable");
    let index =
        LocalIndex::open(data_dir.join("desktop-index.sqlite3")).expect("local index must open");
    index
        .recover_interrupted()
        .expect("interrupted transfers must be recoverable");
    let installation_id = index
        .installation_id()
        .expect("installation ID must be available");
    let api_url =
        std::env::var("DRIVE_DESKTOP_API_URL").unwrap_or_else(|_| DEFAULT_API_URL.to_string());
    let api = drive_api_client::ApiClient::new(&api_url).expect("desktop API URL must be valid");
    let credentials = Arc::new(SystemCredentialStore::new("EnterpriseDrive"));
    let sessions = DeviceSessionManager::new(api.clone(), credentials, installation_id);
    let _ = sessions.restore();
    let state = AppState {
        installation_id,
        data_dir,
        sessions,
        index: index.clone(),
        sync: SyncEngine::new(api.clone(), index.clone()),
        transfers: TransferManager::new(api, index.clone()),
        diagnostics: DiagnosticsExporter::new(index),
    };

    tauri::Builder::default()
        .manage(state)
        .setup(|app| {
            let mut tray = TrayIconBuilder::new().tooltip("企业网盘");
            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            }
            tray.build(app)?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            app_version,
            restore_session,
            login,
            sign_out,
            list_devices,
            list_spaces,
            list_files,
            list_offline_files,
            configure_sync_root,
            pull_sync_changes,
            start_upload,
            start_download,
            pause_transfer,
            resume_transfer,
            cancel_transfer,
            list_transfers,
            export_diagnostics,
        ])
        .run(tauri::generate_context!())
        .expect("Tauri application failed");
}
