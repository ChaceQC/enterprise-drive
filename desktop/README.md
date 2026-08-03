# 企业网盘 Rust 桌面端

`desktop/` 是 Sprint 7 的 Windows 11 Alpha 工程，版本为 `0.5.0`。同步事实、传输状态、本地索引、凭据和诊断均位于 Rust 层，Tauri 页面只展示状态并发送命令。

## Workspace

- `apps/drive-desktop/src-tauri`：Tauri 2 Windows 应用与受控命令。
- `crates/drive-api-client`：DTP/1、设备会话、空间、文件和增量游标 API client。
- `crates/drive-device-session`：设备登录、轮换和系统凭据编排。
- `crates/drive-local-index`：SQLite migration、远端节点索引、操作日志和传输任务恢复。
- `crates/drive-sync-engine`：同步根选择及服务端增量变更落库；双向监听属于 Sprint 8。
- `crates/drive-transfer`：预签名 HTTPS 上传下载队列、暂停/继续/取消、Range 和 SHA-256。
- `crates/drive-platform`：Windows Credential Manager 与同步目录边界。
- `crates/drive-diagnostics`：脱敏诊断 JSON 导出。

## 本地验证

```powershell
cd desktop
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
cargo deny check advisories licenses bans sources
```

Tauri 开发启动：

```powershell
cd desktop
cargo tauri dev --manifest-path apps/drive-desktop/src-tauri/Cargo.toml
```

设备 token 只写入系统凭据库，不进入 SQLite、普通配置文件或诊断包。同步目录首次建立时先获取服务端游标锚点，再拉取目录快照，最后消费增量变更，避免快照窗口漏变更。
