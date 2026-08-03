# 企业网盘 Rust 桌面端

`desktop/` 是 Sprint 7 与 Sprint 8 的 Windows 11 Rust/Tauri 工程，版本为 `0.5.0`。同步事实、传输状态、本地索引、凭据、更新校验和诊断均位于 Rust 层，Tauri 页面只展示状态并发送命令。

## Workspace

- `apps/drive-desktop/src-tauri`：Tauri 2 Windows 应用与受控命令。
- `crates/drive-api-client`：DTP/1、设备会话、空间、文件和增量游标 API client。
- `crates/drive-device-session`：设备登录、轮换和系统凭据编排。
- `crates/drive-local-index`：SQLite migration、远端节点索引、离线操作队列、冲突、逐文件状态和传输恢复。
- `crates/drive-sync-engine`：`notify` 文件监听、远端增量消费、双向同步、冲突副本、选择性同步和设备/权限撤销停机。
- `crates/drive-transfer`：预签名 HTTPS 上传下载队列、暂停/继续/取消、multipart/Range、SHA-256、限速并发和 `.drivepart` 原子发布。
- `crates/drive-platform`：Windows Credential Manager、路径规范化、保留名/长路径/链接边界、冲突命名和原子替换。
- `crates/drive-diagnostics`：脱敏诊断 JSON 导出。
- `crates/drive-update`：Ed25519 更新清单与包验签、SHA-256、暂存安装、健康标记和 watchdog 回退。

## 双向同步边界

- 服务端变更日志和版本号是远端事实，本地 SQLite 索引与操作日志支持离线恢复；本地扫描不会直接覆盖远端。
- 双端同时修改会把本地内容保留为带设备名和 UTC 时间的冲突副本，再把远端版本下载到原路径。目录移动/重命名竞争会保留本地完整目录树，并把旧操作置为冲突。
- 下载只在目标版本、内容 hash、持久化字节数和 `.drivepart` 实际长度一致时续传；不一致或 hash 失败会删除临时文件并从零重试，校验成功后原子替换。
- 默认不跟随符号链接、junction 或 reparse point；同步路径拒绝 Windows 保留名、尾随点/空格和根目录逃逸，并统一 Unicode NFC。
- 设备会话吊销、过期、重用或失效会清除内存 token、停止 watcher、禁用同步根，并终止待处理操作和传输。

## 签名更新

- `update-public-key.txt` 是客户端固定的 Ed25519 公钥；`signing/desktop-code-signing.pem` 是公开代码签名证书，私钥不进入仓库。
- GitHub Actions 从 Secrets 注入更新签名密钥和 Windows PFX，校验 Authenticode 证书 DER SHA-256、更新清单签名、包签名与包 SHA-256，再上传签名安装包和更新工件。
- 当前公开证书 DER SHA-256：`765e82aba7bd3276f18eeadddd7b33257a68b7a1ddcdac6d4fc7f7bc639a3ca5`。

## 本地验证

```powershell
cd desktop
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
cargo deny check advisories licenses bans sources
```

Sprint 8 核心状态机可单独验证，避免在没有 MSVC/Tauri 链接环境时重复执行无关 workspace：

```powershell
cargo test -p drive-transfer sprint8_ --lib
cargo test -p drive-sync-engine sprint8_ --lib
```

Tauri 开发启动：

```powershell
cd desktop
cargo tauri dev --manifest-path apps/drive-desktop/src-tauri/Cargo.toml
```

设备 token 只写入系统凭据库，不进入 SQLite、普通配置文件或诊断包。同步目录首次建立时先获取服务端游标锚点，再拉取目录快照，最后消费增量变更，避免快照窗口漏变更。
