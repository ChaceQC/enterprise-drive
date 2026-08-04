# PROJECT_PROGRESS.md

## 2026-08-04 CI 重复任务收敛

### 当前状态

- 分支：`dev`；已推送的第二轮提交为 `e1dae40`。远端 run `30880492890` 的 8 个 job 都完成成功，但 workflow 总结论记录为 `cancelled`；日志确认把更新工具构建移到 Tauri 之后仍有重复 release 编译，因此本轮按用户要求改为“相关代码未变化就跳过对应 CI”。
- 基线取自成功运行 `30872900207`：8 个 job 合计约 `46.78` runner-minutes，其中 `rust-desktop` 为 `17.25` 分钟、`windows-desktop-installer` 为 `20.80` 分钟；桌面路径合计占约 `38` 分钟。

### 已完成

- 新增 `.github/scripts/ci_scope.py` 与标准库回归用例，按 backend、desktop、installer、rust_policy、windows、minio 六类 scope 路由变更；桌面契约进入后端测试，普通桌面 README 不启动耗时 job。
- `push` 与 `pull_request` 使用同一仓库/分支并发组并开启 `cancel-in-progress`，新提交会取消同分支旧运行。
- 后端 job 先执行 Ruff、Bandit、pip-audit 和 Mypy，通过后才启动 PostgreSQL/MinIO、执行 Alembic、pytest、Compose/Nginx、Docker smoke 与镜像构建。
- Rust job 保留 format、workspace tests 和 Clippy，但改为先跑 tests、再以 `--no-deps` 检查 workspace crate，减少第三方依赖在 Clippy 阶段重复检查和编译；同时移除与 Tauri/NSIS 重复的 workspace release build。
- Tauri CLI 从每次约 9 分钟的 `cargo install` 改为固定 `@tauri-apps/cli@2.11.4` npm 二进制，并使用固定 SHA 的 `actions/cache v6.1.0` 缓存。
- 首次真实全 scope run `30877250861` 已全绿：总 runner-minutes `29.13`，相对基线 `46.78` 下降约 `37.7%`；backend `4.70` 分钟、Rust `7.87` 分钟、安装包 `13.65` 分钟、MinIO 合并扫描 `1.23` 分钟。
- 首轮日志确认安装包 job 内的 `tauri build` 之后，两个 debug `cargo run` 又重新编译整套 update 依赖；随后改为一次 release 构建并直接调用二进制。run `30880492890` 进一步确认 Tauri release 构建完成后，更新工具步骤仍出现 `158` 行 `Compiling`，该步骤耗时 `2m11s`，说明不同 Cargo package/feature 图没有复用同一批 release artifact。
- 本轮把路由收窄到实际代码依赖：普通 Rust crate 源码/测试只运行 `rust-desktop`；Tauri UI、配置、图标、公开密钥和签名材料只运行安装包；Tauri `src-tauri` Rust 入口与 `drive-update` 签名代码同时运行两者；Cargo manifest/lock/toolchain 仍进入 Rust、安装包和 policy。
- CI workflow/router 自身变化只保留 `changes` 轻量校验，不再强制 backend、Rust、安装包、Windows 和供应链全部重跑；安装包 job 同时移除“任意 push 都执行”的兜底条件，并允许 Rust/policy job 按 scope 正常 skipped。
- MinIO Server/Client 由两个 matrix job 合并为一个 supply-chain job，只安装一次 Grype、统一上传一组 SBOM/报告；镜像配置变化和每周一 UTC 03:17 定时任务继续执行该门禁，Rust dependency policy 同时保留每周检查。
- `workflow_dispatch` 会运行完整 scope；每周 schedule 继续运行 MinIO 与 Rust policy。

### 验证

- `python -X utf8 .github/scripts/test_ci_scope.py`：现为 `17 passed`。
- `python -m py_compile`：路由器和测试脚本通过。
- `ruamel.yaml`：workflow 顶层结构、8 个 job、schedule 和依赖关系解析通过。
- `actionlint 1.7.12`：`.github/workflows/backend-ci.yml` 通过。
- 合并后的 MinIO shell block 通过 `bash -n`；固定 npm Tauri CLI 在本机临时目录安装耗时约 6 秒，`tauri-cli 2.11.4` 可执行。
- 本轮再次执行 `actionlint 1.7.12`、17 个 scope 回归、`py_compile` 和四组实际路由输出检查：CI workflow/router 为 `summary=none`，UI-only 为 `installer`，普通 crate source 为 `desktop`，Tauri Rust 为 `desktop,installer`；均通过。
- 首轮远端 run `30877250861` 的 8 个 job 全部成功，桌面安装包签名/更新工件上传成功。
- `git diff --check`：通过。

### 待远端验证

- 已修改 `.github/scripts/ci_scope.py`、回归测试和安装包 job 条件；当前变更只涉及 CI workflow/router 与文档，推送后预期只有 `changes` job 运行，其余重 job 全部显示 skipped。
- 下一步提交并推送，确认远端 summary 为 `none`，并以一个 UI-only 与普通 crate-source 路由用例继续验证 installer/Rust job 的互斥跳过语义。

## 2026-08-04 Sprint 9 版本与契约收尾

### 当前状态

- 分支：`dev`；Sprint 9 功能范围 `BE-036` 至 `BE-039`、`BE-044`、`BE-045` 此前已经完成，本轮处理阶段表与实际仓库之间最后的版本收尾缺口。
- Sprint 8 最终修复提交 `d3725a3` 已推送，GitHub Actions `backend-ci` run `30854694265` 的 8 个 job 全部成功。
- 项目目标版本从 Sprint 7/8 的 `0.5.0` 提升到 Sprint 9 的 `0.6.0`；不新增业务范围，不重跑已通过的 Sprint 9、MinIO、备份恢复、性能或完整桌面测试集合。
- Sprint 9 收尾提交 `d31eaaa` 已推送到 `origin/dev`，对应 `backend-ci` run `30872900207` 的 8 个 job 全部成功。

### 已完成

- 后端 `pyproject.toml`、Settings 默认版本、健康检查断言和 `uv.lock` 项目记录统一为 `0.6.0`。
- Rust workspace、内部 path 依赖、Cargo 锁文件、本机 Tauri 安装包版本和 UI 初始版本统一为 `0.6.0`。
- API client 与更新器 User-Agent 改为从 `CARGO_PKG_VERSION` 生成，避免后续版本提升时再次出现硬编码漂移。
- Sprint 7/8 桌面 OpenAPI 兼容契约同步到当前运行时版本，并新增跨后端、Rust workspace、Tauri 和契约文件的版本一致性测试。
- README、后端/桌面 README、Windows 部署说明、阶段表、执行计划和完整技术计划书同步到当前 `0.6.0` 基线；Sprint 7/8 的历史 `0.5.0` 记录保留。

### 验证

- `uv lock --check` 通过，锁文件解析为 148 个包。
- 受影响的 `backend/app/core/config.py`、`backend/tests/test_app.py` 通过 Ruff check 和 format check。
- 只运行版本一致性、健康检查和桌面 OpenAPI 契约相关的 `backend/tests/test_app.py`、`backend/tests/test_desktop_openapi_contract.py`，结果 `12 passed`。
- `cargo metadata --locked --no-deps` 通过，9 个本地 `drive-*` package 均解析为 `0.6.0`；`cargo fmt --all --check` 通过。
- 定向 `cargo check --locked -p drive-api-client -p drive-update` 在编译第三方 build script 时复现本机既有环境边界：当前只安装 MSVC target，但 shell 缺少 `link.exe`；没有进入本轮 Rust 源码诊断，完整编译继续由 Windows CI 验证。
- 两个桌面 OpenAPI 契约和 Tauri 配置 JSON 解析通过，版本均为 `0.6.0`；`git diff --check` 通过。
- GitHub Actions `backend-ci` run `30872900207` 全绿：`backend`、`rust-desktop`、`rust-dependency-policy`、`windows-deployment`、`minio-image-policy`、两组 MinIO supply-chain 和 `windows-desktop-installer` 共 8 个 job 全部成功。
- 远端 Windows runner 已补齐本机缺失的验证：Rust Clippy、Rust tests、release build、Tauri/NSIS 安装包、Authenticode 与更新工件签名/上传均通过。

### 阻塞与风险

- 生产 DNS/受信证书证据和 MinIO 修复镜像仍不在当前本机环境内，正式 `v0.4.0` tag/Release 继续保持阻塞。
- Web 用户端与管理后台属于 Sprint 10，不纳入本次 Sprint 9 版本收尾。

### 下一步

1. 进入 Sprint 10 Web 用户端与管理后台，建立 `frontend/`、生成 OpenAPI client 并补齐 Web CI/E2E。
2. 在真实生产网络完成 DNS/受信证书记录，并采用修复镜像解除 MinIO 发布 blocker。

### 涉及文件

- `backend/pyproject.toml`
- `backend/app/core/config.py`
- `backend/tests/test_app.py`
- `backend/uv.lock`
- `desktop/Cargo.toml`
- `desktop/Cargo.lock`
- `desktop/apps/drive-desktop/`
- `desktop/crates/`
- `desktop/contracts/`
- `README.md`
- `backend/README.md`
- `desktop/README.md`
- `docs/deployment-windows-docker.md`
- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`
- `PROJECT_STAGE_STATUS.md`
- `企业网盘开发者技术计划书.md`

## 2026-08-03 Sprint 8 Rust 双向同步与桌面发布交付

### 当前状态

- 分支：`dev`；项目版本保持 `0.5.0`，Sprint 8 范围为 `DC-007` 至 `DC-010`。
- Sprint 8 实现和本地专项验收已完成：文件系统监听、远端增量消费、SQLite 离线队列、冲突副本、选择性同步、Windows 路径边界、签名更新与回退均已落地。
- 运行时 OpenAPI 保持 80 个路径、107 个操作；migration head 更新为 `20260803_0023`。
- 本次只补 Sprint 8 尚缺的状态机与验收证据，没有重跑已通过的 Sprint 7、MinIO、备份恢复、性能或其他无关集合；`dev` 推送后以对应 `backend-ci` 全部 job 成功作为最终远端门禁。

### 已完成

- 后端上传初始化新增 `target_node_id` 与 `expected_current_version_id`，桌面端可在既有节点上创建新版本；init 与 complete 都重新校验当前版本，竞争写入返回 `FILE_VERSION_CONFLICT`，不产生静默覆盖、重复容量流水或错误当前版本。
- 新增 `20260803_0023_sprint8_sync_uploads.py`，为上传会话持久化目标节点和版本前置条件，并提供可逆约束迁移。
- `drive-sync-engine` 使用 `notify` 监听本地创建、修改、删除、重命名和移动，消费服务端增量变更；SQLite 持久化操作队列、重试次数、下次执行时间、冲突和逐文件状态，进程重启后可恢复。
- 双端同时修改会把本地内容移动为带设备名和 UTC 时间的冲突副本，原操作进入 `conflict`，远端新版本进入原路径；目录移动/重命名竞争同样保留本地完整目录树并终止旧操作，防止队列随后覆盖远端结果。
- 设备会话吊销、过期、重用或失效会清除内存 token、停止全部 watcher、禁用全部同步根，并把待处理操作、传输任务和逐文件状态统一标记为对应错误；单根权限撤销只停止对应根。
- 下载使用同目录 `.drivepart`，仅在版本、hash、持久化进度和实际临时文件长度全部一致时发送 Range；旧版本或未绑定临时文件会先清理，从零下载。hash 不匹配会删除临时文件并进入有界自动重试，完成后使用 Windows 原子替换。
- 支持选择性同步、glob 忽略规则、带宽限制、1 至 16 并发传输、指数退避、逐文件状态和冲突列表；默认忽略 `.drivepart`，不跟随符号链接、junction 或 reparse point。
- Windows 路径层集中处理大小写折叠、保留设备名、尾随点/空格、Unicode NFC、长路径和冲突文件名；同步根和相对路径均经过根目录逃逸检查。
- 新增 `drive-update`：Ed25519 签名更新清单、签名包、SHA-256、目标平台/版本校验、暂存安装、健康标记和 watchdog 回退。仓库只包含更新公钥与公开代码签名证书，不包含私钥。
- Tauri 后台每 5 秒恢复同步循环，界面新增逐文件状态、冲突记录、选择性同步、限速/并发、检查更新、安装和回退入口。
- CI 新增 Windows Authenticode 签名、证书 DER SHA-256 指纹校验、更新清单/包签名与篡改拒绝、签名安装包及更新工件上传；签名材料只从 GitHub Secrets 注入。

### 验证

- Sprint 8 后端新增版本化上传用例：`2 passed`；此前尚未执行的受影响上传回归与 OpenAPI 契约：`17 passed`。
- 空 PostgreSQL 16 已从零升级到 `20260803_0023`，并完成 `0023 -> 0022 -> 0023` 往返；新增列、成对约束和单一 migration head 均确认存在，临时容器已删除。
- 此前 Sprint 8 Rust 核心专项 `16 passed`，覆盖 10,000 文件初始索引、离线操作/传输异常退出恢复、Windows 路径、冲突命名、原子替换、1 GiB 分片范围和更新签名篡改拒绝。
- 本轮只新增并运行 8 个缺口用例：`drive-local-index` `1 passed`，覆盖多同步根操作/传输队列隔离；`drive-transfer` `4 passed`，覆盖 1 GiB 持久化 Range、进程重启续传、旧 `.drivepart` 清理和 hash 失败重试；`drive-sync-engine` `3 passed`，覆盖双端同时修改、目录移动/重命名冲突和设备吊销后停止全部同步。
- 受本轮修改影响的 `drive-local-index`、`drive-transfer`、`drive-sync-engine` 已通过 GNU 工具链 Clippy `-D warnings`；`cargo fmt --all --check` 通过。
- 后端 Ruff check/format、Mypy、JavaScript 语法和 GitHub Actions YAML 此前均已通过；本轮未修改这些已验证路径的业务语义。
- 本机 MSVC shell 缺少 `link.exe`；此前完整 GNU workspace 测试只在 Tauri `cdylib` 链接阶段遇到 `export ordinal too large`。因此不重复运行本机全 workspace，核心 crate 已完成定向测试，Windows MSVC、release、NSIS、Authenticode 和更新工件由本次 CI 最终确认。
- 已建立 `DRIVE_UPDATE_SIGNING_KEY_BASE64`、`DRIVE_WINDOWS_SIGNING_PFX_BASE64`、`DRIVE_WINDOWS_SIGNING_PFX_PASSWORD`；公开证书 DER SHA-256 为 `765e82aba7bd3276f18eeadddd7b33257a68b7a1ddcdac6d4fc7f7bc639a3ca5`。

### 下一步

1. 提交并推送 `dev`，只跟踪本次 `backend-ci`；若出现失败，只修复实际失败 job，不重跑无关本地集合。
2. Sprint 8 远端门禁全绿后，产品开发顺序进入 Sprint 10 Web 用户端与管理后台；Sprint 9 后端核心产品闭环已经完成。
3. 生产发布仍需真实 DNS/受信证书、MinIO 修复镜像和正式 `v0.4.0` tag/Release 门禁，不能用桌面签名工件替代这些外部证据。

### 涉及文件

- `backend/app/modules/upload/`
- `backend/migrations/versions/20260803_0023_sprint8_sync_uploads.py`
- `backend/tests/test_desktop_sprint8.py`
- `desktop/crates/drive-sync-engine/`
- `desktop/crates/drive-local-index/`
- `desktop/crates/drive-transfer/`
- `desktop/crates/drive-platform/`
- `desktop/crates/drive-update/`
- `desktop/apps/drive-desktop/`
- `desktop/contracts/sprint8-openapi.json`
- `desktop/update-public-key.txt`
- `desktop/signing/`
- `.github/workflows/backend-ci.yml`
- `PROJECT_PLAN.md`
- `PROJECT_STAGE_STATUS.md`
- `README.md`
- `desktop/README.md`
- `企业网盘开发者技术计划书.md`

## 2026-08-03 Sprint 7 Rust 桌面基础交付

### 当前状态

- 分支：`dev`；目标版本已提升为 `0.5.0`。
- Sprint 7 范围固定为 `DC-001` 至 `DC-006`，不包含 Sprint 8 的文件系统监听、双向同步、冲突副本、签名更新和失败回退。
- 运行时 OpenAPI 为 80 个路径、107 个操作；migration head 为 `20260803_0022`。
- Sprint 7 实现、定向验证、提交、推送和 Windows CI 收尾均已完成；最终代码提交为 `a57d3fb`，`dev` 与 `origin/dev` 同步。

### 已完成

- 后端新增独立桌面设备会话：注册、短期轮换、设备列表、单设备/全设备吊销、token hash 存储、轮换 token 重用后的 session family 吊销，以及 `Authorization: Device <opaque token>` 认证。
- 后端新增按租户/用户/空间/根目录绑定的签名增量 cursor、变更日志、删除/移出根目录/权限撤销 tombstone、cursor 过期全量重建信号和 `X-Client-Operation-ID` 持久化重放。
- 文件夹创建、重命名、移动、删除及上传 init/complete/abort 已接入客户端操作幂等；重命名、移动和删除新增当前文件版本前置条件，冲突返回 `FILE_VERSION_CONFLICT`。
- DTP/1 新增批量分片签名、分片确认、服务端并发提示、上传状态已确认分片、下载 `hash_algo/content_hash` 和 Rust Range/SHA-256 传输队列。
- 新增 `20260803_0022_sprint7_desktop_contracts.py`，创建 `desktop_devices`、`device_sessions`、`client_operations`、`sync_changes`。
- 新增 `desktop/` Cargo workspace 和 8 个 package：Tauri 应用、API client、设备会话、SQLite 本地索引、增量同步、传输队列、Windows 平台适配和脱敏诊断。
- Tauri Alpha 已接入设备登录、空间/目录浏览、同步根快照与增量、离线元数据、上传/下载队列、暂停/继续/取消、任务栏托盘和诊断导出；设备 token 只进入 Windows Credential Manager。
- 新增锁定的 `Cargo.lock`、OpenAPI 契约快照、Rust 架构 ADR、确定性 Windows PNG/ICO、cargo-deny 策略和 CI Rust/NSIS job。

### 验证

- Sprint 7 后端、OpenAPI 契约和 health 版本定向集合：`5 passed`。
- 受影响测试文件 Ruff check 与 format check 通过；`uv lock --check` 通过。
- 空 PostgreSQL 16 从零升级到 `20260803_0022`，确认四张 Sprint 7 表存在，临时容器已删除。
- `cargo fmt --all --check` 和 `cargo metadata --locked --no-deps` 通过，workspace 共 8 个 package。
- 本机 PowerShell 未加载 MSVC `link.exe`，因此本地 `cargo check` 在 Rust build script 链接阶段停止；按用户要求不安装系统软件，Clippy、Rust tests、cargo-deny、release build 和 NSIS 由 Windows CI 验证。
- 未重复运行已通过且未受后续修改影响的全量 pytest、安全矩阵、真实 MinIO、备份恢复或性能测试。
- 最终 GitHub Actions `backend-ci` run `30838990372`（提交 `a57d3fb`）全绿：`rust-desktop`、`rust-dependency-policy`、`backend`、`windows-deployment`、`minio-image-policy`、Server/Client 两个 MinIO supply-chain job 和 `windows-desktop-installer` 共 8 个 job 全部成功。
- 最新修复 run 启动后，已取消被取代且仍在运行的 run `30838675810`，避免继续执行重复门禁。
- CI 收尾修复仅针对真实日志：Windows runner 上的 cargo-deny 改为独立 Ubuntu job；15 个内部 path 依赖补齐 `0.5.0`，Tauri 传递链 5 个无安全升级的 RustSec 公告在 `desktop/deny.toml` 中逐项记录原因。

### 下一步

1. Sprint 7 已闭环，不再重复执行已通过的 Sprint 7 或无关测试。
2. 该 Sprint 7 记录形成时的下一步是 Sprint 8；现已由顶部 Sprint 8 交付记录闭环。
3. 生产发布仍需真实 DNS/受信证书、MinIO 修复镜像和正式 `v0.4.0` tag/Release 门禁。

### 涉及文件

- `backend/app/modules/device/`
- `backend/app/modules/sync/`
- `backend/app/modules/file/`
- `backend/app/modules/upload/`
- `backend/migrations/versions/20260803_0022_sprint7_desktop_contracts.py`
- `backend/tests/test_desktop_sprint7.py`
- `backend/tests/test_desktop_openapi_contract.py`
- `desktop/`
- `.github/workflows/backend-ci.yml`
- `docs/adr/0001-rust-desktop-sprint7.md`
- `docs/drive-transfer-protocol-v1.md`
- `PROJECT_PLAN.md`
- `PROJECT_STAGE_STATUS.md`

## 2026-08-03 Sprint 6 管理、监控与上线治理闭环

### 当前状态

- `PROJECT_STAGE_STATUS.md` 中 Sprint 6 的空间、统计、维护、导出、Alertmanager/Grafana、周期恢复演练和备份轮换代码侧剩余项已完成；Sprint 9 的 `BE-044`、`BE-045` 同步闭环。
- 运行时 OpenAPI 为 73 个路径、99 个操作；安全矩阵同步为 99 项，数据库 migration head 为 `20260803_0021`。
- 生产 DNS/受信证书和 MinIO 修复镜像不在当前本机环境内，正式 `v0.4.0` tag/Release 保持阻塞，不使用示例域名、自签名证书或“新增 Critical=0”冒充生产验收。

### 已完成

- 新增 `/api/v1/admin/spaces`：按状态、类型、owner 和关键字筛选，支持签名 cursor、详情、原子创建、乐观更新和停用。创建在同一事务中写入空间、root 节点、owner 成员和空间配额；主 owner 变更同步更新根节点 owner、成员角色、权限版本事件和管理审计。
- 新增 `/api/v1/admin/stats/overview`，按当前租户统计用户、空间、节点、版本、空间配额、分享、上传和 Outbox；空间/member/node 汇总子查询显式带租户条件。
- 新增 `/api/v1/admin/maintenance/tasks` 与 `/maintenance/runs`，查询九个周期任务的连续失败/stale 状态，并以 `admin_jobs` 持久化租户范围异步运行、Celery task ID、结果和失败码。
- 新增 `/api/v1/admin/exports`，异步导出审计、空间和用户 CSV 到私有 `exports/{tenant_id}/{job_id}/`，支持筛选、状态、短期预签名下载、CSV formula 防护、最大行数显式失败和保留期清理。对象删除不在数据库事务中执行，过期成功后写入审计。
- 新增 `20260803_0021_admin_management.py`，为 `spaces` 增加独立 `version` 和管理列表索引，创建 JSONB `admin_jobs`。
- 根 Compose 新增固定 digest 的 Prometheus、Alertmanager、Grafana `monitoring` profile；三项服务只在 Compose 内网，Grafana 经 gateway `/grafana/` 访问，预置运行概览与维护治理看板。
- Nginx 本机 API/S3 与 TLS 模板都拒绝未知 Host；本机 S3 继续允许 `localhost`/`127.0.0.1`，未启用 monitoring profile 时 gateway 仍可启动。
- `deploy/windows/manage.ps1` 新增 `-Monitoring` 生命周期支持、`backup-retention`、轮换计划任务注册/删除、`restore-drill`、恢复演练计划任务注册/删除和 `tls-validate-public`。
- 备份轮换校验目录名、manifest ID 和 SHA-256，按保留天数与最少份数执行；恢复演练使用随机隔离 Compose project，始终清理 target 容器/卷并写 restricted ACL JSON。公网 TLS 验收拒绝私网、CGNAT、benchmark、documentation 和 reserved 地址，记录 DNS、HTTP `308`、HTTPS readiness、证书链和剩余天数。
- 收尾差异审查修正两处监控语义：Outbox backlog 按 pending/failed/processing 总和判断，Grafana maintenance 看板使用 metric-name selector 合并 alert/stale，避免 PromQL `or` 左侧遮蔽 stale。
- 管理任务结果审查把容量校准明细恢复为既有 1,000 项上限；job 仍保留受限明细，完成审计只复制标量摘要、列表计数和嵌套键名，避免把大批空间明细重复写入审计 metadata。
- CI 路径纳入 `deploy/monitoring/**`，新增 Compose/端口、promtool、amtool、dashboard JSON、healthcheck binary 和 Windows governance smoke；MinIO Critical 允许集已从先前较宽的基线收紧到当前实际观测的 Server/Client 16/9 个唯一 ID。
- 新增 `docs/minio-security-risk.md`：登记两个 MinIO 自身 Critical、当前 OIDC/LDAP/Console 可达性缓解和正式发布 blocker。

### 验证

- 管理 API 首轮定向：`3 passed`；完成 CSV/事务边界修复后只重跑受影响导出生命周期和两个新增 owner transfer/CSV 防护用例，结果 `3 passed`。
- 管理模块、admin Worker、migration、网关 smoke 和测试共 28 个文件 Ruff/format 通过；管理模块与 admin Worker 共 25 个源码文件 Mypy 通过。
- 新建临时 PostgreSQL 16，从空库升级到 `20260803_0021 (head)`；查询确认 `admin_jobs.parameters_json=jsonb`、`spaces.version NOT NULL` 和 `idx_spaces_admin_list`，临时容器已删除。
- `governance.ps1`、`manage.ps1` 和新增 smoke 保持 ASCII、无 BOM、PowerShell 5.1 parser 通过；治理 smoke 通过。
- Prometheus 3.13.1 `promtool`、Alertmanager 0.33.1 `amtool`、Grafana dashboard JSON 和三镜像 `wget` healthcheck 可用性通过。
- 监控语义修正后仅重跑受影响的 `platform-alerts.yml`：`promtool check rules` 通过并识别 8 条规则；maintenance dashboard JSON 重新解析通过，确认 alert/stale selector 已更新。
- 管理任务审计摘要修正后只运行对应安全防护用例，结果 `1 passed`；受影响 Worker/测试 Ruff 与 format 通过，Worker 定向 Mypy 通过。
- observability 根因修正后，管理路由 Ruff/format/Mypy 通过；全新 Python 进程创建 FastAPI app 后确认未导入 `app.core.worker_metrics`，API registry 不含 `worker_tasks_total` 或 `trash_cleanup_released_bytes_total`。
- 本机/TLS Nginx 模板 `nginx -t` 通过；真实 raw HTTP smoke 验证未知 API/S3 Host、CL/TE、重复 Content-Length、API 413、S3 streaming 和本机 Host 兼容。
- `docker compose --profile monitoring --profile tls-tools ... config` 通过，确认只有 gateway 发布宿主端口；GitHub Actions YAML 可解析。
- 首次推送提交 `35b3831` 触发 `backend-ci` run `30827760952`：Windows 部署、MinIO image policy 和两组 supply-chain job 全部成功；backend 仅在 Ruff format check 报告 `tests/test_celery_schedule.py` 一处格式差异，其余步骤因 fail-fast 未执行。已按 Ruff diff 精确修正该文件，不重跑无关测试。
- 格式修复提交 `7cab5f6` 触发 `backend-ci` run `30828070314`：Ruff、Bandit、依赖审计、Mypy、完整 Pytest、Compose/监控/TLS/Nginx、Windows 和 MinIO job 均已通过；backend 仅在 observability Docker smoke 发现 API metrics 混入 Worker 指标。根因是管理路由导入 Worker 专用 `celery_app` 触发 Worker observability 模块副作用，已改为只含 broker/backend 的缓存 Celery 发送客户端。
- 未重复运行全量 pytest、旧 Sprint 集合、真实 MinIO、完整备份恢复或 Sprint 3 性能测试；这些未受本轮代码路径影响，继续复用已有通过证据。推送后只跟踪 `backend-ci`，若失败仅修复对应失败项。

### 阻塞与风险

- 当前工作区没有真实 `.env.windows`、生产 DNS、可公开访问的 80/443 或受信证书，`tls-validate-public` 尚未执行真实生产验收。
- 固定社区版 MinIO Server/Client 当前仍有 16/9 个 Critical 唯一 ID；关闭 OIDC/LDAP/Console 只降低可达性，不是镜像修复。
- 备份轮换和隔离演练已自动化；来源签名、完整包加密、离线副本和容量告警继续后续治理。

### 下一步

1. 推送 `dev` 并跟踪本次 `backend-ci` 到全部 job 成功，只处理真实失败项。
2. 在生产环境执行 `tls-validate-public` 并保存 JSON 记录。
3. 更换受支持修复镜像或可审计补丁镜像，重新生成 SBOM/Grype 并运行真实 MinIO 与备份恢复兼容门禁。
4. 发布 blocker 解除后创建 `v0.4.0` tag/Release；并行进入桌面设备会话和增量同步契约。

### 涉及文件

- `backend/app/modules/admin/`
- `backend/app/workers/admin_tasks.py`
- `backend/migrations/versions/20260803_0021_admin_management.py`
- `backend/tests/test_admin_sprint6_management.py`
- `backend/tests/security_route_matrix.py`
- `backend/tests/test_route_security_matrix.py`
- `backend/tests/test_celery_schedule.py`
- `backend/app/core/maintenance_health.py`
- `backend/app/infrastructure/queue/`
- `compose.windows.yml`
- `.env.windows.example`
- `backend/.env.example`
- `deploy/monitoring/`
- `deploy/windows/manage.ps1`
- `deploy/windows/governance.ps1`
- `deploy/windows/tests/governance.smoke.ps1`
- `deploy/windows/nginx/`
- `.github/workflows/backend-ci.yml`
- `README.md`
- `backend/README.md`
- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`
- `PROJECT_STAGE_STATUS.md`
- `AGENT.md`
- `docs/deployment-windows-docker.md`
- `docs/maintenance-monitoring.md`
- `docs/minio-security-risk.md`
- `企业网盘开发者技术计划书.md`

## 2026-08-03 Sprint 5 分享、预览与搜索闭环

### 当前状态

- `PROJECT_STAGE_STATUS.md` 中 Sprint 5 的内部分享接收端、通知/授权重算、OCR/复杂格式和预览产物生命周期剩余项均已完成，Sprint 5 尚未完成项现为空。
- 运行时 OpenAPI 为 64 个路径、85 个操作；安全矩阵同步到 85 项，数据库 migration head 为 `20260803_0020`。
- 下一项进入 `BE-044` 剩余空间管理和 `BE-045` 统计、维护、导出管理 API。

### 已完成

- 新增 `GET /api/v1/shares/created`、`GET /api/v1/shares/received`、`GET /api/v1/shares/{share_id}/items` 和 `POST /api/v1/shares/{share_id}/download`，覆盖创建者列表、接收人列表/详情和 DTP/1 受控下载；读取和下载均重新校验当前分享状态、接收人授权、创建者当前 `share` 权限、节点/版本/blob 事实和文件安全策略。
- 新增 `share_recipient_grants` 物化授权和 `share_notifications` 站内通知；创建分享时展开用户、部门和用户组，部门/用户组成员或状态变化写入 `share.recipients_rebuild_requested`，`share.dispatch_outbox` 重算授权。成员移除、撤销或过期会失活授权并使对应通知失效。
- 新增通知 cursor 列表、未读筛选和已读入口；内部分享访问/下载的成功与拒绝均写入 `share_access_logs` 和审计，访问日志继续使用 `view`/`download` 动作，审计使用 `share.internal.accessed`/`share.internal.downloaded`。
- 新增 `share.expire_shares` 周期维护任务，按租户锁定过期 active 分享、更新状态、失活授权/通知并写入 `share.expired` 审计；调度间隔由 `DRIVE_SHARE_EXPIRY_INTERVAL_SECONDS` 控制。
- `preview_artifacts` 新增 `last_accessed_at`；获取预览 URL 时刷新访问时间。`preview.cleanup_artifacts` 会删除非当前版本且超过保留期的产物记录/对象，并扫描 `previews/{tenant_id}/` 下超期且无数据库记录的孤儿对象，写入审计和 `preview_artifact_cleanup_total` 指标。
- 搜索抽取接入 Tesseract 图片 OCR 和扫描 PDF OCR；PDF 先尝试 `pypdf` 正文，正文为空时再 OCR。旧 `.doc/.xls/.ppt` 与 ODF 文档经 LibreOffice 转 PDF 后抽取；页数、源文件体量、像素、渲染字节、正文字符数和外部命令超时均有配置边界。
- `worker-search` 改用包含 LibreOffice、Poppler、Tesseract `eng`/`chi_sim` 的内容处理镜像，使用独立 1 GiB tmpfs，默认 `--max-tasks-per-child=20`，避免 OCR/转换临时文件和长期进程内存影响其他队列。
- 新增 `20260803_0020_sprint5_completion.py`，创建分享授权/通知表，为预览产物增加最后访问时间和生命周期索引。

### 验证

- Sprint 5 新增核心用例最初 `4 passed`；过期分享和 OCR 资源边界补充用例分别通过。
- 与分享、预览、搜索、组织事件、安全矩阵和 Celery 调度直接相关的既有集合首轮仅 1 项因授权重算事件范围过宽失败，收紧事件后只重跑该失败项并通过。
- 最终定向命令中的预览生命周期和 Celery schedule 已通过；唯一拒绝下载访问日志动作命名不一致已修复，并只重跑 `test_internal_share_received_items_download_notification_and_revoke`，结果 `1 passed`。
- `uv run mypy app`：178 个源码文件通过；Ruff lint、Bandit、Alembic 离线 SQL与单一 head 检查通过。
- OpenAPI 对账为 64 个路径、85 个操作；`docker compose --env-file .env.windows.example -f compose.windows.yml config --quiet` 通过，确认 Search Worker 使用内容处理镜像、独立 tmpfs 和 `max-tasks-per-child=20`。
- 临时空 PostgreSQL 从零升级到 `20260803_0020` 通过，并查询确认 `share_recipient_grants`、`share_notifications` 和 `preview_artifacts.last_accessed_at` 已创建；临时容器已删除。
- `docker build --target preview --tag enterprise-drive-preview:sprint5-check backend` 首次因 Debian 镜像同步返回批量 404，加入 apt 无缓存索引和 5 次重试后重建通过；镜像构建阶段验证 `soffice`、`pdftoppm`、Tesseract 及 `eng`/`chi_sim` 语言包。
- 未重复运行全量 pytest、真实 MinIO、备份恢复或 Sprint 3 性能测试；这些路径与本轮最终修复无直接关系，继续复用已有通过证据。

### 后续边界

- OCR 已覆盖图片、扫描 PDF 与旧 Office/ODF 转换抽取，但不是通用内容分类或复杂 DLP；legal hold、外链代理流和历史版本专用水印继续后续治理。
- 预览生命周期当前按全局保留天数清理；租户级策略、legal hold、治理页面和手工恢复工作流继续 `BE-047` 的扩展边界。
- 该 Sprint 5 收尾记录形成时，根 Compose 尚未纳入 Prometheus、Alertmanager 和 Grafana；本轮 Sprint 6 已由可选 `monitoring` profile 补齐，生产仍需配置真实 webhook 并验收告警链路。

### 下一步

1. 完成 `BE-044` 剩余的空间管理 API。
2. 完成 `BE-045` 统计、维护任务和导出管理 API。
3. 在正式发布阶段补生产 TLS/DNS、MinIO 风险治理和 `v0.4.0` 标记，不重跑已通过且未受影响的 Sprint 3 性能工件。

### 涉及文件

- `backend/app/modules/share/`
- `backend/app/modules/preview/`
- `backend/app/modules/search/`
- `backend/app/infrastructure/search/content_extraction.py`
- `backend/app/workers/share_tasks.py`
- `backend/app/workers/preview_tasks.py`
- `backend/app/workers/search_tasks.py`
- `backend/migrations/versions/20260803_0020_sprint5_completion.py`
- `backend/tests/test_sprint5_completion.py`
- `backend/tests/security_route_matrix.py`
- `backend/tests/test_celery_schedule.py`
- `backend/Dockerfile`
- `compose.windows.yml`
- `.env.windows.example`
- `backend/.env.example`
- `README.md`
- `backend/README.md`
- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`
- `PROJECT_STAGE_STATUS.md`
- `docs/deployment-preview-worker.md`
- `docs/deployment-windows-docker.md`
- `企业网盘开发者技术计划书.md`

## 2026-08-03 Sprint 4 用户、部门与用户组管理闭环

### 当前状态

- `PROJECT_STAGE_STATUS.md` 中 Sprint 4 原剩余的完整用户、部门和用户组管理 API 已完成，Sprint 4 尚未完成项现为空。
- 运行时 OpenAPI 为 58 个路径、79 个操作；安全矩阵同步为 79 项，数据库 migration head 为 `20260803_0019`。
- 该 Sprint 4 收尾记录形成时，`BE-044` 只完成用户、部门、用户组和配额管理子集；空间管理以及 `BE-045` 的统计、维护和导出现已由顶部 Sprint 6 记录闭环。

### 已完成

- 新增 `/api/v1/admin/users` 管理接口：支持筛选与签名 cursor 分页、详情、创建、更新和停用；临时密码使用 Argon2id 哈希，停用用户会吊销其有效会话，并保护最后一个有效系统管理员。
- 新增 `/api/v1/admin/departments` 管理接口：支持筛选与签名 cursor 分页、详情、创建、重命名、移动、停用和成员增删；重命名或移动会在同一事务中更新完整子树路径，并拒绝环路、停用父部门和仍有有效子部门时的停用操作。
- 新增 `/api/v1/admin/groups` 管理接口：支持筛选与签名 cursor 分页、详情、创建、更新、停用和成员增删。
- 三类管理入口均仅允许系统管理员访问并按当前租户隔离；所有读取、写入和拒绝路径均写入管理审计。
- 用户、部门和用户组写操作使用实体 `version` 乐观前置条件；部门/用户组成员或状态变化递增 `tenants.permission_version`，写入 `scope=tenant` 的 `permission.changed`，并按受影响用户或整个租户失效权限缓存。
- 搜索索引继续保存部门/用户组 ACL token，查询时从 PostgreSQL 获取当前成员关系，因此组织成员变化不触发无必要的全租户搜索重建。
- 新增 `20260803_0019_org_admin_versions.py`，以 nullable、回填、not null 三步为 `users`、`departments`、`user_groups` 增加 `version`，并增加三类管理列表索引。

### 验证

- 集中定向测试首轮结果为 `92 passed, 1 skipped, 1 failed`；唯一失败是唯一约束回滚后 actor ORM 实例过期，修复后只重跑该失败用例，结果 `1 passed`。
- 临时真实 PostgreSQL 从空库完整升级到 `20260803_0019` 通过；双会话用户组版本竞争和双管理员并发停用保护定向用例分别 `1 passed`，临时容器均已删除。
- `uv run mypy app`：171 个源码文件通过；`uv run ruff check .` 通过；本轮新增和修改的 Python 文件格式检查通过。
- OpenAPI 对账为 58 个路径、79 个操作；排除 ping/login 后 77 个业务操作全部进入安全矩阵，其中 46 个写操作要求 CSRF，28 个登录态或管理员读取入口通过身份门禁。
- 未重复运行全量 pytest、旧 Sprint 测试、真实 MinIO、备份恢复或性能压测；Windows 全目录格式检查仍只命中两个未修改历史文件的混合换行，本轮未扩大范围修改。

### 后续边界

- 本轮完成 Sprint 4 所列用户、部门和用户组管理，不包含 `BE-038` 内部分享接收端。
- `BE-044` 仍需空间管理接口；`BE-045` 仍需统计、维护和导出管理接口。
- 部门/用户组成员关系在查询权限时以 PostgreSQL 为事实来源；后续若改变搜索 ACL token 模型，再单独设计有界重建策略。

### 涉及文件

- `backend/app/api/v1/router.py`
- `backend/app/modules/admin/organization.py`
- `backend/app/modules/admin/organization_repository.py`
- `backend/app/modules/admin/organization_router.py`
- `backend/app/modules/admin/organization_schemas.py`
- `backend/app/modules/auth/models.py`
- `backend/app/modules/org/models.py`
- `backend/app/modules/permission/cache.py`
- `backend/migrations/versions/20260803_0019_org_admin_versions.py`
- `backend/tests/security_route_matrix.py`
- `backend/tests/test_admin_organization.py`
- `backend/tests/test_admin_organization_postgres.py`
- `backend/tests/test_permission_cache.py`
- `backend/tests/test_route_security_matrix.py`
- `README.md`
- `backend/README.md`
- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`
- `PROJECT_STAGE_STATUS.md`
- `企业网盘开发者技术计划书.md`

## 2026-08-03 Sprint 3 配额、安全与目标性能收尾

### 当前状态

- `PROJECT_STAGE_STATUS.md` 中 Sprint 3 原剩余的目标规模压测、配额账户/策略管理 API 和水印/DLP 基础策略均已完成，Sprint 3 尚未完成项现为空。
- 运行时 OpenAPI 为 48 个路径、58 个操作；migration head 为 `20260803_0018`。
- 本轮沿用已通过的 search、audit、mixed、upload-init 目标工件，只补此前未通过的 `upload_complete`，没有重复运行已通过或无关测试。

### 已完成

- 新增系统管理员配额管理：分页查询配额账户，创建/更新空间、租户、用户额度，以及配额策略列表、创建、更新和停用。
- 配额更新按租户隔离并使用乐观前置条件；新额度不得低于已用容量，数据库中已有用户/租户账户优先于环境默认值。
- 新增租户隔离的 `file_security_policies`：按扩展名/MIME 匹配密级、`presigned/proxy/watermark/blocked` 下载模式、关键字 DLP audit/block、fail-closed、水印模板和策略版本。
- 当前版本与历史版本下载均执行安全策略；内部图片/PDF 可生成动态水印，公开外链支持预签名或水印派生对象，响应、访问日志和审计使用派生文件的真实大小。
- 外链策略要求 proxy 时阻止直连；外链代理流、历史版本专用水印、OCR、legal hold 和复杂内容识别保留为后续治理边界。
- PostgreSQL 新 blob 创建改为 `ON CONFLICT DO NOTHING RETURNING` 原子 upsert，移除新对象常态路径的“先查 + savepoint 插入”开销。
- 性能 runner 增加 `--warmup-seconds`，warm-up 后重置 Locust 统计；complete 队列退出等待缩短为可记录的 0.2 秒。

### 验证

- 配额管理既有定向测试：`3 passed`；真实 PostgreSQL 乐观前置条件并发用例：`1 passed`。
- 空 PostgreSQL 完整 Alembic 升级到 `20260803_0018` 通过。
- 配额、内部文件安全和外链安全集中定向：`8 passed`；历史版本 DLP 与水印派生大小补充用例：`2 passed`。
- 路由安全矩阵与跨租户集中验证：`67 passed`。
- 相关 Ruff、格式检查和 Mypy 均通过；未重跑全量 pytest、旧 smoke、备份恢复或无关模块测试。
- 目标环境确认 10,000 个 fixture 节点、100 万 OpenSearch 文档和 1,000 万审计日志；search、audit、mixed、upload-init 使用此前通过报告。
- 最终 target `upload_complete`：计入 1,936 个 complete，0 失败，`58.364 RPS`；API（不含 storage merge）P95 `790 ms`，端到端 P95 `840 ms`，storage merge P95 `71 ms`，`report.json passed=true`。
- `complete_cleanup.json` 确认 2,000/2,000 个准备节点已 purge，errors 为空；隔离 target 容器、卷、网络和本轮临时镜像均已清理。

### 工件

- `backend/tmp/performance/20260803-sprint3-final/upload-complete-target-upsert-final/report.json`
- `backend/tmp/performance/20260803-sprint3-final/upload-complete-target-upsert-final/complete_cleanup.json`

### 后续边界

- 配额管理本轮闭环账户和策略子集；用户、部门、用户组、空间及统计/维护/导出等完整管理 API 继续 Sprint 9。
- 容量通用校准、部门额度、临时上传占用上限和治理看板继续后续治理。
- 文件安全本轮完成基于已有搜索正文的关键字 DLP 和图片/PDF 水印；OCR、扫描 PDF、复杂内容分类与 legal hold 继续 `GOV-001`。
- 下一项按现有工程顺序进入 `BE-038` 内部分享接收端。

### 涉及文件

- `backend/app/modules/admin/quota.py`
- `backend/app/modules/admin/quota_router.py`
- `backend/app/modules/admin/quota_schemas.py`
- `backend/app/modules/admin/file_security.py`
- `backend/app/modules/admin/file_security_router.py`
- `backend/app/modules/admin/file_security_schemas.py`
- `backend/app/modules/file_security/`
- `backend/app/modules/file/download.py`
- `backend/app/modules/file/version_service.py`
- `backend/app/modules/share/external_download.py`
- `backend/app/modules/upload/repository.py`
- `backend/performance/`
- `backend/migrations/versions/20260803_0017_quota_policy_name.py`
- `backend/migrations/versions/20260803_0018_file_security_policy.py`
- `backend/tests/test_admin_quota.py`
- `backend/tests/test_admin_quota_postgres.py`
- `backend/tests/test_file_security_policy.py`
- `backend/tests/test_external_share_file_security.py`
- `backend/tests/test_performance_benchmark.py`
- `README.md`
- `backend/README.md`
- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`
- `PROJECT_STAGE_STATUS.md`
- `docs/performance-benchmark.md`
- `企业网盘开发者技术计划书.md`

## 2026-08-03 Sprint 3 对象存储稳定性与同 hash 并发闭环

### 当前状态

- Sprint 3 的 MinIO SDK 私有 multipart 方法、同 hash 首次上传竞争、异常 complete 恢复和失败临时对象清理已完成。
- 此记录建立时 `PROJECT_STAGE_STATUS.md` 中 Sprint 3 尚余目标规模压测、策略/账户管理 API 和水印/DLP；这些项目已由上方 2026-08-03 收尾记录全部完成。

### 已完成

- 新增 `S3MultipartControlClient`，使用 MinIO 公共 `get_presigned_url` 和标准 S3 HTTP POST/DELETE/XML 完成 create、complete、abort，不再调用三个 SDK 私有 multipart 方法。
- 新增控制请求超时和控制 URL 有效期配置；MinIO Python 依赖范围收紧为 `>=7.2.20,<8`，避免未经验证的主版本升级。
- complete 请求异常但对象已由存储端提交时，通过 `stat_object` 恢复 ETag 和大小；不存在 provider upload 的 abort 作为幂等成功处理。
- 上传失败统一最佳努力 abort multipart 并删除受控 `uploads/...` 临时对象，`upload.failed` 审计记录 `cleanup_status` 和 `cleanup_errors`。
- 同 hash blob 创建改为 savepoint 内插入；唯一约束竞争失败后读取已提交 blob 并原子增加引用，避免把 blob 竞争误报为同名文件冲突。

### 验证

- `uv lock --check` 通过。
- 新增 multipart 控制面单测 `3 passed`。
- 真实固定版本 MinIO 定向 multipart 用例 `1 passed`，覆盖 create、预签名 PUT、complete、hash 和 abort。
- hash 不匹配失败清理定向用例 `1 passed`，确认会话为 `failed`、multipart 已 abort、临时对象已删除且审计清理结果为空错误。
- 临时 PostgreSQL 16 容器执行当前 migration 后，新增同 hash 双会话竞争用例 `1 passed`，确认只创建一个 blob 且 `ref_count=2`。
- 变更文件 Ruff format/check 与相关模块 Mypy 通过；未运行全量 pytest、备份恢复、性能压测或无关模块测试。
- 两个临时 MinIO 容器和一个临时 PostgreSQL 容器均已删除。

### 下一步

1. 本记录中的三个待办已由上方“配额、安全与目标性能收尾”全部完成。
2. 后续按工程顺序进入 `BE-038`，不重复 Sprint 3 已通过测试和 target 工件。

## 2026-08-02 Sprint 2 剩余增强闭环

### 当前状态

- `PROJECT_STAGE_STATUS.md` 中 Sprint 2 剩余的 `keep_both/replace` 冲突策略和大目录后台化已完成。
- 运行时 OpenAPI 从 45 个操作增加到 47 个；新增后台操作状态查询和失败重试入口。
- migration head 更新为 `20260802_0016`。

### 已完成

- 创建文件夹、移动、恢复和对应批量入口支持 `conflict_policy=fail|keep_both|replace`。
- `keep_both` 使用确定性的 `名称 (n)`，文件名生成器保留扩展名并遵守 255 字符限制。
- `replace` 先复用现有删除语义把当前同名节点移入回收站，再创建、移动或恢复目标节点；删除权限不足时仍按资源隐藏规则拒绝，不做静默覆盖或彻底删除。
- `nodes` 新增 `deleted_root_id`，`file_tree_operations` 保存删除、恢复、彻底删除的任务状态、总量、已处理量、释放容量、尝试次数和失败码。
- 子树规模超过 `DRIVE_FILE_TREE_ASYNC_THRESHOLD` 时，根节点在请求事务中先进入目标状态并返回 HTTP 202；普通目录继续同步完成，不改变既有响应。
- 新增 `GET /api/v1/files/operations/{operation_id}` 和 `POST /api/v1/files/operations/{operation_id}/retry`，按租户和任务创建者隔离。
- maintenance Worker 新增 `file.process_tree_operations`，使用递归 CTE 按深度选择节点，并以 `DRIVE_FILE_TREE_OPERATION_BATCH_SIZE` 分段提交；删除/恢复按父子顺序推进，彻底删除按叶到根处理版本、容量和 blob 引用。
- pending/running 任务由 Celery beat 周期领取；每批以 PostgreSQL 剩余状态为游标，Worker 中断或进程重启后可继续，失败任务保留错误码并支持显式重试。
- 批量文件操作检测到大目录任务时在逐项结果中返回对应 `operation_id`，并继续受原 `Idempotency-Key` 响应重放保护。
- 新任务已接入 maintenance 健康状态、Compose 环境变量和 Windows/本地环境模板。

### 验证

- 新增 `tests/test_file_conflict_policies.py`：`3 passed`，覆盖创建、移动和恢复的 `keep_both/replace`。
- 新增 `tests/test_large_tree_operations.py`：`2 passed`，覆盖 1 节点批次下的中断续跑、删除、恢复、彻底删除、容量/blob 引用释放、状态查询和失败重试。
- 合并运行冲突策略、大目录、Celery schedule、安全矩阵和真实跨租户定向用例，结果为 `61 passed`。
- 20 个受影响 Python 文件 Ruff format check 和 Ruff lint 通过。
- `uv run mypy app` 结果为 155 个源码文件全部通过。
- `uv run alembic heads` 返回 `20260802_0016 (head)`。
- maintenance 告警 YAML 解析通过；根 `compose.windows.yml` 使用 `.env.windows.example` 静态配置解析通过；`git diff --check` 通过。
- 未运行旧 `BE-036/037` 测试、全量回归、Docker 容器启动、备份恢复或性能压测。

### 边界

- 上传初始化的 `conflict_policy` 仍是 fail-only；若未来把 replace 映射为现有文件的新版本，必须进入上传/版本事务并重新验证容量、幂等和审计。
- 本轮完成文件树删除、恢复和彻底删除后台化；大目录权限重算、管理后台任务页面和 closure table 规模触发条件继续后续治理。
- periodic Worker 当前按配置间隔领取任务；生产应继续抓取 maintenance Worker 指标并加载现有连续失败/stale 告警规则。

### 下一步

1. 提交并推送 Sprint 2 剩余增强。
2. 按工程顺序进入 `BE-038` 内部分享接收端。

### 涉及文件

- `backend/app/core/config.py`
- `backend/app/core/maintenance_health.py`
- `backend/app/infrastructure/queue/celery_app.py`
- `backend/app/infrastructure/queue/schedule.py`
- `backend/app/modules/file/batch_service.py`
- `backend/app/modules/file/models.py`
- `backend/app/modules/file/repository.py`
- `backend/app/modules/file/router.py`
- `backend/app/modules/file/schemas.py`
- `backend/app/modules/file/service.py`
- `backend/app/modules/file/tree_operations.py`
- `backend/app/modules/file/validators.py`
- `backend/app/workers/file_tasks.py`
- `backend/migrations/versions/20260802_0016_large_tree_operations.py`
- `backend/tests/test_file_conflict_policies.py`
- `backend/tests/test_large_tree_operations.py`
- `backend/tests/test_celery_schedule.py`
- `backend/tests/security_route_matrix.py`
- `backend/tests/test_route_security_matrix.py`
- `backend/tests/test_route_security_cross_tenant.py`
- `.env.windows.example`
- `backend/.env.example`
- `compose.windows.yml`
- `README.md`
- `backend/README.md`
- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`
- `PROJECT_STAGE_STATUS.md`
- `docs/deployment-windows-docker.md`
- `docs/maintenance-monitoring.md`
- `企业网盘开发者技术计划书.md`

## 2026-08-02 BE-037 回收站列表与批量文件操作

### 当前状态

- 已从 2026-08-01 暂停检查点恢复并完成 `BE-037`，未重复执行 `BE-036`、全量回归、Docker 集成、备份恢复或性能压测。
- 运行时 OpenAPI 由 40 个 route 增加到 45 个；安全矩阵同步为 25 个 CSRF 写入口和 15 个登录态读取入口。
- 数据库 migration head 更新为 `20260801_0015`。

### 已完成

- 新增 `GET /api/v1/files/trash`，按 `deleted_at DESC, id DESC` 使用服务端签名 cursor 分页，只返回没有同删除时间/删除人父节点的删除批次根节点，并返回当前用户的 `delete`/`restore` 权限。
- 新增 `POST /api/v1/files/batch-delete`、`batch-move`、`batch-restore`、`batch-purge`，请求最多包含 100 个节点，响应按输入顺序逐项返回 `success` 或失败错误码。
- 把单项移动、删除、恢复和彻底删除整理为不自行提交的事务单元；单项接口仍保持原有提交/回滚行为，批量接口为每个节点建立 savepoint，业务失败不回滚其他成功项。
- 新增 `file_batch_operations` 和 `20260801_0015_file_batch_idempotency.py`，以 `tenant_id + user_id + operation + idempotency_key_hash` 唯一约束保存请求 hash 和最终响应。
- 四个批量写入口强制接收 `Idempotency-Key`：同 key 同请求直接重放已保存响应，同 key 不同请求返回 `IDEMPOTENCY_KEY_REUSED`，并发唯一键竞争返回明确冲突。
- 批量操作继续复用现有节点权限、审计、搜索 outbox、多维配额释放和 blob 引用计数逻辑，没有建立第二套文件操作语义。
- 将批量幂等编排拆分到 `file/batch_service.py`，避免继续扩大既有 `file/service.py`。
- 安全路由矩阵、CSRF 计数、登录态读取计数和真实跨租户资源用例已同步；跨租户批量请求只逐项返回 `NODE_NOT_FOUND`，不泄露资源存在性。

### 验证

- 变更文件 Ruff format check 和 Ruff lint 已通过。
- `uv run mypy app` 结果为 154 个源码文件全部通过。
- 新增集中定向测试 `tests/test_file_batch_operations.py` 最终结果为 `3 passed`，覆盖回收站两页 cursor、批量删除/恢复、批量移动部分失败、批量彻底删除、持久化重放和同 key 异请求冲突。
- `tests/test_route_security_matrix.py` 结果为 `51 passed`，运行时 OpenAPI 与 45 个 route 精确一致；新增写入口缺少 CSRF 时仍统一拒绝。
- `tests/test_route_security_cross_tenant.py::test_internal_routes_hide_foreign_tenant_resources` 结果为 `1 passed`。
- `uv run alembic heads` 返回 `20260801_0015 (head)`；`git diff --check` 通过。
- 本轮没有执行全量测试、Docker、真实 MinIO、备份恢复、性能压测或 `BE-036` 既有测试。

### 边界与风险

- 普通目录的删除、恢复和彻底删除仍同步遍历子树；超大目录的任务状态、游标分片和长事务拆分继续归 `BE-046`。
- 创建/移动的 `keep_both`、`replace` 冲突策略仍未进入本轮 `BE-037`，当前保持 fail-only，避免提前改变上传和版本覆盖语义。
- 幂等记录当前随业务数据长期保留；保留期、归档和治理指标应与后续生命周期管理统一设计。

### 下一步

1. 提交并推送 `BE-037` 的代码、迁移、测试和文档。
2. 按工程顺序进入 `BE-038`，实现“分享给我的”、创建者分享列表、接收人详情与受控下载。
3. `BE-029` 目标规模压测继续保留到发布性能门禁，不回到当前功能开发路径重复执行。

### 涉及文件

- `backend/app/modules/file/batch_service.py`
- `backend/app/modules/file/models.py`
- `backend/app/modules/file/repository.py`
- `backend/app/modules/file/router.py`
- `backend/app/modules/file/schemas.py`
- `backend/app/modules/file/service.py`
- `backend/migrations/versions/20260801_0015_file_batch_idempotency.py`
- `backend/tests/test_file_batch_operations.py`
- `backend/tests/security_route_matrix.py`
- `backend/tests/test_route_security_matrix.py`
- `backend/tests/test_route_security_cross_tenant.py`
- `README.md`
- `backend/README.md`
- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`
- `PROJECT_STAGE_STATUS.md`
- `企业网盘开发者技术计划书.md`

## 2026-08-01 暂停检查点：BE-037 回收站列表与批量文件操作

### Git 与工作区

- 当前分支：`dev`。
- 当前 HEAD：`d7a05b4daf2e359ec0022a51e290929bfaf7ff85`（`feat: 完成文件版本列表下载与回滚`）。
- `d7a05b4` 已成功推送到 `origin/dev`。
- 暂停前工作树干净；本次只修改 `PROJECT_PROGRESS.md` 保存检查点，未提交、未 stash，也未改动 `BE-037` 业务代码。

### 最新确认结果

- `BE-036` 代码、文档和安全矩阵已提交推送；其唯一一次最小验证结果仍为 Ruff、Mypy 通过和 `3 passed`，恢复时不要重复运行。
- `BE-037` 已完成开工前审查：读取了 `AGENT.md`、`PROJECT_PLAN.md`、技术计划书中的接口契约，以及现有 file router/service/repository/schema、删除/移动/恢复/彻底删除测试和安全路由矩阵。
- 当前仓库没有通用 `Idempotency-Key` 持久化实现，也没有回收站用户分页接口或四个批量文件接口；最新 migration head 为 `20260801_0014`。
- 本轮未启动 Docker、API、Worker、性能工具或测试进程。

### 已确认的 BE-037 实现方向

- 新增 `GET /api/v1/files/trash?space_id=...&cursor=...&page_size=...`，按 `deleted_at DESC, id DESC` 使用服务端签名 cursor，只列出删除批次根节点，避免目录子树中的每个后代重复出现在回收站顶层。
- 新增 `POST /api/v1/files/batch-delete`、`batch-move`、`batch-restore`、`batch-purge`；每个请求最多处理有限数量节点，响应逐项返回成功或错误码，单项业务失败不吞掉其他项结果。
- 四个批量写入口强制接收 `Idempotency-Key`。计划新增持久化批量操作记录和 `20260801_0015` migration，以 `tenant + user + operation + key hash` 唯一约束，并保存请求 hash 与最终响应；同 key 不同请求返回冲突，相同请求直接重放已保存结果。
- 为保证幂等记录与成功项同时提交，同时支持部分失败，计划把现有单项删除、移动、恢复和彻底删除逻辑拆成“不自行 commit”的内部事务单元；批量服务在外层事务内为每项使用 savepoint，最后原子写入批量响应。
- 继续复用现有节点权限、容量释放、blob 引用、审计和搜索 outbox 逻辑，不另写一套文件操作语义。
- 新增 5 个 route 后，安全矩阵预期从 40 调整到 45；CSRF 写入口预期从 21 调整到 25，登录态读取入口预期从 14 调整到 15，并同步真实跨租户 fixture。

### 精确恢复步骤

1. 从本检查点直接实现 `BE-037`，不要重新审查 `BE-036`，不要运行其既有测试。
2. 先修改 `backend/app/modules/file/models.py`、`repository.py`、`schemas.py`、`service.py`、`router.py`，并新增 `backend/migrations/versions/20260801_0015_file_batch_idempotency.py`。
3. 再同步 `backend/tests/security_route_matrix.py`、`test_route_security_matrix.py` 和 `test_route_security_cross_tenant.py`，新增一个集中覆盖回收站分页、四类批量操作、部分失败与幂等重放的定向测试文件。
4. 只执行一次变更文件 Ruff、`uv run mypy app`、新增定向测试和 OpenAPI 精确对账；不执行全量测试、Docker 集成、备份恢复或性能压测。
5. 验证通过后同步 README、计划书和本进度文件，执行一次 `git diff --check`，提交并推送 `BE-037`，然后按编号进入 `BE-038`。

## 2026-08-01 BE-036 文件版本列表、指定版本下载与回滚

### 当前状态

- 文件版本列表、指定历史版本下载和回滚为新版本的核心 API 已完成。
- 下一项按编号进入 `BE-037` 回收站列表与批量文件操作；继续执行“实现优先、每项一次最小定向验证”，不恢复目标压测或全量重复测试。

### 已完成

- 新增 `GET /api/v1/files/{node_id}/versions`，使用节点级 `read_meta` 权限和签名 cursor 分页，返回 `current_version_id` 并逐项标记 `is_current`。
- 新增 `GET /api/v1/files/{node_id}/versions/{version_id}/download`，使用节点级 `download` 权限、现有预签名限流和 DTP/1 响应，允许下载同一节点的指定历史版本。
- 新增 `POST /api/v1/files/{node_id}/versions/{version_id}/rollback`，使用节点级 `update` 权限；支持可选 `expected_current_version_id`，当前版本变化时返回 `FILE_VERSION_CONFLICT`。
- 回滚锁定目标节点，生成递增 `version_no`，复用历史版本 blob 并增加引用计数；旧版本记录保持不变。
- 新版本创建与空间、可选用户/租户及匹配策略配额扣减处于同一事务，并更新 `nodes.current_version_id`。
- 回滚写入 `file.version.rolled_back` 审计及 `search.index_requested`、`search.extract_requested`、`preview.render_requested` 事件；列表和历史下载分别写入 `file.versions.listed`、`file.version.downloaded`。
- 安全路由矩阵和跨租户 fixture 已同步，运行时 OpenAPI 路由总数更新为 40，排除 ping/login 后为 38。

### 验证

- 只运行一次变更文件 Ruff format check、Ruff lint 和 `uv run mypy app`，全部通过。
- 只运行 `tests/test_file_versions.py` 与安全矩阵/OpenAPI 精确对账用例，结果为 `3 passed`。
- 定向用例覆盖签名 cursor、历史版本下载、回滚创建版本 2、blob 引用与配额 ledger、审计/搜索/预览事件，以及 viewer 可列表/下载但不可回滚；未运行全量测试、Docker 集成或性能压测。

### 边界

- 当前版本下载仍可使用 `/files/{node_id}/download`，历史版本使用带 `version_id` 的独立入口；受控代理 `/content` 目前只代理当前版本。
- 回滚按新文件版本计入容量，不释放被替换的当前版本容量；只有彻底删除相应版本后才按正向流水释放。
- 批量版本回滚、版本备注/保留策略和历史版本代理 Range 不在本轮核心范围。

### 下一步

1. 提交并推送 `BE-036`。
2. 实现 `BE-037` 回收站签名 cursor 列表，以及批量删除、移动、恢复和彻底删除。
3. 所有批量写入口接入 `Idempotency-Key`，逐项返回成功或失败，不以单项失败回滚已完成的其他项。

### 涉及文件

- `backend/app/modules/file/repository.py`
- `backend/app/modules/file/router.py`
- `backend/app/modules/file/schemas.py`
- `backend/app/modules/file/version_service.py`
- `backend/tests/test_file_versions.py`
- `backend/tests/security_route_matrix.py`
- `backend/tests/test_route_security_matrix.py`
- `backend/tests/test_route_security_cross_tenant.py`
- `README.md`
- `backend/README.md`
- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`
- `docs/drive-transfer-protocol-v1.md`
- `企业网盘开发者技术计划书.md`

## 2026-08-01 BE-035 维护任务调度告警

### 当前状态

- 五个既有 maintenance 周期任务已接入统一连续失败状态、指标和告警规则；未新增第二套调度器。
- 下一项按编号进入 `BE-036` 文件版本列表、指定版本下载与回滚。

### 已完成

- 保留 Celery beat 的 UTC 调度和 maintenance 专用队列，统一监控 `upload.expire_sessions`、回收站清理、blob 清理、孤儿对象扫描和空间容量校准。
- 新增 Redis 原子状态 `maintenance_health:{task_name}`，跨 Worker 子进程和重启保存连续失败、告警状态、最近完成/成功/失败时间；成功执行自动清零。
- Celery `task_postrun` signal 在任务结束后更新状态，达到连续失败阈值时写结构化 `maintenance.alert` 错误日志；监控写入异常不会改变原任务结果。
- maintenance Worker 新增连续失败、告警、stale、最近完成/成功/失败时间 Gauge，以及从任务返回字典采集的通用 `maintenance_task_result_total{task,metric}` Counter。
- Worker 主进程按配置周期从 Redis 刷新 Gauge，任务超出多个调度周期未完成时设置 stale。
- 新增 `deploy/monitoring/maintenance-alerts.yml`，覆盖连续失败、长时间未完成、对象存储错误和容量漂移。
- 新增 `docs/maintenance-monitoring.md`，记录配置、指标、Redis 边界、Prometheus 接入和排障顺序。

### 边界

- 该 `BE-035` 阶段当时尚未把 Prometheus Server/Alertmanager 纳入根 Compose；Sprint 6 已由可选 `monitoring` profile 补齐，生产监控仍需配置真实企业值班接收端。
- Redis 只保存运行监控状态，不替代 PostgreSQL、对象存储和审计事实；Redis 数据丢失会重置失败 streak，但不会改变业务数据。
- 当前告警覆盖既有五个维护任务；过期分享、预览产物和后续生命周期任务接入时必须加入同一任务清单和调度间隔映射。

### 验证

- 只运行一次变更文件 Ruff format check、Ruff lint 和 `uv run mypy app`，全部通过。
- 只运行 `tests/test_observability.py` 与 `tests/test_celery_schedule.py`，结果为 `8 passed`。
- 已用项目环境解析 `deploy/monitoring/maintenance-alerts.yml`，确认规则结构有效；未启动 Docker、全量测试或性能压测。

### 下一步

1. 只运行一次维护监控定向 Ruff、Mypy 和 observability/schedule 测试后提交推送。
2. 进入 `BE-036`，实现文件版本列表、指定版本下载和回滚为新版本，并复用权限、容量和审计服务。
3. 该阶段规划由部署治理补齐 Alertmanager、Grafana 看板和通知路由；Sprint 6 现已完成 profile、规则和看板，真实接收端继续由生产环境配置。

### 涉及文件

- `backend/app/core/maintenance_health.py`
- `backend/app/core/worker_observability.py`
- `backend/app/core/worker_metrics.py`
- `backend/app/core/config.py`
- `backend/tests/test_observability.py`
- `deploy/monitoring/maintenance-alerts.yml`
- `docs/maintenance-monitoring.md`
- `docs/deployment-windows-docker.md`
- `.env.windows.example`
- `compose.windows.yml`
- `README.md`
- `backend/README.md`
- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`
- `企业网盘开发者技术计划书.md`

## 2026-08-01 BE-034 高密级下载代理

### 当前状态

- 已完成内部受控代理下载核心链路，普通文件预签名直连保持不变。
- 下一项按编号进入 `BE-035` 维护任务调度告警；本轮只保留代理下载定向验证，不执行全量测试或性能压测。

### 已完成

- 新增 `GET /api/v1/files/{node_id}/content`，复用现有 Cookie Session、节点级 `download` 权限、租户边界、当前版本和 active blob 校验。
- 扩展 `StorageAdapter.stream_object`，MinIO/S3 适配器按 offset、length 和固定 chunk 异步流式读取；内存测试适配器提供同契约实现。
- 支持完整下载和标准单段 Range：`start-end`、`start-`、`-suffix`；合法部分请求返回 HTTP 206。
- 多段、反向、不可满足或超过单段上限的请求返回 HTTP 416，并携带 `Accept-Ranges` 与 `Content-Range: bytes */{size}`。
- 响应包含 `Content-Length`、ETag、UTF-8 `Content-Disposition`、`Cache-Control: private, no-store`、`X-Content-Type-Options` 和 DTP/1 响应头。
- 代理下载使用独立限流配置；允许与拒绝均写入 `file.downloaded`，代理审计记录 `delivery_mode`、版本、Range 起止和响应字节数。
- 把新增 route 同步到安全矩阵和跨租户 fixture 映射，运行时 OpenAPI 口径更新为 37 个 route。

### 验证

- 只运行一次变更文件 Ruff format check、Ruff lint 和 `uv run mypy app`，全部通过。
- 只运行 `tests/test_download.py` 与安全矩阵/OpenAPI 精确对账单测，结果为 `6 passed`；未运行全量测试、Docker 集成、性能压测或旧模块重复回归。

### 边界

- 此记录建立时任何具备节点下载权限的客户端都可显式选择代理入口；2026-08-03 已补文件安全策略自动选路。
- 此记录建立时外链分享只返回短期预签名 URL；2026-08-03 已补动态水印和关键字 DLP，外链代理流仍属后续边界。
- 单次部分 Range 默认上限为 64 MiB，完整无 Range 请求不受该部分范围上限限制；API 带宽和连接资源需要由部署层继续监控。

### 下一步

1. 只运行一次代理下载定向测试、Ruff 和 Mypy，确认最小闭环后提交推送。
2. 进入 `BE-035`，为 maintenance 任务增加连续失败状态、Prometheus 指标和可配置告警阈值。
3. 密级自动选路、图片/PDF 水印和关键字 DLP 已由 2026-08-03 收尾完成；仅外链代理、历史版本专用水印和复杂内容识别继续后续治理。

### 涉及文件

- `backend/app/modules/file/download.py`
- `backend/app/modules/file/download_range.py`
- `backend/app/modules/file/router.py`
- `backend/app/infrastructure/storage/base.py`
- `backend/app/infrastructure/storage/s3.py`
- `backend/app/infrastructure/storage/testing.py`
- `backend/app/api/errors.py`
- `backend/app/api/deps.py`
- `backend/app/core/config.py`
- `backend/tests/test_download.py`
- `backend/tests/security_route_matrix.py`
- `backend/tests/test_route_security_matrix.py`
- `backend/tests/test_route_security_cross_tenant.py`
- `.env.windows.example`
- `compose.windows.yml`
- `docs/drive-transfer-protocol-v1.md`
- `README.md`
- `backend/README.md`
- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`
- `企业网盘开发者技术计划书.md`

## 2026-08-01 BE-033 多维配额策略

### 当前状态

- `BE-033` 核心运行时已完成，工程主线不再被 `BE-029` 目标规模压测阻塞。
- 下一项按编号进入 `BE-034` 高密级下载代理与 HTTP Range；后续验证只运行与新增功能直接相关的最小定向集合。

### 已完成

- 新增 `quota_policies` 表、SQLAlchemy 模型、迁移约束和租户优先级索引，支持扩展名、MIME 前缀、累计额度、单文件大小和启停状态。
- 复用 `quota_accounts` / `quota_ledger` 表达 `space`、`tenant`、`user`、`policy` 四类账户；用户和租户默认额度为 `0` 时关闭对应维度。
- 上传初始化执行多维快速检查；秒传和 multipart complete 创建版本时在同一事务内按固定顺序执行原子条件扣减，任一维度不足都会回滚本次创建。
- 彻底删除和回收站保留期清理按文件版本正向流水释放全部关联账户，兼容旧版本只有空间流水的历史数据。
- 新增 `DRIVE_DEFAULT_USER_QUOTA_BYTES`、`DRIVE_DEFAULT_TENANT_QUOTA_BYTES`、`DRIVE_QUOTA_POLICY_ENABLED`，并同步 Windows 环境模板和 Compose。
- 明确 `quota_policies` 当前由数据库事实表提供；2026-08-03 已补账户/策略管理 HTTP API，部门额度和多维通用校准继续后续治理。

### 验证

- 复用前一轮定向回归结果：原上传、空间容量校准和回收站清理相关测试 `18 passed`，新增代码定向 Ruff/Mypy 与 Alembic 静态 SQL 已通过。
- 本轮只补齐遗漏的 `storage_adapter` 测试夹具导入，并单次运行 `uv run pytest -p no:cacheprovider tests/test_quota_multidimensional.py -q`，结果为 `2 passed`。
- 未重新执行 `BE-029` 压测、完整 Docker 恢复或全量测试。

### 风险与边界

- 现有账户的 `limit_bytes` 是数据库事实，修改环境默认值不会自动覆盖已创建账户；2026-08-03 已提供管理 API 显式调整并写审计。
- 策略按上传文件名扩展名和请求中的 MIME 元数据匹配；2026-08-03 已补密级和基于已有搜索正文的关键字 DLP，复杂内容分类/OCR 继续后续治理。
- `quota.reconcile_space_usage` 仍只校准空间账户，多维通用校准尚未实现。

### 下一步

1. 完成一次定向 Ruff、Mypy 和迁移 SQL 检查后提交并推送当前成果。
2. 实现 `BE-034`：为高密级/强审计场景增加后端代理下载、单段 HTTP Range、流式响应和下载结果审计；普通文件继续使用短期预签名直连。
3. `BE-029` 目标规模数据和最终 target `upload_complete` 已于 2026-08-03 完成；后续直接复用通过工件。

### 涉及文件

- `backend/app/modules/quota/models.py`
- `backend/app/modules/quota/repository.py`
- `backend/app/modules/quota/service.py`
- `backend/migrations/versions/20260801_0014_multidimensional_quota.py`
- `backend/app/modules/upload/service.py`
- `backend/app/modules/upload/lifecycle.py`
- `backend/app/modules/file/service.py`
- `backend/app/modules/file/trash_cleanup.py`
- `backend/tests/test_quota_multidimensional.py`
- `.env.windows.example`
- `compose.windows.yml`
- `README.md`
- `backend/README.md`
- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`
- `企业网盘开发者技术计划书.md`

## 2026-08-01 BE-031/BE-032 对象存储验收对账

### 当前状态

- `BE-031` 与 `BE-032` 的既有实现已逐条对照源码、测试、CI 配置和技术计划验收，当前任务验收完成。
- 后续只保留不属于本轮验收的企业级补强：MinIO SDK 升级兼容、异常恢复、同 hash 并发竞争，以及 `BE-035` 的失败告警和运行看板。

### 已完成

- `file.cleanup_orphaned_objects` 默认 dry-run，按对象存储游标分批扫描受控最终对象 key；显式删除只处理无 DB `file_blobs.storage_key` 引用的对象。
- 非受控 key、已引用对象和跨批次游标均有测试；删除失败保留对象并写错误审计，审计 metadata 只保存 storage key hash，不保存原始 key。
- 维护任务已注册到 Celery maintenance 队列和 beat，默认以 `dry_run=true`、`scan_all=true` 调度；worker 汇总多租户和多批次结果。
- 真实 MinIO 集成覆盖对象读写/hash、copy、delete、list 游标、预签名下载、multipart 创建/分片预签名/abort/complete、服务端 hash 和孤儿扫描。

### 验证

- 本机真实 Docker：使用 `.env.windows.example` 中已存在的 MinIO digest 镜像，运行阶段 `--pull never`、`0.50 CPU / 512m / 512m swap / 128 PIDs`；定向 `test_blob_cleanup.py`、`test_celery_schedule.py`、`test_observability.py`、`test_storage_minio_integration.py` 共 `20 passed`，结束后测试容器为 `0`。
- GitHub Actions `backend-ci` 已通过 `DRIVE_RUN_MINIO_TESTS=1` 启动临时 MinIO，并执行同一真实对象存储测试路径；最近闭环 run `30681696299` 的 backend、Windows、镜像策略和两个 MinIO supply-chain job 全部成功。

### 下一步

1. 进入 `BE-029 target`，先实现可恢复、分阶段、资源受限、可清理的目标数据生成器。
2. 再执行真实 multipart complete 压测和完整 target profile，记录硬件、镜像 digest、数据量、p50/p95/p99、错误率、OpenSearch refresh/磁盘与审计写入耗时。

## 2026-08-01 BE-029 target 数据生成器

### 当前状态

- 已实现 `backend/performance/target_state.py`、`target_opensearch.py`、`target_audit.py` 和 `target_data.py`，但尚未把 100 万 OpenSearch 文档和 1,000 万审计日志灌入真实环境。
- 生成器把 OpenSearch 与审计分成独立阶段，使用确定性 ID、专属 `be029-*` index/action、原子 state checkpoint、批次上限和节流参数；大规模执行必须显式 `--confirm-large-target`。
- 清理要求精确匹配 `run_id`，只删除当前 state 所属 index 和审计 action，不执行全库、全 index 或不受控 Docker 清理。
- CLI 默认每次只执行 1 批，只有显式 `--max-batches 0` 才不限批次；当前小规模恢复与清理闭环已经完成，目标规模验收仍未完成。

### 已完成

- OpenSearch 生成器支持单批/多批恢复，使用单 shard、零 replica、生成期间关闭 refresh，完成后恢复 refresh 并记录真实文档数与 index store bytes。
- PostgreSQL 审计生成器使用临时 staging table + `COPY` + `ON CONFLICT DO NOTHING`，每批提交后保存 checkpoint；清理按批次删除并可中断恢复。
- 修复 `asyncpg.Connection` 不支持异步上下文管理器的问题，改为 `try/finally` 关闭连接，并增加异常路径连接关闭测试。
- 真实 Docker run `be029-docker-6f4bbdb7`：默认单批生成并观察到 OpenSearch/审计 `100/100`，显式不限批次后恢复到 `1,000/1,000`；cleanup 后审计剩余 `0`、专属 index 返回 `404`、测试容器剩余 `0`。
- 资源边界：PostgreSQL `0.75 CPU / 768 MiB / 128 PIDs`，OpenSearch `1 CPU / 1536 MiB / 256 PIDs`，均使用本地固定镜像和 `--pull never`；完成态快照约为 PostgreSQL `70.07 MiB`、OpenSearch `1.229 GiB`。
- 单元与静态验证：CLI 默认批次与连接关闭新增回归已通过，Ruff、格式检查和 Mypy 全部通过。
- `upload_complete` 已补齐真实 multipart 链路：DTP/1 init、part presign、无 Cookie/无代理环境继承的 MinIO PUT、complete、Server-Timing 分段和节点清理；每用户首个存储连接 warm-up 单独计量。
- `report.json` 已升级为 `BE-029/2`，新增 p50、平均/最小/最大延迟、汇总错误率、主机内存/磁盘、Docker server、compose 容器限额与镜像 digest、PostgreSQL 索引/数据库体量和 OpenSearch 状态。

### 未完成

- 尚未完成真实目标规模数据灌入、真实 multipart complete 50 RPS/延迟分解、100 RPS 初始化上传和完整 target profile。
- 尚未把目标数据报告（硬件、镜像 digest、数据库索引、refresh、磁盘、p50/p95/p99、错误率）接入现有 `report.json`。

### 下一步

1. 先提交并推送本轮 multipart、报告和文档改动，确认 GitHub Actions。
2. 继续在受限真实 Compose 中分阶段灌入 100 万 OpenSearch 文档和 1,000 万审计日志，利用 `BE-029/2` 报告记录每批耗时、refresh/store、数据库索引和磁盘。
3. 用同一隔离 project 完成 target profile 的 10,000 节点、100 RPS 初始化上传、50 RPS complete 和搜索/审计门槛，再提交最终 BE-029 验收。

## 2026-08-01 BE-030 路由、租户与网络安全矩阵

### 当前状态

- route/租户/对抗输入批次已通过提交 `94ed1d4` 和 GitHub Actions run `30680735602` 闭环，5 个 job 全部成功。
- Host/CORS 与真实 Nginx 原始 HTTP 收尾已通过提交 `65ab794` 和 GitHub Actions run `30681448854` 闭环，5 个 job 全部成功。
- 提交 `ff00542` 已消除 MinIO 供应链报告阶段的误导性“Failed minimum severity”注解；run `30681696299` 再次通过全部 5 个 job，注解命中数为 0，新增 Critical 基线门禁仍然保留。
- `BE-030` 已完成本地门禁、真实 Docker 验证和远端 CI 闭环。
- 运行时 OpenAPI 当前包含 36 个 `/api/v1` method + path；排除 `GET /ping` 和 `POST /auth/login` 后为原计划口径的 34 个 route。

### 已完成

- 新增 `tests/security_route_matrix.py`，为全部 36 个 API route 固定 method、模板路径、最小合法请求、访问模式、租户范围、CSRF 模式和资源授权策略。
- 新增 OpenAPI 集合一致性门禁：矩阵与 `create_app(settings).openapi()["paths"]` 必须完全一致，新增、删除或改名 route 未同步矩阵时测试会失败。
- 对全部 36 个 route 执行匿名 ASGI 请求：受保护入口统一返回 `401/AUTH_REQUIRED`；登录返回统一无效凭据；无 Cookie 登出保持幂等；ping 和外链入口保持既定公开边界。
- 对全部 20 个登录态副作用 route 执行缺失 CSRF 测试，统一返回 `403/CSRF_TOKEN_INVALID`；有会话登出也必须校验 CSRF，无会话登出仍可幂等成功。
- 验证 11 个登录态读取 route 可通过身份门禁，普通用户访问管理员审计 route 返回 `403/ADMIN_REQUIRED`。
- 建立真实第二租户夹具，包含用户、空间、根目录、活动/回收站节点、文件版本、ACL、外链分享和未完成上传会话；26 个内部资源 route 使用真实外租户 ID 时全部返回 404，空间列表和管理员审计结果也不泄露外租户记录。
- 验证已登录成员在空间成员关系被删除后无需重新登录即失去空间列表和写权限，活跃 Cookie Session 不缓存业务授权。
- 新增损坏图片、超大图片、Office 扩展名命令注入、文档路径穿越/NUL、Range 授权、预签名 URL 凭据隔离和不同 token 外链穷举测试。
- 外链访问和下载在攻击者轮换原始 token 时仍受来源 IP 总量窗口限制；前两次无效 token 返回 404，达到临时测试门槛后返回 `429/RATE_LIMITED`。
- 新增 Trusted Host 与 CORS 预检测试：未知 Host 在 route dispatch 前返回 400，CORS 只回显显式允许的 origin。
- 新增 `scripts/smoke_gateway_security_docker.py`，只使用本地已有 Nginx 镜像并固定 `--pull never`，容器限制为 `0.25 CPU / 128m / 64 PIDs`、只读根文件系统和 `no-new-privileges`。
- 真实 Nginx 原始 TCP smoke 验证：健康检查 200、`Content-Length + Transfer-Encoding` 冲突 400、重复冲突 `Content-Length` 400、API Host 的 2 KiB 请求在 1 KiB 门槛下返回 413、storage Host 对同一长度先返回 `100 Continue`。
- `backend-ci` 增加显式 Nginx/Certbot pull，后续模板校验和 raw HTTP smoke 全部使用 `--pull never`，不再把镜像下载隐含在验证命令中。

### 阻塞与风险

- 当前 Range 验证确认请求头不能绕过权限且预签名响应不携带 Cookie/CSRF；完整后端代理 Range 属于 `BE-034`，尚未实现。
- MinIO Server/Client 既有 Critical 基线、真实公网 DNS/受信 TLS 和外部扫描仍是正式上线风险。

### 下一步

1. 对账 `BE-031`、`BE-032` 的既有实现、真实 MinIO 测试与 CI 验收证据。
2. 继续最早仍未完成的 `BE-029 target` 子任务，按资源受限、分阶段、可恢复、可清理方式补齐目标规模数据生成与验收。

### 验证

- `uv run pytest -o addopts='' tests/test_route_security_matrix.py tests/test_route_security_cross_tenant.py tests/test_security_adversarial.py -q`：`53 passed in 15.63s`。
- 四个新增 Python 文件 Ruff、格式检查与 Mypy：通过。
- `uv lock --check`、全量 Ruff、格式检查、Bandit、pip-audit 和 `uv run mypy app`：全部通过；Bandit 中危/高危为 0，依赖已知漏洞为 0。
- 完整 `uv run pytest -p no:cacheprovider -q`：通过；收集 `245` 个测试，其中 `241 passed, 4 skipped`。
- route/租户批次提交 `94ed1d4` 已推送；GitHub Actions run `30680735602` 的 backend、windows-deployment、minio-image-policy 和两个 MinIO supply-chain job 全部成功。
- 新增 Host/CORS 后 `tests/test_security_adversarial.py`：`10 passed`。
- 真实 Nginx smoke 使用本地 `nginx:1.27-alpine` 镜像 `sha256:65645c7bb6a0...`，结果为 `200/400/400/413/100`；测试容器结束后为 0。
- 网络层收尾后的完整 `uv run pytest -p no:cacheprovider -q`：通过；收集 `247` 个测试，其中 `243 passed, 4 skipped`。
- 网络层提交 `65ab794` 对应 GitHub Actions run `30681448854`：backend、windows-deployment、minio-image-policy 和两个 MinIO supply-chain job 全部成功，backend job 实际通过 raw HTTP security smoke。
- CI 提示修复提交 `ff00542` 对应 GitHub Actions run `30681696299`：5 个 job 全部成功；完整日志中 `Failed minimum severity level`、GitHub `error/warning` 注解和 Grype severity-threshold 假失败文本命中数均为 0。

### 涉及文件

- `backend/tests/security_route_matrix.py`
- `backend/tests/test_route_security_matrix.py`
- `backend/tests/test_route_security_cross_tenant.py`
- `backend/tests/test_security_adversarial.py`
- `backend/scripts/smoke_gateway_security_docker.py`
- `.github/workflows/backend-ci.yml`
- `AGENT.md`
- `docs/security-testing.md`
- `README.md`
- `backend/README.md`
- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`
- `企业网盘开发者技术计划书.md`

## 2026-07-31 BE-030 production Settings 自校验

### 当前状态

- production 配置的应用内 fail-fast 已通过提交 `a52b4ce` 和 GitHub Actions run `30661668693` 闭环。

### 已完成

- `Settings` 在 `environment=production` 时统一校验 debug、限流、关键 secret、PostgreSQL/Redis/Celery 凭据 URL、Trusted Hosts、CORS、S3 公共端点、SameSite 与 Secure Cookie。
- 关键 secret 拒绝过短值、`change-me`/开发默认值和 `$` 间接插值；Pydantic 启用 `hide_input_in_errors`，启动异常不回显传入 secret。
- 本机 HTTP 只在 Trusted Hosts、CORS 和 S3 公共端点全部为 localhost/回环地址时允许；任何非回环生产 Host 会强制 HTTPS、Secure Cookie，并要求 S3 外部端点使用 443。
- FastAPI、Celery Worker/beat、Alembic migration 和管理员 seed 都通过现有 `get_settings()` 触发同一校验，不新增可绕过的第二套启动入口。
- 可观测性 Docker smoke 改用带密码 Redis 和完整 production 安全配置，继续验证 2-worker API、maintenance Worker、真实任务、指标隔离和 trace 关联。
- 新增 `tests/test_config.py` 16 个用例，覆盖本机/公网正例和 debug、关闭限流、弱 secret、无密码 URL、Wildcard、带凭据/路径端点、HTTP 公网 origin、非 443/公网回环 HTTP S3、SameSite=None 与 secret 不回显。

### 阻塞与风险

- 应用内校验不替代 `manage.ps1 -Tls` 的宿主 bind、HSTS、API/MinIO CORS 精确对齐、真实 DNS、证书和 Certbot 邮箱检查。
- 完整 34 route 身份/租户矩阵以及恶意图片、文档、Range、预签名 URL 和外链穷举动态测试仍未完成。

### 下一步

1. 建立 34 个 API route 的身份/租户矩阵。
2. 增加恶意图片/文档、Range、预签名 URL 和外链穷举动态安全测试。

### 验证

- production Settings 定向测试：`16 passed`；FastAPI、Celery、可观测性和 S3 相关回归合计 `35 passed`。
- Ruff、格式检查、Bandit 和 `uv run mypy app`：全部通过；Bandit 中危/高危为 0。
- `uv run pip-audit --local --progress-spinner off`：0 已知漏洞。
- 完整 `uv run pytest`：`188 passed, 4 skipped`。
- runtime 镜像使用 `1 CPU / 2 GiB` BuildKit 上限和 `--pull=false` 重建为 `sha256:d1e18de9bee6a3e725c1cd9bc7c02326cf4b8ce63bcb96dd2eccf567341302b0`，耗时 `8.5s`。
- 真实 Docker 负例：production 仅提供弱/默认配置时容器退出码为 1，错误包含 `Production settings validation failed` 且不包含传入 secret。
- 真实 Docker 正例：PostgreSQL、带密码 Redis、2-worker API 和 maintenance Worker 启动成功，24 次 ping、3 个多进程 gauge 文件、真实 `upload.expire_sessions` 任务、API/Worker trace 均通过。
- Docker smoke 采样峰值为 4 个容器、`53.3%` aggregate Docker CPU、`473.4 MiB` 容器内存和 `3371.8 MiB` Docker/WSL 私有工作集；结束后容器和网络均为 0。
- 根 `compose.windows.yml` 使用 `--no-build --pull never` 和强 production 配置启动成功；migration、seed、minio-init 均退出 0，API 为 healthy，容器内读取到 `environment=production`、`rate_limit=True`。峰值为 5 个运行容器、`123.3%` aggregate Docker CPU 和 `1462.8 MiB` 容器内存；结束后隔离 project 的容器、网络和卷均为 0。
- 提交 `a52b4ce fix: 增加生产配置启动自校验` 已推送到 `origin/dev`；GitHub Actions run `30661668693` 的 backend、windows-deployment、minio-image-policy 和两个 MinIO supply-chain job 全部成功，backend job 实际通过新增配置测试、observability Docker smoke 和 runtime/preview 构建。

### 涉及文件

- `backend/app/core/config.py`
- `backend/tests/test_config.py`
- `backend/scripts/smoke_observability_docker.py`
- `.env.windows.example`
- `AGENT.md`
- `README.md`
- `backend/README.md`
- `docs/deployment-windows-docker.md`
- `docs/security-testing.md`
- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`
- `企业网盘开发者技术计划书.md`

## 2026-07-31 BE-030 安全测试修复首轮

### 当前状态

- `BE-029` 已通过提交 `f0302e2` 和 GitHub Actions run `30652675576` 闭环。
- `BE-030` 首轮依赖、静态代码、登录入口和错误响应修复已通过提交 `25acecf` 和 GitHub Actions run `30660034411` 闭环。

### 已完成

- 使用实际 `.venv` 审计 123 个安装包，发现的 20 条已知漏洞记录全部集中在 `Pillow 12.2.0`；预览 Worker 会读取用户上传图片，因此判定为可达而非误报。
- 生产依赖下限和 `uv.lock` 已升级为 `Pillow 12.3.0`，预览定向测试全部通过；加入安全工具后审计 145 个环境包为 0 已知漏洞。
- dev 依赖新增 `bandit 1.9.4` 和 `pip-audit 2.10.1`；`backend-ci` 在 Ruff 后执行中危/高危静态扫描和实际环境依赖漏洞审计。
- Worker metrics 的 `0.0.0.0:9100` 只监听 Compose 内部网络且不发布宿主端口，对该行精确标注 `B104` 边界；Bandit 中危/高危结果为 0。
- 登录新增 `auth.login.ip` 和 `auth.login.account` 两类 Redis 固定窗口；默认分别为每 60 秒 30 次和 10 次，账号 key 使用租户与用户名规范化值的 SHA-256，不保存原文。
- 不存在租户、用户或停用用户的登录仍执行 Argon2id 校验成本，并统一返回 `AUTH_INVALID_CREDENTIALS`，降低账号存在性时序差异。
- 422 校验错误统一移除 Pydantic 原始 `input`，避免密码、外链口令和 token 被错误响应重复保存。
- 新增 `docs/security-testing.md`，记录威胁模型、命令、首轮结果、有效边界和后续动态测试范围。

### 已闭环

- `backend-ci` 的 backend、windows-deployment、minio-image-policy 和两个 MinIO supply-chain job 全部成功；新增 Bandit 与 pip-audit 门禁已在远端真实执行。

### 阻塞与风险

- 当前固定窗口不包含阶梯延迟、临时锁定、管理员解锁和验证码，这些仍属于 Sprint 11 账号安全治理。
- MinIO Server/Client 既有 Critical 基线仍未清零；Python 依赖审计通过不代表镜像供应链风险已经消失。
- 尚未完成 34 个 API route 的未认证、普通用户、跨租户、撤权并发和管理员动态矩阵。

### 下一步

1. 建立 34 个 API route 的身份/租户矩阵。
2. 增加恶意图片、文档、Range、预签名 URL 和外链穷举动态安全测试。

### 验证

- `uv run pytest tests/test_auth.py tests/test_rate_limit.py -q`：15 个用例通过。
- 图片、PDF、Office、LibreOffice、Poppler 和 preview Worker 定向测试：14 个用例通过。
- `uv run bandit -r app -ll --skip B101`：中危、高危均为 0。
- `uv run pip-audit --local --progress-spinner off`：审计 145 个环境包，已知漏洞为 0。
- `uv lock --check`、`uv sync --frozen --all-extras --dev`、Ruff、格式检查和 `uv run mypy app`：全部通过；Mypy 检查 149 个源文件，Ruff 确认 210 个文件格式正确。
- 完整 `uv run pytest`：`172 passed, 4 skipped`。
- Compose 已验证登录限流三个环境变量可从宿主覆盖并传入 API。
- runtime 镜像已在 `1 CPU / 2 GiB` BuildKit 上限和 `--pull=false` 下重建为 `sha256:2a6b5558b3031b0c8da6404ac7ca9809afb475ad5940ca3b6fc9c3e702e60928`；preview 镜像已在 `1 CPU / 3 GiB` 上限下重建为 `sha256:16710e0eab90942598a39fa8979275e4eea322ba31fb5064a3bd19484e715c47`，两者均确认使用 `Pillow 12.3.0`。
- 隔离真实 Compose 使用 `--no-build --pull never` 启动 API 必需依赖；错误登录首次返回 `401/AUTH_INVALID_CREDENTIALS`，同账号第二次返回 `429/RATE_LIMITED`，`details.action=auth.login.account`。
- 真实 Compose 采样峰值为 5 个运行容器、`123.1%` aggregate Docker CPU、`1426.3 MiB` 容器内存和 `4826.4 MiB` Docker/WSL 私有工作集；结束后该 project 的容器、网络和卷均为 0。
- `docker compose --env-file .env.windows.example -f compose.windows.yml config --quiet`、`deploy/windows/manage.ps1 config -EnvFile .env.windows.example -Quiet` 和 `git diff --check`：全部通过；当前运行中和全部容器均为 0，本地 10 个镜像对应 10 个唯一 image ID。
- 提交 `25acecf fix: 修复首轮安全测试高危问题` 已推送到 `origin/dev`；GitHub Actions run `30660034411` 的 5 个 job 全部成功，backend job 实际执行新增 Bandit 与 pip-audit 门禁并完成两类镜像构建。

### 涉及文件

- `backend/pyproject.toml`
- `backend/uv.lock`
- `backend/app/api/deps.py`
- `backend/app/api/errors.py`
- `backend/app/core/config.py`
- `backend/app/core/worker_metrics.py`
- `backend/app/modules/auth/router.py`
- `backend/app/modules/auth/service.py`
- `backend/tests/test_auth.py`
- `backend/tests/test_rate_limit.py`
- `.github/workflows/backend-ci.yml`
- `.env.windows.example`
- `compose.windows.yml`
- `AGENT.md`
- `README.md`
- `backend/README.md`
- `docs/deployment-windows-docker.md`
- `docs/security-testing.md`
- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`
- `企业网盘开发者技术计划书.md`

## 2026-07-31 BE-029 性能基准首份真实 Docker smoke

### 当前状态

- `BE-028` 已完成真实 Windows 11 Docker Desktop 闭环：runtime/preview 镜像独立构建、本地镜像 preflight、15 服务 source 启动、备份、默认数据服务恢复、显式完整 target 全栈恢复、gateway/API/Worker/beat/数据服务校验和彻底清理均已通过。
- `BE-029` 第一版 Locust 工具链和真实 Docker smoke 已完成：170 次请求、0 失败，已定义的文件列表、上传初始化、搜索和审计 P95 门槛全部通过，报告为 `passed=true`。
- 当前 Docker client/server 为 `29.6.2`，Compose 为 `v5.3.1`，context 为 `desktop-linux`；运行中容器和全部残留容器均为 `0`。
- `BE-029` 实现已提交为 `f0302e2 feat: 完成首版性能基准与真实 Docker 验证` 并推送到 `origin/dev`；GitHub Actions run `30652675576` 的全部 5 个 job 成功。

### 已完成

- `deploy/windows/backup-restore.ps1` 新增统一 helper container wrapper，全部 `pg_dump`、tar 归档/扫描、卷清理和 PostgreSQL restore 默认使用 `--pull never --cpus 0.50 --memory 512m --memory-swap 512m --pids-limit 128`。
- 新增 `DRIVE_BACKUP_HELPER_CPU_LIMIT`、`DRIVE_BACKUP_HELPER_MEMORY_LIMIT`、`DRIVE_BACKUP_HELPER_PIDS_LIMIT`、`DRIVE_BACKUP_GZIP_LEVEL` 和 `DRIVE_BACKUP_PG_DUMP_COMPRESSION_LEVEL`，并对数值范围做快速校验。
- `pg_dump` 与 gzip 默认压缩等级从高压缩改为 `1`；正式卷归档不再创建后立即重复执行完整 `tar -tzf`，发布前完整工件校验和隔离 tar 安全预扫描仍保留，rollback archive 仍立即校验。
- 备份与 `backup-verify` 增加 PostgreSQL dump、逐卷归档、发布前校验等阶段输出和累计耗时，避免长时间无反馈。
- `deploy/windows/manage.ps1 up` 默认固定 `--no-build --pull never`；TLS 和恢复内部 `compose up/run` 也禁止隐式拉取，只有显式 `up -Build` 才进入构建路径。
- `backup-restore.integration.ps1` 删除 `-BuildImages`，增加 `-PreflightOnly` 和本地镜像快速门禁；preflight 在创建证书、容器或卷之前完成。
- integration 不再对同一成功备份额外重复执行一次完整 `backup-verify`，因为 `backup` 发布前和 `restore` 开始前已经各执行一次完整校验；损坏 manifest 拒绝用例继续保留。
- integration 固定 `COMPOSE_PARALLEL_LIMIT=1`、API/全部 Worker concurrency `1`，降低各服务 CPU/内存上限，并给 MinIO probe helper 设置独立 CPU/内存/swap/PID 边界。
- integration 只调用一次 source `up`，随后轮询容器状态，不再用第二次 `compose up --wait` 重复触发启动流程。默认恢复使用 `-NoStartAfterRestore`，只启动 PostgreSQL、Redis、MinIO、OpenSearch 验证数据恢复；完整 target 全栈验收改为显式 `-FullStackRestore`。
- 首次真实低资源 integration 暴露 OpenSearch 在 `1024m` 硬上限下启动不稳定：Docker 事件显示先转为 `unhealthy`，没有 OOM 事件，清理阶段的退出码 `137` 来自 SIGTERM 超时后的 SIGKILL。单容器复现的启动峰值为 `1018 MiB / 1024 MiB`，余量不足。
- integration 的测试专用 OpenSearch 上限调整为 `1280m`，JVM heap 仍保持 `512m`、CPU 仍限制为 `1.00`；PostgreSQL、Redis、MinIO、OpenSearch 四服务并发探针在 `68.5s` 内全部健康，OpenSearch 峰值为 `1246.2 MiB`。
- 新增 `Write-IntegrationProjectDiagnostics`：真实 integration 失败时在删除项目之前打印 Compose 状态，并对异常 OpenSearch、PostgreSQL、Redis、MinIO、migration、minio-init、seed 和 API 输出状态、health、OOM、退出码与尾部日志。
- runtime 镜像 `enterprise-drive-backend:windows-local` 已使用 `1 CPU / 2 GiB` BuildKit 资源上限独立构建完成；preview 镜像 `enterprise-drive-preview:windows-local` 已使用 `1 CPU / 3 GiB` 上限独立构建完成。当前 10 个本地镜像没有重复 image ID。
- integration `-PreflightOnly` 已确认 8 个唯一 Compose 镜像全部存在，执行前后容器数均为 `0`。
- 默认真实 integration 已通过 source 15 服务启动、备份发布前校验、损坏 manifest 拒绝、source 停止、PostgreSQL/Redis/MinIO/OpenSearch 恢复点验证、运行中 target 拒绝和清理。
- 显式 `-FullStackRestore` 已通过 target gateway、API、5 个 Worker、beat、PostgreSQL、Redis、MinIO、OpenSearch、migration/minio-init/seed 退出状态、唯一 gateway 宿主端口边界和实际镜像对账。
- 已同步 `.env.windows.example`、`AGENT.md`、根/后端 README、Windows 部署文档、执行计划和完整技术计划书。
- 资源修复已提交为 `b1113d1 fix: 限制备份测试资源并禁止隐式构建` 并推送到 `origin/dev`。
- GitHub Actions run `30644453844` 的 backend、MinIO image policy 和两个 supply-chain job 全部成功；失败仅在 `windows-deployment / Validate Windows TLS fake Docker guards`。原因是 CI fake `docker.cmd` 仍只匹配旧 bootstrap 命令，新增 `--pull never` 后没有返回 `fake-bootstrap` 容器 ID。
- `.github/workflows/backend-ci.yml` 已把 fake bootstrap 匹配更新为 `run --detach --no-deps --pull never --service-ports gateway`，并在本机从 workflow 原文提取、执行同一 PowerShell step，全部 TLS fake Docker guard 通过。
- CI fixture 修复已提交为 `252fff6 fix: 同步 Windows TLS CI 假 Docker 命令` 并推送；后续 run `30645014214` 的 backend、windows-deployment、minio-image-policy 和两组 minio-supply-chain job 全部成功。
- `1963f76 fix: 收紧 Windows 备份集成资源并补充诊断` 已提交并推送；run `30648296028` 的 backend、windows-deployment、minio-image-policy 和两组 minio-supply-chain job 全部成功。
- 新增 `backend/performance/`，使用 dev-only Locust `2.46.2`，提供 `smoke`、`baseline` 和显式 `target` 三档，并覆盖登录、`/auth/me`、100 项文件列表批量权限、DTP/1 上传初始化与 abort、搜索和管理员审计。
- runner 使用 `-X utf8` 与 `PYTHONUTF8=1`，捕获 Locust stdout/stderr 后统一写 stdout，避免 PowerShell 把正常 stderr 日志转成 `NativeCommandError`；同时按 Locust 真实规则读取 `stats_stats.csv` 和 `stats_stats_history.csv`。
- fixture 使用一个随机根目录承载全部子目录，清理时先普通 DELETE 整棵子树再一次 purge；上传初始化使用稳定父目录，避免 aborted upload session 外键阻塞 fixture 根目录清理。
- fixture HTTP/清理逻辑与 CLI 参数解析已拆为 `fixture.py` 和 `fixture_cli.py`，原 `python -m performance.fixture` 入口保持不变，普通源码文件均控制在 300 行以内。
- `OpenSearchIndexAdapter.search_files` 仅把 `index_not_found_exception` 转为空搜索结果，其他 `NotFoundError` 继续抛出，空环境的首次搜索不再返回 500。
- 根 `compose.windows.yml` 已传递 `DRIVE_RATE_LIMIT_ENABLED`，`.env.windows.example` 默认保持 `true`，隔离容量基准可显式关闭限流且在报告中记录模式。
- 首次真实 smoke 暴露清理外键冲突和错误的登录临时阈值；修复后使用现有本地镜像、`--no-build --pull never` 和隔离 project 重跑成功。
- 最终 smoke 工件位于 `backend/tmp/performance/20260731-be029-smoke-9c42e8/`，包含 7 个非空文件；数据库 fixture 节点、测试容器、网络、named volumes 和临时端口全部为 0。
- `f0302e2 feat: 完成首版性能基准与真实 Docker 验证` 已推送；run `30652675576` 的 backend、windows-deployment、minio-image-policy 和两组 minio-supply-chain job 全部成功。

### 进行中

- `BE-029` 首版已闭环，正在按工程顺序切换到 `BE-030` 安全测试修复审计。

### 阻塞与风险

- 低压缩等级会增加一定备份体积，但换取更低 CPU 峰值；正式环境应根据备份窗口、磁盘和恢复目标调整，不能取消 helper 容器资源上限。
- `1280m` 是真实 integration 的测试专用 OpenSearch 上限；正式 `.env.windows.example` 仍使用 `3g` 容器内存和 `1g` JVM heap，不能把低资源测试预算直接当作生产容量规划。
- 本轮验证覆盖本机 HTTP Compose 和自签名测试证书，不替代真实生产 DNS、受信证书链、外部网络、BitLocker/外部介质和周期恢复演练。
- MinIO Server/Client 既有 Critical 漏洞基线仍属于上线风险；当前 CI 只阻断相对基线新增的 Critical。
- 当前 smoke 只有 100 个目录和 2 个用户，不代表 100 万 OpenSearch 文档、1,000 万审计日志、真实 multipart complete 或完整 target 容量验收。
- 受限单 API CPU 环境下两次登录的 P95 为 `2500 ms`；技术计划书没有登录验收阈值，因此当前只记录错误率和延迟，不把临时编造的 `500 ms` 当作门禁。登录 SLO 需结合 Argon2id 参数和生产 CPU 预算单独确定。

### 下一步

1. 按工程编号进入 `BE-030` 安全测试修复审计，先从当前默认配置和攻击者可达路径建立缺口矩阵。
2. 为后续 target 验收补充 100 万 OpenSearch 文档、1,000 万审计日志和真实 multipart complete 数据生成设计。
3. 根据首份基准继续由 `DC-006` 设计 DTP/1 服务端并发提示，并验证 HTTP/2/HTTP/3 透明承载与回退边界。

### 验证

- PowerShell 5.1 parser：`backup-restore.ps1`、`manage.ps1`、smoke、integration 全部通过。
- PowerShell 文件 ASCII 检查：4 个脚本的 non-ASCII byte 均为 `0`。
- `deploy/windows/tests/backup-restore.smoke.ps1`：`27` 个用例全部通过。
- `docker compose --env-file .env.windows.example -f compose.windows.yml config --quiet`：通过。
- integration `-PreflightOnly`：8 个唯一镜像全部存在，结果为成功；执行前后运行中/全部容器数均为 `0`。
- 受限真实 Docker helper：容器内 cgroup 为 `cpu.max=50000 100000`、`memory.max=536870912`、`pids.max=128`，与默认 `0.50 CPU / 512m / 128 PIDs` 一致。
- 真实 64 KiB 临时卷使用新归档路径生成 `449` 字节 gzip 文件并通过隔离 tar 安全校验，归档加校验耗时约 `3.78s`；临时卷、目录和容器已清理。
- runtime 镜像使用 BuildKit `--resource memory=2g --resource cpu-quota=100000` 独立构建成功，用时约 `50.7s`；镜像 ID 为 `sha256:782beca9aa4708b8912a1b4487b4a9c1350220549a1898a824287f6fc8b75677`，大小 `108031695` 字节。
- preview 镜像使用 BuildKit `--resource memory=3g --resource cpu-quota=100000` 独立构建成功，用时约 `127.9s`；镜像 ID 为 `sha256:707a67e424fb38aa96e7bef806b1d0277c5cb81a272200e706728496c3c218b3`，大小 `361680759` 字节。
- 默认真实 integration：`409.6s` 通过，监测采样峰值约为 `311.6%` aggregate Docker CPU 和 `2254 MiB` 容器内存；测试结束后 source/target 容器均为 `0`。
- `-FullStackRestore`：`357.3s` 通过，12 个同时运行容器，采样峰值为 `123.5%` aggregate Docker CPU、`2226 MiB` 容器内存和 `4528 MiB` Docker 相关宿主进程 working set；测试结束后 source/target 容器均为 `0`。
- 已从 `.github/workflows/backend-ci.yml` 原文提取并本地执行 `Validate Windows TLS fake Docker guards` step，结果通过。
- GitHub Actions run `30645014214`：5 个 job 全部成功。
- GitHub Actions run `30648296028`：5 个 job 全部成功；既有 MinIO Critical 基线仅作为 supply-chain annotation，不是本次失败。
- 当前 `docker ps` 和 `docker ps -a`：容器数均为 `0`。
- `uv lock --check`、`uv run ruff check .`、`uv run ruff format --check .` 和 `uv run mypy app performance tests/test_performance_benchmark.py tests/test_search_opensearch.py`：全部通过。
- 完整 `uv run pytest`：`168 passed, 4 skipped`。
- 定向性能/OpenSearch 测试：`8 passed`；性能测试单独为 `6 passed`，包含部分 fixture 创建失败后的自动根目录清理。
- `uv run python -X utf8 -m locust --help`：通过；直接使用 Windows 默认 GBK 的 `uv run locust --help` 曾复现 TOML 解码错误，runner 已固定 `-X utf8` 和 `PYTHONUTF8=1`。
- `BE-029` 审计：仓库原先没有 benchmark/load-test 文件、Locust/k6/pytest-benchmark 依赖或 CI 性能门禁；复用资产为 `httpx`、Prometheus/OTel 指标、真实 Docker smoke 和技术计划书目标。
- runtime 镜像使用 BuildKit `1 CPU / 2 GiB` 上限、`--pull=false` 单独重建，耗时 `37.8s`，镜像 ID 为 `sha256:4401248ea4b60644a0aa74fe31ba00c5c641720b74c7dda958d45fb57ddd66ee`。
- 最终真实 Docker smoke：170 次请求、0 失败；文件列表/上传初始化/搜索/审计 P95 为 `32/92/71/25 ms`，报告 `passed=true`。
- smoke 资源采样峰值：6 个容器、`162%` aggregate Docker CPU、`1506.1 MiB` 容器内存、`4471.9 MiB` Docker 相关宿主进程 working set。
- `backend/tmp/performance/20260731-be029-smoke-9c42e8/report.json`、HTML 和 4 个 Locust CSV 均为非空；fixture 节点为 `0`，最终 `docker ps`、`docker ps -a` 和两个隔离 project 的容器/网络/卷均为 `0`。
- GitHub Actions run `30652675576`：5 个 job 全部成功；backend job 完成依赖安装、PostgreSQL/MinIO、Ruff、Mypy、pytest、Compose/TLS/Nginx 校验、runtime/preview 构建和 observability Docker smoke。

### 涉及文件

- `deploy/windows/backup-restore.ps1`
- `deploy/windows/manage.ps1`
- `deploy/windows/tests/backup-restore.smoke.ps1`
- `deploy/windows/tests/backup-restore.integration.ps1`
- `.env.windows.example`
- `AGENT.md`
- `README.md`
- `backend/README.md`
- `docs/deployment-windows-docker.md`
- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`
- `企业网盘开发者技术计划书.md`
- `.github/workflows/backend-ci.yml`
- `backend/pyproject.toml`
- `backend/uv.lock`
- `backend/performance/`
- `backend/app/infrastructure/search/opensearch.py`
- `backend/tests/test_performance_benchmark.py`
- `backend/tests/test_search_opensearch.py`
- `compose.windows.yml`
- `docs/performance-benchmark.md`

## 2026-07-31 BE-027 暂停与恢复收尾

### 当前状态

- 此前已按用户要求暂停并保留工作树原状；收到“继续”后恢复 `BE-027` 收尾，暂停期间未执行提交、推送、暂存、重置或清理。
- 当前分支为 `dev`；`BE-027` 实现提交为 `81709039d20454e97933b5bb061d852807676a8e`（`feat: 完成可观测性指标与 tracing`），已推送到 `origin/dev`。
- 实现提交推送后 `dev` 与 `origin/dev` 的 ahead/behind 均为 0，工作树恢复干净。
- 恢复时工作树包含 27 个已修改文件和 5 个新增文件，均未暂存。
- 最终审阅补齐 API/Worker registry 隔离后，提交范围为 31 个已修改文件和 6 个新增文件。

### 已完成

- `BE-027` 的 HTTP/业务/Worker Prometheus 指标、Uvicorn multiprocess 聚合、JSON 日志关联、FastAPI/Celery OpenTelemetry、运行入口和真实 Docker observability smoke 已实现。
- 最终 diff 审阅发现 Worker Counter 与 API Counter 虽由不同容器写入，但仍在同一 Python 模块初始化；已拆分 `app.core.metrics` 和 `app.core.worker_metrics`，避免无标签 metric 在 multiprocess mmap 初始化时跨进程角色泄漏，并把 API/Worker 双向隔离加入真实 Docker smoke。
- 正式 runtime image `enterprise-drive-backend:windows-local` 已构建成功。
- 最近一次真实 Docker prefork smoke 已验证 2-worker API、PostgreSQL、Redis 和 maintenance Worker；24 次 API ping 全部进入聚合指标，检测到 3 个 API multiprocess gauge 进程文件，API/Worker registry 双向隔离通过，真实 Celery task 状态为 `success`，API 与 Worker 均产生有效 trace ID，临时容器和网络已经清理。
- README、`AGENT.md`、执行计划、Windows/Preview 部署文档、CI 和技术计划书已随实现同步。
- GitHub Actions `backend-ci` run `30634347985` 全部成功；backend job 已实际执行 runtime image 构建、observability Docker smoke 和 Preview Worker image 构建，Windows 部署、MinIO image policy 与供应链 jobs 也全部成功。

### 最近验证

- 恢复后重新执行完整后端测试：`160 passed, 4 skipped`。
- `uv lock --check`：通过，解析 102 个包。
- `uv run ruff check .`：通过。
- `uv run ruff format --check .`：202 个文件格式通过。
- `uv run mypy app`：通过，149 个源文件无类型问题。
- `docker compose --env-file .env.windows.example -f compose.windows.yml config --quiet`：通过。
- 恢复后执行 `git diff --check`：通过；仅显示 `backend/uv.lock` 的 Git 行尾转换提示，没有空白错误。
- 最新 Docker smoke：`api_ping_count=24`、`api_metric_process_files=3`、`metric_registry_isolation=passed`、`worker_task_status=success`；API trace ID 为 `7ce22eb62ff2741c276dac1fee1763c9`，Worker trace ID 为 `13079cbfa0098f50df1367a46050c75b`。
- GitHub Actions：`backend-ci` run `30634347985` 成功，backend job 用时 3 分 24 秒。

### 未完成与风险

- `BE-028` 的 15 服务真实 Compose 构建、启动、readiness、gateway、Worker/beat、备份与恢复门禁尚未开始。

### 下一步

1. 按 `BE-028` 使用根 `compose.windows.yml` 启动全部 15 个默认服务。
2. 验证 gateway、API `/readyz`、MinIO 外部端点、5 个 Worker、beat、内部指标端点和唯一宿主端口边界。
3. 执行真实备份、`backup-verify`、隔离恢复和失败回滚门禁，并记录精确 Compose project、镜像和备份工件证据。

## 2026-07-31 BE-027 metrics/tracing

### 已完成

- 对照技术计划书 21.1 至 21.3 和正式 Compose 进程模型完成真实缺口审计：原实现只有 4 组预览/清理指标，没有 HTTP 指标、OpenTelemetry 初始化、trace 日志关联、上传/下载/权限指标、Worker task 指标、Outbox pending 和搜索索引延迟。
- 新增 `http_requests_total` 与 `http_request_duration_seconds`；标签使用 HTTP method、完整 FastAPI 路由模板和状态码，未知路由统一为 `unmatched`，不记录原始 URL、路径参数或 `/metrics` 自身。
- 新增 `upload_sessions_total`、`upload_failures_total`、`download_requests_total` 和 `permission_decision_duration_seconds`，覆盖上传初始化/complete/abort/分片签名、内部/外链下载以及空间、节点和批量权限判断。
- 新增 `outbox_pending_total{status}` 和 `search_index_lag_seconds`；API 抓取时以短超时查询 PostgreSQL，数据库重启或超时时仍返回已有进程指标。
- 正式 API 的 2 个 Uvicorn worker 使用 Prometheus multiprocess 目录聚合；新增 runtime entrypoint，只在容器启动前删除该目录中的旧 `.db` metric 文件，避免任一在线 worker 清空其他进程数据。
- 新增 `worker_tasks_total` 与 `worker_task_duration_seconds`；5 个 Celery Worker 各自在 Compose 内部 `9100` 暴露指标，并记录 task、queue、status 和 duration。API 与 Worker 的独立容器指标不再通过同进程测试伪装成统一 registry。
- API 指标定义与 Worker/预览/维护指标定义已拆分为独立模块和本地 registry；真实 multiprocess smoke 会双向拒绝跨角色 metric 名称，避免无标签 metric 初始化产生错误抓取面。
- JSON 日志自动补齐 `service`、`env`、`request_id`、`task_id`、`trace_id`、`span_id`、tenant/user/resource 上下文；HTTP 请求结束日志记录 route、method、status 和 `latency_ms`，Celery task 结束日志记录 task ID、queue、status 和耗时。
- FastAPI 与 Celery 已接入 OpenTelemetry SDK；采样率可配置，exporter 支持 `none`、Console 和 OTLP/HTTP。默认 `none` 不向外部发送 span，但保留 W3C trace/span 关联；OTLP endpoint、headers 和超时均来自环境变量。
- 新增隔离的真实 Docker smoke 脚本：自动启动 PostgreSQL 16、Redis、空库 migration、2-worker API 和 maintenance Worker，验证后自动删除容器与网络。
- `backend-ci` 在 runtime image 构建后执行同一 observability smoke，使 API 多进程和真实 Celery task 指标成为持续门禁。
- 已同步 `AGENT.md`、根/后端 README、Windows Docker 部署说明、Preview Worker 部署说明、项目计划和技术计划书。

### 版本影响

- 新增向后兼容的指标、日志字段、环境变量和内部 Worker metrics 端口，无数据库 migration、对象存储 key、DTP/1 或现有 HTTP API 破坏性变更。
- 新增 `opentelemetry-exporter-otlp-proto-http` 与 `opentelemetry-instrumentation-celery`，`uv.lock` 解析包数量从 97 增至 102；项目版本保持 `0.4.0`。
- `backend/Dockerfile` runtime entrypoint 由直接启动命令调整为先准备 Prometheus multiprocess 目录再 `exec` 原命令；migration、seed、API、Worker 和 beat 仍复用同一镜像和原命令语义。

### 进行中

- 按工程编号进入 `BE-028`，使用根 `compose.windows.yml` 对全部 15 个默认服务执行构建、启动、readiness、gateway、Worker/beat、备份与回滚门禁。

### 阻塞与风险

- 当前仓库没有内置 Prometheus Server、Alertmanager 或治理看板；API 和各 Worker 已提供抓取面，告警规则、连续失败阈值、目标发现和看板属于 `BE-035`。
- Worker 指标只在 Compose 内部 `9100` 暴露，不发布宿主端口；监控系统必须分别抓取 `worker-audit`、`worker-permission`、`worker-search`、`worker-maintenance` 和 `worker-preview`，不能只抓 API `/metrics`。
- 默认 tracing exporter 为 `none`；生产需要先部署受控 OTLP collector，再配置 endpoint、认证 header、采样率、保留期和敏感属性策略。
- Outbox/Search gauge 是抓取时的最佳努力数据库快照；数据库不可用时不会阻塞全部 `/metrics`，但 gauge 可能短暂保留上次成功值。

### 下一步

1. 执行 `BE-028` 全 15 服务真实 Compose 构建、启动、gateway、readiness、Worker/beat 和备份恢复验证。
2. 在 `BE-035` 增加 Prometheus scrape 配置、告警规则、失败阈值和治理看板；在 `BE-029` 输出正式性能基准。

### 验证

- `uv run pytest`：160 passed，4 skipped。
- `uv run ruff check .`：通过。
- `uv run ruff format --check .`：202 个文件格式通过。
- `uv run mypy app`：通过，149 个源文件无类型问题。
- `uv lock --check`：通过，解析 102 个包。
- `docker compose --env-file .env.windows.example -f compose.windows.yml config --quiet`：通过；5 个 Worker 均解析出内部 `DRIVE_WORKER_METRICS_PORT=9100`，API/Worker 均解析出 tracing 与 multiprocess 配置。
- 真实 Docker 正式 runtime image：`enterprise-drive-backend:windows-local` 构建成功，包含 OTLP/HTTP 与 Celery instrumentation 依赖。
- `uv run python scripts/smoke_observability_docker.py --image enterprise-drive-backend:windows-local`：通过；真实 PostgreSQL、Redis、Alembic、2-worker API 和 maintenance Worker 均正常。
- Docker smoke 结果：24 次 `/api/v1/ping` 聚合为 24，API 指标目录在注入测试样本前检测到 3 个 `gauge_livemostrecent` multiprocess 文件；API 抓取面不含 Worker/预览/维护指标，Worker 抓取面不含 API/上传下载/权限/Outbox/Search 指标。使用生产同款 Celery prefork、`worker_ready` 后启动 9100 指标端点，真实 `upload.expire_sessions` task 为 success；API 与 Worker JSON 日志均包含有效 trace ID/span ID，临时容器和网络已清理。
- GitHub Actions `backend-ci` run `30634347985`：全部成功；包含完整后端测试、Windows Compose/TLS/备份模型、Nginx 模板、runtime/Preview 镜像、真实 observability Docker smoke、Windows 部署脚本和 MinIO 供应链门禁。

### 涉及文件

- `backend/app/api/middleware.py`
- `backend/app/core/config.py`
- `backend/app/core/logging.py`
- `backend/app/core/metrics.py`
- `backend/app/core/tracing.py`
- `backend/app/core/worker_metrics.py`
- `backend/app/core/worker_observability.py`
- `backend/app/infrastructure/queue/celery_app.py`
- `backend/app/modules/file/blob_cleanup.py`
- `backend/app/modules/upload/router.py`
- `backend/app/modules/file/router.py`
- `backend/app/modules/file/trash_cleanup.py`
- `backend/app/modules/share/router.py`
- `backend/app/modules/permission/service.py`
- `backend/app/workers/preview_tasks.py`
- `backend/scripts/runtime_entrypoint.py`
- `backend/scripts/smoke_observability_docker.py`
- `backend/tests/test_app.py`
- `backend/tests/test_observability.py`
- `backend/tests/test_preview_worker.py`
- `backend/Dockerfile`
- `backend/pyproject.toml`
- `backend/uv.lock`
- `.github/workflows/backend-ci.yml`
- `.env.windows.example`
- `backend/.env.example`
- `compose.windows.yml`
- `AGENT.md`
- `README.md`
- `backend/README.md`
- `docs/deployment-windows-docker.md`
- `docs/deployment-preview-worker.md`
- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`
- `企业网盘开发者技术计划书.md`

## 2026-07-31 Drive Transfer Protocol v1

### 已完成

- 正式采用 `Drive Transfer Protocol v1`，线协议标识固定为 `DTP/1`。
- 新增 `docs/drive-transfer-protocol-v1.md`，定义控制面、预签名 HTTPS 数据面、版本协商、上传状态机、断点恢复、complete 幂等、服务端 SHA-256、Range 下载、错误码、安全边界和验收。
- 新增 `backend/app/core/transfer_protocol.py`，集中维护协议头、版本常量和传输响应基类。
- 上传全部接口支持可选请求头 `X-Drive-Transfer-Protocol: DTP/1`；文件下载和外链下载也使用同一协商依赖。为兼容已有客户端，省略请求头时按 `DTP/1` 处理。
- 客户端声明未知版本时返回 HTTP 426、`TRANSFER_PROTOCOL_UNSUPPORTED` 和当前支持版本列表。
- 秒传、multipart 初始化、上传状态、分片签名、complete、abort、文件下载和外链下载响应统一返回 `protocol_version=DTP/1`。
- 已同步 `AGENT.md`、README、执行计划和完整技术计划；明确不自研 TCP/UDP、TLS、QUIC、私有加密或可靠传输层。

### 版本影响

- OpenAPI 增加可选 `X-Drive-Transfer-Protocol` header parameter，并为 8 个传输响应 schema 增加只读语义的 `protocol_version` 字段。
- 省略请求头的现有客户端继续可用；该改动为向后兼容的字段扩展，项目版本保持 `0.4.0`。

### 进行中

- 回到任务编号顺序，进入 `BE-027` metrics/tracing 接入缺口审计。

### 阻塞与风险

- 当前 DTP/1 核心兼容档仍使用单分片签名接口；批量签名、服务端建议并发数和 Rust 持久化传输队列属于 `DC-006`。
- 当前上传分片大小由服务端全局配置决定；在真实 MinIO、磁盘和网络基准完成前，不把固定高并发或更大分片写死到协议。
- HTTP/2、HTTP/3 只作为透明承载升级；当前未完成网关编译能力、UDP 网络和自动回退实测。

### 下一步

1. 审计并实现 `BE-027` 请求、数据库、队列、任务指标和 tracing 缺口。
2. 在 `DC-006` 实现 DTP/1 批量分片签名、并发提示和 Rust 传输队列。
3. 在 `BE-029` 性能基准后决定默认分片和并发策略，并验证 HTTP/2/HTTP/3 回退。

### 验证

- `uv run pytest`：153 passed，4 skipped。
- `uv run ruff check .`：通过。
- `uv run ruff format --check .`：196 个文件格式通过。
- `uv run mypy app`：通过，146 个源文件无类型问题。
- `uv lock --check`：通过，解析 97 个包。
- OpenAPI：版本 `0.4.0`、30 条 path；上传、文件下载和外链下载均公开 `X-Drive-Transfer-Protocol` header。
- OpenAPI：`AbortUploadResponse`、`CompleteUploadResponse`、`InstantUploadResponse`、`MultipartUploadResponse`、`UploadPartUrlResponse`、`UploadSessionStatusResponse`、`FileDownloadUrlResponse` 和 `ExternalShareDownloadResponse` 均包含 `protocol_version`。
- 测试覆盖 `DTP/1` 正常响应和 `DTP/2` 返回 HTTP 426。

### 涉及文件

- `AGENT.md`
- `docs/drive-transfer-protocol-v1.md`
- `backend/app/core/transfer_protocol.py`
- `backend/app/api/deps.py`
- `backend/app/modules/upload/router.py`
- `backend/app/modules/upload/schemas.py`
- `backend/app/modules/file/router.py`
- `backend/app/modules/file/schemas.py`
- `backend/app/modules/share/router.py`
- `backend/app/modules/share/schemas.py`
- `backend/tests/test_upload.py`
- `backend/tests/test_download.py`
- `backend/tests/test_share_router.py`
- `README.md`
- `backend/README.md`
- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`
- `企业网盘开发者技术计划书.md`

## 2026-07-31 BE-026 回收站保留期自动清理

### 已完成

- 对照 `AGENT.md`、`PROJECT_PLAN.md`、工程任务表和现有代码核对 `BE-026` 验收：`upload.expire_sessions` 已覆盖过期上传，`file.cleanup_unreferenced_blobs` 已覆盖无引用 blob，原任务真正缺少的是回收站保留期自动清理。
- 新增 `file.cleanup_expired_trash` 服务与 Celery 任务，默认 `DRIVE_TRASH_RETENTION_DAYS=30`、`DRIVE_TRASH_CLEANUP_INTERVAL_SECONDS=3600`，并接入 `maintenance` route 和 Celery beat。
- 清理查询按租户扫描超过保留期的删除批次根节点；父节点与子节点 `deleted_at/deleted_by` 相同时只领取父节点，避免同批子树重复处理。
- 清理前使用 PostgreSQL `FOR UPDATE SKIP LOCKED` 领取根节点，并锁定全部子树节点；普通目录在单事务内删除版本和节点、扣减 blob 引用、释放空间容量并写入 `file_purged` 负向账本。
- 为已彻底删除的文件写入 `reason=trash_retention_expired` 的 `search.index_requested`，并记录 `file.trash.retention_purged` 系统审计；冲突或容量/blob 异常会回滚该根节点并记录失败审计。
- 新增迁移 `20260731_0013` 和 `idx_nodes_trash_cleanup(tenant_id, is_deleted, deleted_at, id)`。
- 新增 `trash_cleanup_total{status}` 和 `trash_cleanup_released_bytes_total` Prometheus 指标。
- 新增 SQLite 回归测试和真实 PostgreSQL Docker 集成测试，覆盖到期目录子树、未到期节点、删除批次去重、租户隔离、行锁查询、容量、blob 引用、审计、搜索 outbox 和迁移索引。
- `backend-ci` 已增加临时 PostgreSQL 16 容器、`pg_isready`、Alembic upgrade 和真实数据库测试；原真实 MinIO 测试继续保留。
- 已把 `Drive Transfer Protocol v1` 纳入 Sprint 7 前置计划：自定义 HTTPS 之上的分片、断点、校验、幂等和并发契约，数据仍通过预签名 HTTPS 直达 MinIO/S3，不自研 TCP/UDP、TLS 或可靠传输层。

### 版本影响

- 新增向后兼容的维护任务、环境变量和 Prometheus 指标；数据库只增加查询索引，无列、约束、对象 key 或 HTTP API 破坏性变更。
- Alembic head 从 `20260701_0012` 更新为 `20260731_0013`；项目版本保持 `0.4.0`。

### 进行中

- 按编号进入 `BE-027` metrics/tracing 接入缺口审计，先区分现有 `/metrics`、预览/孤儿对象/回收站指标与尚未实现的请求、数据库、队列和 trace 能力。

### 阻塞与风险

- 当前每个删除批次根节点仍在一个数据库事务内遍历和删除整棵子树；超大目录需要 `BE-046` 的游标分片、任务状态和长事务边界。
- 任务已暴露失败计数并写失败审计，但连续失败告警、积压阈值和治理看板属于 `BE-035`。
- 当前保留期是全局配置，没有按空间/密级策略、dry-run 和运行记录；这些能力属于 `BE-047`，不提前混入 `BE-026`。
- 本轮真实 PostgreSQL 容器门禁已通过；完整 15 服务 Compose 的拉取、构建、启动、健康和备份恢复仍属于 `BE-028`。

### 下一步

1. 审计 `BE-027` 现有 `/metrics` 覆盖范围，列出请求、数据库、队列、任务和 trace 的真实缺口。
2. 实现 `BE-027` 缺少的基础指标与 tracing 能力，并补 Prometheus/OpenTelemetry 测试。
3. 按 `BE-028` 使用真实 Docker Desktop 完整启动 15 服务并执行 readiness、Worker/beat、gateway、备份恢复门禁。

### 验证

- `uv run pytest`：152 passed，4 skipped。
- `uv run ruff check .`：通过。
- `uv run ruff format --check .`：195 个文件格式通过。
- `uv run mypy app`：通过，145 个源文件无类型问题。
- `uv lock --check`：通过，解析 97 个包。
- `uv run alembic heads`：`20260731_0013 (head)`。
- 真实 Docker PostgreSQL：`postgres:16-bookworm` 容器运行并通过 `pg_isready`。
- 真实 PostgreSQL migration：从空库升级到 `20260731_0013`，`alembic current` 为 head。
- `DRIVE_RUN_POSTGRES_TESTS=1 uv run pytest tests/test_trash_cleanup_postgres_integration.py -q`：1 passed。
- `docker compose --env-file .env.windows.example -f compose.windows.yml config --quiet`：通过，15 个默认服务。
- 临时 PostgreSQL 测试容器已删除。
- GitHub Actions `backend-ci` run `30612418629`：提交 `ba51270` 全部通过。

### 涉及文件

- `backend/app/core/config.py`
- `backend/app/core/metrics.py`
- `backend/app/modules/file/models.py`
- `backend/app/modules/file/repository.py`
- `backend/app/modules/file/trash_cleanup.py`
- `backend/app/workers/file_tasks.py`
- `backend/app/infrastructure/queue/celery_app.py`
- `backend/app/infrastructure/queue/schedule.py`
- `backend/migrations/versions/20260731_0013_trash_cleanup_index.py`
- `backend/tests/test_trash_cleanup.py`
- `backend/tests/test_trash_cleanup_postgres_integration.py`
- `.github/workflows/backend-ci.yml`
- `.env.windows.example`
- `compose.windows.yml`
- `README.md`
- `backend/README.md`
- `docs/deployment-windows-docker.md`
- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`
- `企业网盘开发者技术计划书.md`

## 2026-07-31 BE-025 管理员审计查询 API

### 已完成

- 对照 `AGENT.md`、执行计划、完整技术计划和现有代码审计早期未完成项，确认 Sprint 4 的高危动作当前直接查询 PostgreSQL 权限事实，Sprint 5 搜索已有 OpenSearch 过滤与 PostgreSQL 二次权限校验；最早真正缺少的工程任务为 `BE-025`。
- 新增 `backend/app/modules/admin/` 管理模块和 `GET /api/v1/admin/audit-logs`。
- 查询仅允许当前租户的 `is_super_admin` 用户访问，普通用户返回 `ADMIN_REQUIRED`；服务层再次执行管理员检查，不依赖页面或路由隐藏。
- 支持按 `actor_id`、`actor_type`、`action`、`resource_type`、`resource_id`、`result`、`risk_level`、`request_id`、`created_from` 和 `created_to` 组合筛选。
- 使用 `created_at DESC, id DESC` 和签名 cursor 分页；查询始终包含 `tenant_id` 条件，测试覆盖其他租户审计记录不可见。
- 管理员成功查询、普通用户越权查询和非法时间范围都会写入 `admin.audit_logs.queried` 审计与对应 outbox event，记录筛选条件、返回数量和拒绝原因。
- 已同步 `README.md`、`backend/README.md`、`PROJECT_PLAN.md` 和《企业网盘开发者技术计划书.md》。

### 版本影响

- 新增向后兼容的管理查询 API，无数据库 migration、对象存储 key 或现有 API 破坏性变更；作为 Sprint 6 / `v0.4.0` 原计划任务完成，当前版本保持 `0.4.0`。

### 进行中

- 按任务顺序继续审计 `BE-026` 生命周期清理：现有过期上传、无引用 blob、孤儿对象和容量校准已落地，仍需核对回收站、过期分享和预览产物的持续治理缺口。

### 阻塞与风险

- 当前查询直接读取单表并利用租户、actor/time、resource/time 索引；千万级日志的月分区、保留归档和外部投递属于 `BE-049`，本任务不提前混入后续分区迁移。
- 审计 metadata、IP 和 User-Agent 仅向系统管理员返回；后续导出仍需独立权限、异步任务、签名和数据脱敏策略。
- Docker Hub 经 Docker Desktop 内部代理访问仍有 EOF，完整容器门禁继续按下方 Docker 状态记录处理。

### 下一步

1. 提交并推送 `BE-025` 的代码、测试和文档。
2. 完成 `BE-026` 生命周期清理缺口审计并优先交付过期分享和预览产物清理。
3. 修复 Docker Hub 拉取路径后补跑完整 Compose、健康检查、备份恢复和真实依赖门禁。

### 验证

- `uv run pytest tests/test_admin_audit.py -q`：3 个测试通过。
- `uv run ruff format --check app tests/test_admin_audit.py`：通过。
- `uv run ruff check app tests/test_admin_audit.py`：通过。
- `uv run mypy app`：通过，144 个源文件无类型问题。
- `uv run ruff format --check .`：191 个文件格式通过。
- `uv run ruff check .`：通过。
- `uv lock --check`：通过，解析 97 个包。
- `uv run pytest`：151 passed，3 skipped。
- `uv run alembic heads`：`20260701_0012 (head)`。
- OpenAPI：版本 `0.4.0`、30 条 path，包含 `/api/v1/admin/audit-logs`。

### 涉及文件

- `backend/app/api/v1/router.py`
- `backend/app/modules/admin/__init__.py`
- `backend/app/modules/admin/audit.py`
- `backend/app/modules/admin/router.py`
- `backend/app/modules/admin/schemas.py`
- `backend/app/modules/audit/repository.py`
- `backend/tests/test_admin_audit.py`
- `README.md`
- `backend/README.md`
- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`
- `企业网盘开发者技术计划书.md`

## 2026-07-31 Docker Desktop 重新安装与基础验证

### 已完成

- 用户已重新安装 Docker Desktop；确认 CLI 位于 `C:/Program Files/Docker/Docker/resources/bin/`。
- 已确认当前 context 为 `desktop-linux`，Docker client/server 均为 `29.6.2`，daemon 为 Linux `amd64`，Docker Compose 为 `v5.3.1`。
- 已使用 `.env.windows.example` 执行根目录 `compose.windows.yml` 静态配置校验，配置有效并解析出 15 个默认服务。
- 已从 `registry.k8s.io` 拉取 `pause:3.10`，创建 Linux 容器并确认状态为 `true running`，随后删除测试容器和镜像，未保留验证资源。
- 已确认宿主机直接访问 Docker Hub token 接口返回 HTTP 200。

### 版本影响

- 本轮只恢复本机容器运行时并同步验证记录，项目代码版本保持 `0.4.0`，未修改 Compose、镜像、数据库或业务代码。

### 进行中

- 完整项目镜像拉取、Compose 启动、健康检查、备份恢复和全依赖集成门禁尚未执行。

### 阻塞与风险

- 当前 Codex Git Bash 进程继承了 Docker Desktop 安装前的 PATH，直接运行 `docker` 会提示命令不存在；显式加入 Docker `resources/bin` 后 CLI、daemon 和 Compose 均可使用，重启 Codex 终端或应用后应重新确认 PATH。
- Docker Hub 的 `hello-world` 拉取在 daemon 使用的 `http.docker.internal:3128` 内部代理路径连续出现 `auth.docker.io` EOF；`registry.k8s.io` 拉取和容器运行正常，说明 daemon 与 Linux containers 已恢复，但项目依赖的 Docker Hub 镜像拉取路径仍需处理。

### 下一步

1. 重启或刷新 Codex Git Bash 环境，确认 Docker 安装目录已进入 PATH。
2. 检查 Docker Desktop 代理、DNS 和 Docker Hub 访问，直到 `docker pull nginx:1.27-alpine` 等项目依赖镜像成功。
3. 执行完整 Compose 镜像拉取、构建、启动、`/readyz`、Worker/beat、gateway 端口和停止验证。
4. 补跑真实备份恢复、全依赖集成和 Sprint 6 发布门禁，再正式发布 `v0.4.0`。

### 验证

- `docker context show`：`desktop-linux`。
- `docker version`：client/server `29.6.2`，server OS `linux`，architecture `amd64`。
- `docker info`：Operating System `Docker Desktop`。
- `docker compose version`：`v5.3.1`。
- `docker compose --env-file .env.windows.example -f compose.windows.yml config --quiet`：通过。
- `docker compose ... config --services`：15 个默认服务。
- `registry.k8s.io/pause:3.10`：拉取、运行、检查和清理通过。
- Docker Hub `hello-world`：daemon 内部代理请求 `auth.docker.io` 返回 EOF，尚待修复。

### 涉及文件

- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`

## 2026-07-31 概念缺口补全为正式计划

### 已完成

- 根据“优先补入计划”清单复核 Web 用户端与管理后台、文件版本、批量文件操作、内部分享接收端、登录安全、OIDC/LDAP/SSO 和密码管理，确认这些能力此前仅存在于交互契约、接口示例、模块描述或“后续接入”文字中。
- 新增 Sprint 9 至 Sprint 13：
  - Sprint 9 / `0.6.0`：核心产品能力闭环。
  - Sprint 10 / `0.7.0`：Web 用户端与管理后台。
  - Sprint 11 / `0.8.0`：身份与账号安全。
  - Sprint 12 / `0.9.0`：规模化治理与内容能力。
  - Sprint 13 / `1.0.0`：稳定版发布。
- 新增 37 个可执行工程任务：`BE-036` 至 `BE-050`、`FE-001` 至 `FE-012`、`OPS-001` 至 `OPS-003`、`QA-001` 至 `QA-002`、`REL-001` 至 `REL-005`，每项均包含依赖、估时和验收。
- 补齐文件版本列表/下载/回滚、回收站列表、批量删除/移动/恢复/彻底删除、分享给我的、接收人访问和站内通知的后端接口计划。
- 补齐登录失败限流、阶梯延迟、账号锁定/解锁、用户改密、管理员重置、首次登录强制改密、全会话吊销、OIDC/OAuth 2.1 + PKCE 和 LDAP 同步计划。
- 补齐 `frontend/` TypeScript + React + Vite 路线，明确 OpenAPI 生成 client、BFF Cookie、CSRF、用户端页面、管理后台页面、Compose 内部 Web 服务和 Playwright E2E。
- 补齐 Web 批量操作、内部分享通知、账号安全、OIDC/LDAP 身份源管理和生命周期/Outbox 治理页面任务，避免后端能力进入 Sprint 后仍没有对应操作入口。
- 将大目录后台操作、完整生命周期、OCR、审计分区与外部投递、Outbox dead-letter、备份来源签名/完整包加密、离线副本和跨版本数据迁移纳入 Sprint 12。
- 将虚拟盘、macOS/Linux 文件提供器、WebDAV、SMB、Kubernetes/systemd、移动端、在线协同、复杂 DLP、跨地域双活和计费升级为带编号、入口条件和验收标准的远期 Backlog。
- 已同步 `AGENT.md`、`PROJECT_PLAN.md`、`README.md` 和《企业网盘开发者技术计划书.md》。

### 版本影响

- 本轮只补全规划和开发约束，当前代码版本保持 `0.4.0`，不新增数据库 migration、业务 API、前端或客户端代码。
- `0.5.0` 至 `1.0.0` 为目标路线，不代表对应能力已经实现；实际版本只在代码、测试、文档和发布门禁完成后提升。

### 进行中

- 当前仍处于 Sprint 6 收尾；Sprint 7 之后的桌面、Web、产品闭环、身份和治理任务均为待执行计划。

### 阻塞与风险

- 新路线依赖较多，必须按任务依赖推进，不能让 Web 页面或桌面端先行固化尚未稳定的版本、批量、身份或分享契约。
- OIDC 和 LDAP 需要真实身份提供商测试环境；正式接入前必须完成 issuer/subject、目录外部 ID、账号冲突和离职禁用策略评审。
- Web 技术栈只固定主干工具，具体依赖版本和插件必须在 `frontend/` 初始化时重新执行许可证、安全和维护状态检查并锁入项目。
- `v1.0.0` 仍受 MinIO Critical 基线、真实公网证书、生产告警、周期恢复和完整 UAT 等现有风险约束。
- 规划补全阶段本机 Docker Desktop 曾被卸载；同日已重新安装并完成 daemon、Linux container 与 Compose 静态配置基础验证，最新状态见上方记录。

### 下一步

1. 先处理 Docker Hub 经 Docker Desktop 内部代理访问时的 EOF，再补跑 Sprint 6 完整容器门禁并正式发布 `v0.4.0`；基础 daemon、Linux container 和 Compose 配置验证已恢复。
2. 按现有计划推进 Sprint 7/8 Rust 桌面客户端和配套后端同步契约。
3. 从 `BE-036` 开始补齐 Sprint 9 产品 API，再建立 `frontend/` 并执行 Sprint 10。
4. 身份、安全和规模治理完成后，执行 Sprint 13 稳定版门禁并发布 `v1.0.0`。

### 验证

- 已检查新增 Sprint、任务编号、依赖关系、验收物、风险和远期 Backlog 均已写入执行计划与完整技术计划。
- 本轮是文档规划变更，后端运行时、OpenAPI、数据库、Compose 和现有测试行为未发生变化。
- 规划补全当时因 Docker Desktop 已卸载，未执行容器验证；同日重装后已补做 daemon、Linux container 和 Compose 静态配置检查，完整项目栈、备份恢复与 Testcontainers 仍待后续门禁。

### 涉及文件

- `AGENT.md`
- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`
- `README.md`
- `企业网盘开发者技术计划书.md`

## 2026-07-31 Rust 桌面客户端纳入二期计划

### 已完成

- 检查当前仓库和规划，确认仓库中没有 `desktop/`、桌面应用或同步客户端代码；原完整技术计划只把“完整桌面同步客户端”排除在一期，并笼统列为 P3 二期增强项。
- 将桌面客户端提升为正式 Sprint 7 和 Sprint 8 路线，目标版本为 `0.5.0`，采用 Rust stable、Cargo workspace 和 Tauri 2，Windows 11 优先，Windows 稳定后再评估 macOS 和 Linux。
- 明确 Rust 负责 API client、设备会话、同步引擎、本地 SQLite 索引、传输队列、文件系统监听、系统凭据和更新验签；界面层不保存同步事实状态。
- 明确桌面端开工前的后端依赖：opaque device session、设备列表与吊销、增量变更 cursor、删除 tombstone、版本前置条件、幂等客户端操作 ID 和 cursor 失效错误码。
- 明确首个 Alpha 范围：登录、空间/目录浏览、上传下载队列、暂停/继续/取消、同步目录选择、离线元数据、任务栏托盘和脱敏诊断导出。
- 明确双向同步规则：临时文件下载、SHA-256 校验后原子替换、离线操作日志、异常退出恢复、冲突副本、Windows 路径规范、默认不跟随符号链接或 junction、签名安装和更新回退。
- 已同步 `AGENT.md`、`PROJECT_PLAN.md`、`README.md` 和《企业网盘开发者技术计划书.md》。

### 版本影响

- 本轮只调整规划和开发约束，不新增数据库 migration、业务 API、客户端代码或发布工件，当前项目版本保持 `0.4.0`。
- Rust 桌面客户端属于向后兼容的新产品能力，首个 Alpha 目标版本为 `0.5.0`；实际版本提升在桌面端和配套后端契约开始交付时执行。

### 进行中

- 桌面客户端尚未开始编码；`desktop/` Cargo workspace、Tauri 应用、设备会话和增量同步 API 均仍待实现。

### 阻塞与风险

- 当前浏览器认证使用 BFF + HttpOnly Cookie Session，Rust 后台同步进程需要独立的 opaque device session，不能直接复制浏览器 Cookie 方案。
- 当前文件 API 适合交互式浏览与传输，但缺少增量变更日志、删除 tombstone 和版本前置条件，直接开始双向同步会产生全量轮询、漏删除或静默覆盖风险。
- Windows 大小写折叠、保留设备名、尾随点/空格、长路径、文件锁和 reparse point 必须在统一 Rust 平台适配层处理。
- 桌面安装包、自动更新和系统凭据都涉及平台安全能力，必须在 Alpha 阶段就接入签名、验签、吊销和日志脱敏，不能留到正式版前补做。

### 下一步

1. 先完成当前 Sprint 6 收尾和 `v0.4.0` 正式发布。
2. 创建桌面架构 ADR，固定 Tauri/Rust 模块边界、本地数据模型、同步状态机、冲突策略和 Windows 路径规则。
3. 先实现后端设备会话与增量变更契约及测试，再建立 `desktop/` Cargo workspace。
4. 按“Rust API client -> SQLite 本地索引 -> 单向上传下载 -> 本地监听 -> 双向同步 -> 签名发布”顺序推进。

### 验证

- 已检查当前仓库不存在桌面客户端目录或 Rust workspace。
- 已检查执行计划和完整技术计划中的一期边界、优先级、里程碑、任务拆分、验收物、风险和结论均已同步桌面端路线。
- 本轮为文档规划变更，不涉及后端运行时、OpenAPI、Compose 或数据库行为。

### 涉及文件

- `AGENT.md`
- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`
- `README.md`
- `企业网盘开发者技术计划书.md`

## 2026-07-16 Windows 备份恢复自动化完成

### 已完成

- 项目版本已统一提升到 `0.4.0`，应用配置、`pyproject.toml`、`uv.lock`、健康检查测试、README、执行计划和完整技术计划书保持一致；本轮不修改数据库结构、业务 API、对象存储 key 或 Worker payload。
- `deploy/windows/manage.ps1` 已正式提供 `backup`、`backup-verify` 和 `restore`，并对动作专属参数、TLS 模式、环境文件、备份路径、CMS 输出路径、`-ForceRestore` 和 `-NoStartAfterRestore` 做入口门禁。
- `deploy/windows/backup-restore.ps1` 已形成完整 Windows Docker Desktop 备份恢复流程：
  - 从实际 `docker compose config --format json` 和 Docker runtime 读取 Compose project、Git commit、项目版本、网络、逻辑卷、物理卷、服务 image reference 及实际 image ID，不手拼运行时资源名称。
  - 备份 manifest 固定记录 15 个默认 Compose 服务的实际 image ID，并记录 PostgreSQL revision/WAL、MinIO bucket、OpenSearch index、TLS certificate lineage、源服务运行/退出/健康状态及配置摘要。
  - PostgreSQL 使用 custom-format `pg_dump`；MinIO、Redis、OpenSearch 和 TLS 证书卷在停止写入面后归档；成功校验的受限 ACL staging 目录才会原子发布。
  - 备份与恢复同时持有 project mutex 和按物理卷名称排序的 volume mutex，避免不同 project 实际映射到同一卷时并发读写。
  - 备份目录、回滚目录和解密后的 CMS 文件自动应用受保护 NTFS DACL，只允许当前用户、SYSTEM 和 Administrators 完全控制，并在发布前后复核。
  - tar 工件会先在临时卷中以只读根文件系统、无网络、drop capabilities 和 `no-new-privileges` 方式预解包扫描，拒绝特殊文件、hardlink、绝对 symlink、越界 symlink 和缺失 symlink 目标，再允许写入目标卷。
  - 恢复严格校验嵌套 manifest schema、manifest 与工件 SHA-256、Compose 配置 SHA、Git commit、项目版本、所有服务 image reference/image ID、bucket/index/TLS lineage、逻辑卷/物理卷唯一性和 source/target 物理卷不重叠。
  - 目标卷必须属于目标 Compose project、具有正确 logical-volume label 且无 foreign container attachment；默认拒绝现有容器和非空卷。
  - `-ForceRestore` 会先为原非空目标卷创建受限 ACL rollback archive；恢复失败时按卷原始 `missing`、`empty`、`nonempty` 三态删除、清空或回灌，若回滚本身异常则保留并报告归档路径。
  - 恢复失败会停止并清理本轮 target 运行资源、删除本轮新建卷、恢复原空卷或原非空卷，并保持 target 隔离；备份结束会按 source 原始 running/exited/absent 状态和健康状态完整对账。
  - CMS 明文输出必须是仓库和备份目录之外的绝对路径，父目录必须预先存在且路径链不得含 reparse point；明文只保存在内存，完整恢复成功末尾才以受限 ACL 临时文件原子发布。
- 新增 `deploy/windows/tests/backup-restore.smoke.ps1`，共 24 项 fake Docker/CMS smoke，覆盖路径边界、备份根目录祖先/卷根与既有非空目录 ACL 门禁、manifest/工件损坏、嵌套 manifest、mutex 竞争、CMS 正负例与发布竞态、ACL、source 状态恢复、非空卷、物理卷重叠、错误卷标签、foreign attachment、image ID 不匹配、`-NoStartAfterRestore`、CMS 延迟发布、target 失败隔离，以及恢复提交后的 rollback 清理失败不反向回滚数据。
- 新增 `deploy/windows/tests/backup-restore.integration.ps1`，使用随机 source/target Compose project 和仓库外临时目录，真实写入并恢复 PostgreSQL、MinIO、Redis、OpenSearch、TLS lineage 和 CMS 环境文件，同时校验 API、全部 Worker、beat、gateway、宿主端口边界、ACL、损坏 manifest 拒绝和运行中 target 拒绝。
- `.github/workflows/backend-ci.yml` 的 Windows job 已加入独立 backup/restore smoke，并继续递归检查 `deploy/windows/**/*.ps1` 的 PowerShell 5.1 语法、ASCII 和无 BOM。
- 已同步 `AGENT.md`、`PROJECT_PLAN.md`、`README.md`、`backend/README.md`、`docs/deployment-windows-docker.md` 和《企业网盘开发者技术计划书.md》的 `v0.4.0` 行为、安全边界、操作入口和验收要求。
- 已提交并推送 `dev`：
  - `9383659 feat: 完成 Windows 备份恢复自动化`
  - `8141e0f fix: 补齐 Windows CI Compose 模型响应`

### 版本影响

- 本轮新增可执行的备份、校验、隔离恢复和失败回滚能力，属于向后兼容的部署功能扩展，项目版本从 `0.3.0` 提升到 `0.4.0`。
- 数据库 migration、业务 OpenAPI path、对象存储 key、认证模型和 Worker payload 未发生破坏性变化；正式发布 tag 仍在后续合并 `main` 时创建。

### 验证

- 后端门禁已通过：`uv sync --frozen --all-extras --dev`、`uv lock --check`、Ruff format/check、Mypy、Pytest、Alembic SQL 和 OpenAPI；结果为 186 个文件格式通过、140 个 source file 无类型问题、`148 passed, 3 skipped`、OpenAPI `version=0.4.0` 且 29 条 path。
- 真实 MinIO 集成测试已通过，结果为 `3 passed`。
- 本机 HTTP/TLS 两套 Compose config、runtime/preview 镜像构建、默认/TLS/ACME 三套 Nginx `nginx -t` 和 `manage.ps1 config` 均已通过。
- 2026-07-16 独立复跑 `backup-restore.smoke.ps1`，结果为 `24/24 passed`。
- 四个 PowerShell 文件均通过 PowerShell 5.1 parser、ASCII 和无 BOM 检查；PSScriptAnalyzer `1.25.0` 结果为 `0 Error`、44 个命名/ShouldProcess/测试 runspace 等非阻塞 Warning。
- 2026-07-16 最终真实 integration 使用 source project `enterprise-drive-backup-source-9f05318c92` 和 target project `enterprise-drive-backup-target-9f05318c92` 完成 source -> backup -> corrupt verify -> target restore：
  - PostgreSQL 只恢复备份点数据，MinIO 对象回到备份点内容，Redis key、OpenSearch index、Alembic revision、TLS symlink/SAN 和 CMS 环境文件均通过。
  - API `/healthz`、真实 PostgreSQL `/readyz`、全部 Worker、beat、gateway 和仅 gateway 发布宿主端口的边界均通过。
  - 损坏 `manifest.sha256` 被拒绝，运行中的 target project 再次 restore 被拒绝。
  - 备份目录和 CMS 输出 ACL 断言通过。
- 演练结束后已确认 `enterprise-drive-backup-*` containers、volumes、networks、宿主临时目录和测试 CMS 证书均为 0。
- Workflow YAML 已由 PyYAML 解析，顶层 `name`、`on`、`jobs` 和四个 job 均存在；`git diff --check` 已通过。
- GitHub Actions 首次 run `29436231488` 的 backend、MinIO image policy、MinIO supply-chain 及新增 backup/restore smoke 均通过；Windows TLS fake Docker guard 因旧 fixture 未返回新增 mutex 所需的 Compose JSON model 而失败。补齐最小 fake `config --format json` 响应后，已在本机直接执行 workflow 原始 PowerShell block 并通过。
- GitHub Actions 最终功能验证 run `29436565873` 已通过全部 backend、windows-deployment、minio-image-policy 和两组 minio-supply-chain job；Windows job 同时通过 PowerShell parser/编码、24 项 backup/restore smoke 和 TLS fake Docker guards。

### 阻塞与风险

- Windows CMS 只保护 `.env.windows`；PostgreSQL dump、MinIO/Redis/OpenSearch 原始卷和含 TLS 私钥的归档仍依赖 BitLocker、受限 NTFS ACL、加密外部介质和受控保管链。
- `manifest.sha256` 和工件 SHA-256 只提供完整性检查，不认证备份制作者身份；来源认证仍需受保护签名或受控传输与保管链。
- Redis/OpenSearch 原始卷恢复限定相同 image reference、相同实际 image ID 和单节点同拓扑；跨版本或拓扑变化必须使用对应产品支持的迁移/快照机制。
- 该次备份恢复收尾时记录的是先前较宽的 MinIO Critical 基线；2026-08-03 已复核为 Server/Client 16/9 个唯一 ID，其中两个 MinIO 自身 Critical 尚无社区版 patched version，正式上线前仍需采用受支持修复镜像或可审计补丁镜像。
- `-ForceRestore` 回滚属于尽力恢复；回滚异常时会保留受限 ACL rollback archive 并报告路径，仍需人工确认数据状态。
- 真实公网 DNS、受信证书签发、外部双域名 HTTPS 和实际 Certbot renewal lineage 续期仍属于生产环境验收项。

### 下一步

1. 按生产恢复演练周期配置独立备份介质、保留策略、离线副本、告警和定期抽样恢复记录。
2. 恢复推进 MinIO multipart 稳定封装、真实对象存储异常恢复与升级兼容、高密级代理下载、多维配额和治理任务告警。

### 涉及文件

- `.github/workflows/backend-ci.yml`
- `AGENT.md`
- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`
- `README.md`
- `backend/README.md`
- `backend/app/core/config.py`
- `backend/pyproject.toml`
- `backend/tests/test_app.py`
- `backend/uv.lock`
- `deploy/windows/manage.ps1`
- `deploy/windows/backup-restore.ps1`
- `deploy/windows/tests/backup-restore.integration.ps1`
- `deploy/windows/tests/backup-restore.smoke.ps1`
- `docs/deployment-windows-docker.md`
- `企业网盘开发者技术计划书.md`

## 2026-07-15

### 已完成

- 为同一个 `gateway` service 增加公网 TLS 模式：`manage.ps1 -Tls` 会把宿主入口切换为 `80/443`，使用 `deploy/windows/nginx/tls.conf.template` 按 API/存储双域名 Host 分流，并保留默认本机 HTTP `18080/19000` 模式。
- 新增 `deploy/windows/nginx/acme-bootstrap.conf.template`，首次签发期间只开放 `/gateway-healthz` 和 `/.well-known/acme-challenge/`，其他请求返回 `503`；签发成功后强制重建 gateway 并切换到 TLS 模板。标准端口集成发现已配置 Host 的 `/gateway-healthz` 被维护页覆盖后，已为 bootstrap 的域名 server block 补齐显式健康端点。
- 在正式 Compose 中增加 `tls-certificates`、`tls-acme-webroot`、`tls-certbot-work`、`tls-certbot-logs` named volumes 和 `tls-tools` profile 下的一次性 Certbot 服务；Certbot 不发布宿主端口，证书私钥只由 gateway 只读挂载。
- 公网 Nginx 模板已启用 TLS 1.2/1.3、HTTP/2、HTTP `308` 跳转、HSTS、未知 Host 拒绝、安全响应头、API WebSocket 代理和 MinIO 原始 Host/请求体保留。
- 扩展 `deploy/windows/manage.ps1`：新增 TLS 配置校验、`tls-init`、`tls-renew`、`tls-certificates`、Windows 计划任务注册/精确幂等删除、续期后的 `nginx -t` 与热重载；`down -Volumes` 成功清理 Certbot profile 全部卷后再删除对应续期任务。续期前的证书检查允许即将到期或已过期证书进入 Certbot，避免被 24 小时有效期门禁提前阻断，续期后再执行严格有效期检查；续期和计划任务注册还会拒绝缺少 Certbot renewal lineage 的手工/自签名证书。首次签发改用同一 gateway service 的临时 one-off bootstrap 容器，已有 gateway 停止但保留，签发失败会删除临时容器并恢复原入口。
- 修复公网 Trusted Hosts 模式下 API 容器健康检查使用 `127.0.0.1` Host 导致 `/readyz` 返回 400 的问题；healthcheck 现在访问回环地址但显式携带 `DRIVE_SERVER_NAME` Host。
- 公网配置校验新增非回环 IPv4 bind、数据库/Redis URL 密码一致性和 MinIO CORS 对齐门禁：`MINIO_CORS_ALLOWED_ORIGIN` 必须与 `DRIVE_CORS_ORIGINS` 精确一致且全部为 HTTPS origin，避免 API CORS 已切换 HTTPS 但预签名 PUT/GET 仍被 MinIO 的本机 HTTP origin 拒绝。
- CI 新增公网 TLS Compose 渲染、ACME/TLS Nginx 模板语法验证和 Windows PowerShell 5.1 `manage.ps1` parser/guard job；Nginx 验证使用临时自签名双域名证书，不依赖真实公网证书。
- 同步更新 AGENT、README、执行计划、完整技术计划书和 Windows Docker 部署文档中的 TLS、续期、健康检查、版本与验收规则。

### 版本影响

- 本轮新增公网 TLS/ACME/续期能力，属于向后兼容的部署功能扩展，项目版本从 `0.2.0` 提升到 `0.3.0`。
- `backend/pyproject.toml`、`backend/uv.lock`、应用 Settings、`/healthz` 测试和相关文档版本已同步为 `0.3.0`。
- 数据库结构、API 契约、对象存储 key 和 Worker payload 未变化；正式发布 tag 在后续合并 `main` 时创建。

### 进行中

- Windows Docker 本机 HTTP 和公网 TLS 代码/本机自签名闭环已完成，标准宿主 `80/443` 已在隔离完整编排中实测；真实公网 DNS、受信证书签发、外部网络双域名 HTTPS、浏览器信任链和 Certbot renewal lineage 实际续期仍需在生产环境验收。
- 备份与恢复当前只有上线前原则和操作检查清单，尚未形成可执行流程；后续仍需补 PowerShell 自动化脚本、加密与校验、同一业务时间点编排和隔离环境恢复演练。

### 阻塞与风险

- 当前机器没有可用于本项目的真实公网双域名与受信证书，因此 ACME 生产签发、外部网络到宿主 `80/443` 和浏览器信任链尚未实测，仍是上线前环境验收项；本机标准端口映射本身已通过。
- Windows 计划任务续期依赖运行 Docker Desktop 的同一用户和可用的 Linux engine；宿主重启、用户会话和 Docker Desktop 自启动策略必须在生产机演练。
- `MINIO_IMAGE`、`MINIO_MC_IMAGE` 示例仍使用 `latest`，正式发布前应固定已验证 tag 或 digest。

### 下一步

- 在真实生产 DNS/网络环境执行 `tls-init -Tls`、注册每日续期任务，并实测 API/存储双域名的外部 `80/443`、受信证书链、HTTP 跳转和预签名 PUT/GET。
- 增加 PostgreSQL/MinIO/证书卷备份与恢复 PowerShell 自动化，并在隔离 Compose project 中完成同一业务时间点恢复演练。
- 固定 MinIO/MinIO Client 镜像 tag 或 digest，补镜像 SBOM 与漏洞扫描。
- 完成上线治理后，再恢复推进 MinIO multipart 稳定封装、高密级下载代理、多维配额和治理任务告警等业务任务。

### 验证

- 已运行 `uv sync --frozen --all-extras --dev`、`uv lock --check`、Ruff、Mypy、Pytest、Alembic SQL 和 OpenAPI 生成；结果为 `186 files already formatted`、`140 source files` 无类型问题、`148 passed, 3 skipped`、OpenAPI `version=0.3.0` 且 29 条 path，锁文件和迁移链通过。
- 已运行本机 HTTP 与公网 TLS 两套 `docker compose config --quiet`，并通过 Windows PowerShell 5.1 parser 校验 `manage.ps1` 和 workflow 中的完整 PowerShell step；TLS 参数校验覆盖双域名格式、非回环 IPv4 bind、HTTPS S3 根 URL、Secure Cookie、Trusted Hosts、API/MinIO HTTPS CORS、生产 secret、数据库/Redis URL 密码一致性及保留字符百分号编码正例。
- 已使用 `certbot/certbot:v5.6.0` 生成临时双域名自签名证书，在 `nginx:1.27-alpine` 中验证 ACME bootstrap 和 TLS 模板 `nginx -t`；本机运行验证 HTTP 返回 `308`、API/存储两个 HTTPS Host 的 `/gateway-healthz` 均返回 200，ACME challenge 可读取共享 webroot，已配置 Host 的 bootstrap `/gateway-healthz` 返回 200，非 challenge 请求返回 503。
- 已在隔离 Compose project `enterprise-drive-tls-integration` 中真实构建 `runtime`/`preview` 镜像并启动完整正式编排；API、gateway、5 类 Worker、beat、PostgreSQL、Redis、MinIO、OpenSearch 全部 healthy，migration/seed/minio-init 均退出 0，`/healthz` 返回 `version=0.3.0`，`/readyz` 返回数据库 ready。
- 隔离 TLS 编排首次启动暴露 API healthcheck 的 Host 不在 Trusted Hosts，导致 `/readyz` 400；修复为显式使用 `DRIVE_SERVER_NAME` 后重新启动通过，形成公网 Trusted Hosts 回归验证。
- 已通过 `storage.test` TLS Host 使用 MinIO Client 的 S3v4 签名完成对象 pipe/stat/cat/remove，确认 gateway 保留存储 Host、请求方法、查询参数和请求体；只有 gateway 发布测试宿主端口 `18083/18444`。
- 已在隔离 Compose project `enterprise-drive-tls-standard-0715` 使用标准宿主 `80/443` 再次启动完整正式编排；API、gateway、5 类 Worker、beat、PostgreSQL、Redis、MinIO、OpenSearch 全部 healthy 且 restart count 为 0，migration/seed/minio-init 退出 0。实测 HTTP `308`、`/healthz` 版本 `0.3.0`、数据库 `/readyz`、HSTS、MinIO CORS 204、S3v4 pipe/stat/cat/remove、未知 Host 空连接拒绝，以及只有 gateway 发布宿主端口。
- 已真实停止但保留标准端口 TLS gateway，用同一 service 启动 one-off bootstrap；确认已配置 Host 的 `/gateway-healthz` 返回 200、普通路径返回 503、原 gateway 容器保持 exited，删除临时容器后原 gateway 恢复 healthy 和 HTTPS 服务。
- 自签名证书卷没有 Certbot renewal lineage；真实 Docker 运行已确认 `tls-renew` 在续期前明确拒绝该状态，不再把手工证书误记为“无续期任务后热重载”。Windows fake Docker 流程验证了成功路径固定使用 `--cert-name enterprise-drive`、renew 前允许不足 24 小时证书进入 Certbot、renew 后执行严格证书检查和 Nginx 热重载；实际受信证书续期仍待生产 lineage 演练。
- 已真实创建临时 Windows 计划任务并用不同大小写名称执行幂等删除；再次创建后，`down -Tls -Volumes` 成功清理全部业务/TLS volumes、containers、networks、标准端口和对应计划任务。
- 已解析 `.github/workflows/backend-ci.yml`，并在 Windows PowerShell 5.1 复现 TLS Compose、证书生成、Nginx 模板和 fake Docker guard；覆盖 tls-init 签发失败恢复、renewal lineage、renew 前后有效期门禁、MinIO CORS、loopback bind、数据库密码不一致、危险证书名在 shell 检查前拒绝和续期 cert name。已检查全部改动文件为 UTF-8 无 BOM、Markdown fence 成对、`manage.ps1` 保持 ASCII，`git diff --check` 通过；测试 containers/volumes/networks/tasks 和 `80/443` 均无残留。
- GitHub Actions `backend-ci` run `29359205421` 已通过：Linux backend job 完成依赖同步、MinIO 集成、Ruff、Mypy、Pytest、两套 Compose/Nginx 校验和 runtime/preview 镜像构建，Windows deployment job 完成 PowerShell parser 与全部 TLS guard 验证。

### 涉及文件

- `.env.windows.example`
- `.github/workflows/backend-ci.yml`
- `AGENT.md`
- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`
- `README.md`
- `backend/README.md`
- `backend/app/core/config.py`
- `backend/pyproject.toml`
- `backend/tests/test_app.py`
- `backend/uv.lock`
- `compose.windows.yml`
- `deploy/windows/manage.ps1`
- `deploy/windows/nginx/acme-bootstrap.conf.template`
- `deploy/windows/nginx/tls.conf.template`
- `docs/deployment-windows-docker.md`
- `企业网盘开发者技术计划书.md`

## 2026-07-14

### 已完成

- 将正式部署方向从“Linux/Kubernetes 或宿主机 Nginx”统一修正为 Windows 11 + Docker Desktop（WSL2/Linux containers）+ 仓库根 `compose.windows.yml`。
- 明确 `compose.windows.yml` 是正式部署唯一编排入口，`backend/docker-compose.yml` 继续作为本地依赖开发清单，两者用途不得混用。
- 明确 Nginx gateway 运行在 Compose 内，并且是唯一允许发布宿主端口的服务；当前默认本机由 gateway 发布 HTTP `18080/19000`。公网模式在补齐受信证书和 TLS 配置后映射 `80/443`，API、Worker、PostgreSQL、Redis、OpenSearch、MinIO API/Console 等内部服务不发布宿主端口。
- 明确正式部署环境模板为根 `.env.windows.example`，宿主机管理入口为 `deploy/windows/manage.ps1`，Windows 侧命令统一以 PowerShell 为主。
- 明确默认本机 API 入口为 `http://localhost:18080`，S3 外部预签名入口为 `http://localhost:19000`，两者均由 gateway 发布；公网 TLS 完成后的目标分别为 `https://drive.example.com` 和 `https://storage.example.com`。gateway 按 Host 分流并保留原始 Host，S3 外部入口不使用路径前缀重写。
- 明确 S3 内外端点分离：API/Worker 使用 Compose 内部 `http://minio:9000`，浏览器只接收 gateway 暴露的 host-based 外部端点。
- 明确正式编排必须覆盖 API、一次性 migration、一次性 seed、MinIO 初始化、按职责隔离的 Celery Worker、Celery beat、PostgreSQL、Redis、MinIO、OpenSearch、Nginx gateway、named volumes、备份与回滚。
- 明确 `/healthz` 只表示进程存活，`/readyz` 必须执行真实 PostgreSQL 探针，数据库不可用时返回非 2xx，Compose 和 gateway 以 readiness 结果决定是否接流量。
- 明确 Preview Worker 与其他队列隔离，镜像内包含 LibreOffice、Poppler 和中文字体，并限制 CPU、内存、临时磁盘、并发数和子进程生命周期。
- 新增 `docs/deployment-windows-docker.md` 作为 Windows 11 Docker 正式部署、运维、备份、发布和回滚的主文档；Kubernetes、systemd 仅保留为未来可选迁移方向。

### 版本影响

- 部署架构从 Linux 宿主服务/Kubernetes 默认路径切换为 Windows 11 Docker Desktop 正式路径，属于向后兼容的部署能力增强，项目版本已按次版本规则从 `0.1.0` 提升到 `0.2.0`。
- `backend/pyproject.toml`、`backend/uv.lock` 和应用 Settings 版本已同步为 `0.2.0`；本轮已构建并验收 `runtime`、`preview` 本地镜像，正式发布 tag 在后续合并 `main` 时创建。

### 进行中

- Windows Docker 本机 HTTP 部署闭环已完成；公网受信证书、TLS server block、HTTP 到 HTTPS 跳转、证书续期和双域名 HTTPS 实测仍在进行中。
- 备份与恢复当前只有原则和检查清单，尚未形成可执行流程；后续仍需补 PowerShell 自动化脚本和隔离环境恢复演练。

### 阻塞与风险

- Docker Desktop 必须启用 WSL2 engine 和 Linux containers；Windows containers 模式不在本项目支持范围内。
- 默认本机通过 gateway 的 `18080/19000` 两个端口区分 API 与 S3；生产域名模式必须配置两个真实 DNS 名称和 TLS 证书，并让 gateway 保留原始 Host。不得为 MinIO 外部端点增加 `/s3` 等 base path。
- 当前 Nginx 工件只实现本机 HTTP `18080/19000` 和可配置 Host/端口，尚未包含证书挂载、TLS server block 或 HTTPS 自动化；公网 `80/443`、受信证书续期和 HTTPS 实测仍是上线前阻塞项。
- PostgreSQL、Redis、MinIO、OpenSearch 都使用 named volumes；更新和回滚过程中误执行 `docker compose down -v` 会删除持久化数据，管理脚本不得把该命令作为默认操作。
- OpenSearch、LibreOffice 和 Poppler 对 Docker Desktop 的 CPU、内存和磁盘要求较高，正式部署前需要按部署文档预留 WSL2 资源并验证 Preview Worker 的临时空间限制。
- 当前 OpenSearch Security Plugin 在 Compose 内关闭，服务仅位于 internal network 且不发布宿主端口；公网或跨主机拆分前必须重新评估鉴权、TLS 和网络策略。
- `MINIO_IMAGE`、`MINIO_MC_IMAGE` 示例仍使用 `latest`，正式发布前应固定已验证 tag 或 digest。

### 下一步

- 在公网发布前为 gateway 增加受信证书挂载、TLS server block、HTTP 到 HTTPS 跳转和证书续期方案，并实测 API/存储双域名的 `80/443` Host 分流。
- 增加 PostgreSQL/MinIO 备份与恢复 PowerShell 自动化，并在隔离 Compose project 中完成恢复演练。
- 固定 MinIO/MinIO Client 镜像 tag 或 digest，补镜像 SBOM 与漏洞扫描。
- Docker 部署闭环通过后，再恢复推进 MinIO multipart 稳定封装、高密级下载代理、多维配额和治理任务告警等业务任务。

### 验证

- 已确认 Docker Desktop `29.3.1` 使用 `desktop-linux` / WSL2 Linux engine，Docker Compose 为 `v5.1.0`。
- 已运行 `docker compose --env-file .env.windows.example -f compose.windows.yml config --quiet` 和 `deploy/windows/manage.ps1 config -Quiet`，均通过。
- 已实际构建 `runtime` 和 `preview` 两个镜像；运行用户均为 UID/GID `10001` 的非 root `app`。Preview 镜像内 `LibreOffice 7.4.7.2` 与 `pdftoppm 22.12.0` 可执行。
- 已完整启动 gateway、API、PostgreSQL、Redis、MinIO、OpenSearch、5 类 Worker 和 beat；`migration`、`seed`、`minio-init` 均按预期 `Exited (0)`，其余服务全部 healthy。只有 gateway 发布 `127.0.0.1:18080/19000`。
- 已验证 `/healthz` 返回 `version=0.2.0`，`/readyz` 通过真实 PostgreSQL `SELECT 1` 并返回 `checks.database=ready`。
- 已验证 MinIO CORS 预检返回 HTTP 204，并按配置返回允许 origin/method/header。
- 已完成两轮真实 6 MiB multipart 上传与下载闭环：登录、创建空间、初始化上传、gateway 预签名 PUT、complete、gateway 预签名 GET 全部成功，下载内容 SHA-256 与原内容一致，外部 URL 使用 `localhost:19000`。
- 已通过 gateway 运行真实 MinIO 集成测试，结果 `3 passed`，覆盖 multipart、presign、copy、delete、list、hash 和孤儿对象扫描。
- 初次持续运行暴露 Celery `asyncio.run()` 跨事件循环复用 asyncpg QueuePool，导致连接累积、`Future attached to a different loop` 和 PostgreSQL `too many clients`。现已增加可配置数据库池模式：API 使用受控 QueuePool，Celery Worker 使用 NullPool；新增跨事件循环回归测试。
- 修复后连续观察 2 分钟：`/readyz` 始终 200，PostgreSQL 当前业务连接保持稳定，audit/permission/search/preview/maintenance 任务持续成功，无连接池、事件循环或任务异常。
- 连接池修复后已再次运行完整质量门禁：`uv sync --frozen --all-extras --dev`、`uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy app`、`uv run pytest`、`uv lock --check`、`uv run alembic upgrade head --sql`；结果为 Ruff 通过、`186 files already formatted`、Mypy `140 source files` 无问题、`148 passed, 3 skipped`、锁文件与 Alembic SQL 通过。
- 已再次运行 `docker compose --env-file .env.windows.example -f compose.windows.yml config --quiet`、`deploy/windows/manage.ps1 config -EnvFile .env.windows.example -Quiet` 和 `git diff --check`；Compose、管理脚本和补丁格式检查均通过，文档均为 UTF-8、无 BOM，Markdown code fence 成对，陈旧默认部署方向仅保留在明确标记的历史记录中。
- 验证完成后已使用 `deploy/windows/manage.ps1 down -EnvFile .env.windows.example -Volumes` 关闭本轮测试环境；确认 Compose 项目无残留容器，`18080/19000` 均已释放，测试生成的 `enterprise-drive-windows` named volumes 与 networks 已清理。

### 涉及文件

- `AGENT.md`
- `PROJECT_PLAN.md`
- `PROJECT_PROGRESS.md`
- `README.md`
- `backend/README.md`
- `docs/deployment-preview-worker.md`
- `docs/deployment-windows-docker.md`
- `企业网盘开发者技术计划书.md`
- `.github/workflows/backend-ci.yml`
- `.env.windows.example`
- `.gitattributes`
- `.gitignore`
- `compose.windows.yml`
- `deploy/windows/manage.ps1`
- `deploy/windows/nginx/default.conf.template`
- `backend/Dockerfile`
- `backend/.dockerignore`
- `backend/.env.example`
- `backend/app/core/config.py`
- `backend/app/db/session.py`
- `backend/app/health.py`
- `backend/app/infrastructure/queue/celery_app.py`
- `backend/app/infrastructure/queue/schedule.py`
- `backend/app/infrastructure/storage/s3.py`
- `backend/tests/test_app.py`
- `backend/tests/test_celery_schedule.py`
- `backend/tests/test_db_session.py`
- `backend/tests/test_storage_s3_endpoints.py`
- `backend/pyproject.toml`
- `backend/uv.lock`

## 2026-07-01

### 已完成

- 实现过期上传清理服务 `UploadCleanupService`，按租户扫描过期的 `initiated`、`uploading`、`completing` 上传会话。
- 上传清理会将会话标记为 `expired`，再最佳努力调用对象存储 `abort_multipart_upload` 并删除 `uploads/...` 临时对象；清理失败会记录到任务统计和审计 metadata，不回滚已过期终态。
- 为维护任务补充租户列表查询和上传会话按租户加锁读取，避免跨租户扫描。
- 新增 `upload.expire_sessions` Celery 任务并路由到 `maintenance` 队列，任务参数支持 `tenant_id`、`limit` 和 `request_id`。
- 新增系统审计写入路径，过期清理写入 `upload.expired` 审计事件和 outbox event，actor_type 为 `system`。
- 在 multipart complete 重新加锁最终写入前补充状态校验，避免过期清理与完成上传并发时继续创建文件版本。
- 补充上传清理测试，覆盖过期会话清理、终态/未到期会话跳过、对象存储 abort/delete 调用和审计写入。
- 同步更新 README、后端 README、执行计划和完整技术计划书中的过期上传清理状态、maintenance 队列职责和下一步说明。
- 新增限流基础设施，提供 `RateLimiter` 协议、Redis 固定窗口实现和测试用内存固定窗口实现。
- 上传初始化已按 `tenant + user` 维度接入基础限流，触发后返回 HTTP 429 和 `RATE_LIMITED`。
- 分片签名已按 `tenant + user + upload session` 维度接入基础限流，避免同一用户不同上传会话互相误伤。
- 下载预签名已按 `tenant + user + node + IP` 维度接入基础限流。
- 新增限流配置项：`DRIVE_RATE_LIMIT_ENABLED`、`DRIVE_UPLOAD_INIT_RATE_LIMIT_COUNT`、`DRIVE_UPLOAD_INIT_RATE_LIMIT_WINDOW_SECONDS`、`DRIVE_UPLOAD_PART_PRESIGN_RATE_LIMIT_COUNT`、`DRIVE_UPLOAD_PART_PRESIGN_RATE_LIMIT_WINDOW_SECONDS`、`DRIVE_DOWNLOAD_PRESIGN_RATE_LIMIT_COUNT`、`DRIVE_DOWNLOAD_PRESIGN_RATE_LIMIT_WINDOW_SECONDS`。
- 补充限流测试，覆盖上传初始化、分片签名、分片签名 session 维度隔离和下载预签名的 429 行为。
- 同步更新 README、后端 README、执行计划和完整技术计划书中的基础限流状态、配置项和下一步说明。
- 新增 `DELETE /api/v1/files/{node_id}/purge` 彻底删除接口，只允许彻底删除已在回收站的节点。
- 删除到回收站保持容量占用不变；彻底删除会删除节点元数据和文件版本，按版本大小合计释放空间容量，并写入 `reason=file_purged`、`ref_type=node` 的负向容量流水。
- 彻底删除会扣减相关 `file_blobs.ref_count`，但不在接口事务中同步删除对象存储最终对象；本轮已由 `file.cleanup_unreferenced_blobs` 维护任务接管 DB 驱动的最终对象清理。
- 补充彻底删除响应模型 `PurgeNodeResponse`，返回根节点 ID、彻底删除节点数量和释放容量字节数。
- 补充文件操作测试，覆盖软删不释放容量、彻底删除文件释放容量、彻底删除目录释放后代版本容量、blob 引用计数扣减、审计写入、活跃节点和根目录拒绝彻底删除。
- 同步更新 README、后端 README、执行计划和完整技术计划书中的彻底删除容量释放策略、接口清单、后续容量校准和对象生命周期边界。
- 按新的开发约束暂停容量校准推进，先在 `AGENT.md` 补充“优先复用成熟库、标准工具、开放协议、框架能力或可信开源实现；实验功能在鲁棒性、可扩展性和可维护性前提下保持简洁”的规则，并要求轻量自研实现记录原因、范围、限制和替换触发条件。
- 根据补充要求修正 `AGENT.md`：不默认引入或直接依赖云厂商专有 SDK，外部能力优先使用开放协议、兼容接口、标准客户端或可替换的开源适配器；确需临时使用 SDK 时必须封装在 infrastructure 适配层并记录替换计划。
- 完成复用成熟库、开放协议和禁止默认云厂商 SDK 维度的代码审计，新增 `docs/code-audit-2026-07-01.md`。
- 审计确认高优先级问题：当前对象存储默认实现仍直接依赖 `boto3/botocore`，虽然已封装在 `StorageAdapter` 适配层，但依赖基线和默认实例化与最新 AGENT 规则冲突，需要优先替换为开放协议或非云厂商专有的开源 S3 兼容客户端。
- 审计确认中优先级问题：当前 Redis 固定窗口限流为轻量自研实现，`INCR` 与 `EXPIRE` 分离执行，异常时可能留下无 TTL key；后续应使用成熟限流库或 Redis Lua 原子脚本。
- 审计确认分页游标、文件名校验、上传 hash 规范化、outbox 退避和文件树遍历属于可暂时保留的轻量实现，并已记录适用范围、已知限制和替换触发条件。
- 按“项目尚未上线，不保留旧兼容”的要求，将浏览器认证改为 BFF + HttpOnly Cookie Session：移除 JWT 生成与校验、`python-jose` 依赖、`Authorization: Bearer` 入口和 `/auth/refresh` 路径。
- 认证存储从 refresh token 语义改为 `auth_sessions`：服务端只保存 opaque session token 的哈希和 CSRF token 哈希，登录写入 `drive_session` HttpOnly Cookie 和 `drive_csrf` 可读 Cookie。
- 新增 `POST /api/v1/auth/session/rotate` 和 `POST /api/v1/auth/logout`，会话轮换会签发新的 session token 与 CSRF token，旧 session 被复用时吊销整个 session family。
- `get_current_user` 已统一从 session cookie 认证；`POST`、`PUT`、`PATCH`、`DELETE` 等有副作用请求必须校验 `X-CSRF-Token`，并补充业务接口空间创建缺少 CSRF 时返回 `CSRF_TOKEN_INVALID` 的测试。
- 对象存储默认实现已移除 `boto3/botocore`，改用非云厂商专有的 MinIO Python SDK；业务层仍只依赖 `StorageAdapter` 协议。
- Redis 固定窗口限流已改为 Lua 脚本，在一次 `EVAL` 内完成 `INCR`、条件 `EXPIRE` 和 `TTL` 读取，避免留下无 TTL key。
- 同步更新 `AGENT.md`、README、后端 README、执行计划、完整技术计划书和代码审计记录中的认证、对象存储与限流说明。
- 已按要求恢复 `stash@{0}: paused quota reconciliation draft` 中的容量校准草稿，并按 AGENT 规则整理为基于现有 SQLAlchemy、Celery 和 PostgreSQL 事实表的维护任务，没有引入新的外部依赖或自研调度框架。
- 复查暂停的容量校准草稿：当前 `refs/stash` 已为空，但已从 Git unreachable commit 中定位到 `75600a4 On dev: paused quota reconciliation draft`；其内容已由 `8310cda`、`bd6de63` 和 `1a0960b` 的容量校准提交覆盖，并保留后续幂等与批量扫描修正。
- 新增 `QuotaReconciliationService`，以 `file_versions` 和 `nodes.space_id` 汇总实际空间容量，支持 `repair=false` 只读报告模式和 `repair=true` 修复模式。
- 容量校准修复模式会补建缺失的空间容量账户；已有账户修复前使用数据库行锁并重新聚合实际用量和账本合计，再校准 `quota_accounts.used_bytes`，并只按最新差额写入 `reason=quota_reconciled` 的账本流水，重复执行不会追加无差额修复流水；修复时写入 `quota.reconciled` 系统审计和 outbox event。
- 新增 Celery 维护任务 `quota.reconcile_space_usage` 并路由到 `maintenance` 队列，支持 `tenant_id`、`limit`、`repair`、`request_id`、`scan_all` 和 `max_items` 参数；统计始终完整，返回明细超过 `max_items` 时用 `items_truncated=true` 标记。
- 按 AGENT 的鲁棒性和可扩展性要求修正容量校准扫描边界：`limit` 作为单批大小，worker 默认通过 cursor 分批扫完整个租户，避免定期任务长期只校准第一批空间。
- 补充容量校准测试，覆盖只读报告不落库、修复快照和账本漂移、重复修复幂等、补建缺失空间容量账户、系统审计写入、worker 聚合入口和返回明细截断。
- 本次再次按 `stash@{0}: paused quota reconciliation draft` 复核容量校准恢复状态：当前 `refs/stash` 为空，原草稿 Git 对象 `75600a4 On dev: paused quota reconciliation draft` 仍可追溯，其有效内容已由当前 `dev` 的容量校准提交吸收；补充修正缺失空间容量账户且实际用量为 0 时的修复统计，确保补建账户也计入 `repaired_accounts`，且不写入无差额账本流水。
- 新增 `file_blobs.status`，用 `active` / `deleting` 区分可复用内容对象和正在清理的内容对象；上传秒传和 multipart complete 只复用 active blob，同 hash blob 正在清理时返回 `BLOB_DELETING`。
- 新增 `BlobCleanupService`，按租户扫描 `ref_count=0`、`status=active` 且无 `file_versions` 引用的 blob，先标记为 `deleting`，再在数据库事务外删除对象存储内容，最后删除 blob 元数据。
- 对象存储删除失败时会恢复 blob 为 `active`，计入 `storage_errors`，并写入 `file.blob.cleanup_failed` 系统审计；删除成功会写入 `file.blob.cleaned` 系统审计和 outbox event。
- 新增 Celery 维护任务 `file.cleanup_unreferenced_blobs` 并路由到 `maintenance` 队列，支持 `tenant_id`、`limit` 和 `request_id` 参数。
- 补充 blob 清理测试，覆盖成功清理对象和元数据、对象存储删除失败恢复 active、仍被版本引用时跳过、worker 聚合入口和上传初始化遇到 deleting blob 时拒绝复用。
- 新增权限模块基础表 `space_members`，记录用户在空间内的 `owner`、`admin`、`editor`、`viewer` 角色，带租户、空间、用户唯一约束和角色 CHECK 约束。
- 创建空间时会在同一事务内写入创建者的 `owner` 空间成员关系，为后续 PermissionService 替换临时 owner 边界提供事实表。
- 补充空间创建测试，确认创建空间会同步创建根目录、容量账户、owner 成员、审计日志和 outbox event。
- 新增 `PermissionService` 空间级角色检查，使用固定动作集合和角色白名单，不引入复杂权限表达式引擎。
- 空间列表已改为按 `space_members` 成员关系返回；文件树、上传初始化、multipart complete 和下载已接入空间级动作检查，非成员或角色权限不足仍返回统一的 `SPACE_NOT_FOUND` / `NODE_NOT_FOUND`。
- 补充权限接入测试，覆盖非成员不可见、viewer 可列空间和文件、viewer 不能创建文件夹或初始化上传、viewer 可下载已有文件。
- 新增空间成员管理 API：`GET/POST /api/v1/spaces/{space_id}/members`、`PATCH/DELETE /api/v1/spaces/{space_id}/members/{user_id}`，owner/admin 可添加、查看、调整和移除成员。
- 空间成员变更会递增 `spaces.permission_version`，写入 `permission.space_member.added`、`permission.space_member.updated`、`permission.space_member.removed` 审计；无权管理成员的请求写入 denied 审计。
- 成员管理已保护最后一个 `owner`，拒绝删除或降级最后一个空间所有者；重复添加成员返回 `SPACE_MEMBER_EXISTS`，目标用户不存在或不可用返回 `USER_NOT_FOUND`。
- 成员管理编排服务放在 `space` 模块，通过 `AuthService` 查询目标用户，避免权限模块直接依赖空间和认证模块的 repository。
- 补充空间成员管理测试，覆盖 owner 管理成员生命周期、viewer 越权被拒、admin 可查看成员、角色变更后权限即时生效、移除成员后失权以及最后 owner 保护。
- 新增 `acl_entries` 节点 ACL 基础表，支持用户主体、`allow` / `deny`、动作集合、继承开关和同节点同用户同 effect 唯一约束。
- `PermissionService` 新增节点级权限判断：空间角色作为默认授权，节点 ACL 显式 `deny` 优先于角色和 ACL `allow`，ACL `allow` 可为已有空间成员补充节点动作。
- 新增节点 ACL 管理 API：`GET/POST /api/v1/files/{node_id}/acl`、`PATCH/DELETE /api/v1/files/{node_id}/acl/{entry_id}`；节点 ACL 变更会递增 `nodes.permission_version` 并写入 `permission.node_acl.*` 审计。
- 文件列表、创建文件夹、上传初始化、multipart complete 和下载入口已接入节点路径 ACL 校验；上传 complete 会重新检查父目录 `upload` 权限，避免上传会话创建后权限收紧仍可完成。
- 补充节点 ACL 测试，覆盖 viewer 通过 ACL allow 获得上传权限、ACL 删除后失权、editor 被继承 deny 覆盖、关闭继承后子目录恢复角色权限、ACL deny download 返回统一隐藏错误并写拒绝审计。
- 空间成员和节点 ACL 的新增、更新、删除已在同一业务事务中写入 `permission.changed` outbox event，payload 包含 `scope`、`resource_id`、`permission_version`、`reason`、`actor_id`、`affected_user_id` 和变更摘要，为 Redis 权限缓存失效和搜索 ACL 重建提供输入。
- 补充权限变更事件测试，覆盖空间成员 add/update/remove 和节点 ACL create/update/remove 均写入 `permission.changed`，并校验 scope、reason、permission_version 和 affected_user_id。
- `PermissionService` 新增 `batch_check_nodes`，文件列表复用父路径为当前页子节点批量评估常用动作权限，并在 `FileNodeResponse.permissions` 返回结果，避免列表页 N+1 权限查询。
- 补充节点 ACL 测试，覆盖 editor 被继承 deny 后文件列表中子节点 `upload=false`，关闭继承后列表权限恢复为 `upload=true`。
- 新增 Redis 权限缓存失效适配器，统一权限缓存 key 规则为 `permission:{tenant}:user:{user}:space:{space}:node:{node}:action:{action}:v:{permission_version}`。
- 新增 `permission.invalidate_cache` Celery 任务并路由到 `permission` 队列，消费 `permission.changed` outbox event 后删除匹配 Redis 权限缓存 key；节点 ACL 变更当前按受影响用户保守失效租户内节点权限缓存，后续有路径/closure 数据后可收窄。
- outbox dispatcher 支持按事件类型或前缀 claim；`audit.dispatch_outbox` 已限定只消费 `audit.*`，避免抢占 `permission.changed`。
- 新增 org 模块基础事实表：`departments`、`department_members`、`user_groups`、`user_group_members`，支持部门树、用户组和成员关系。
- 新增 `OrgRepository`，提供部门、用户组、成员关系创建，以及按用户列出活跃部门 ID 和用户组 ID，为后续 ACL 主体展开提供稳定接口。
- 新增 Alembic migration `20260701_0008_org_base.py` 和 org repository 测试，覆盖活跃主体过滤和重复成员关系唯一约束。
- 扩展 `acl_entries.subject_type` 支持 `user`、`department`、`group` 三类主体，新增 Alembic migration `20260701_0009_acl_subjects.py` 更新 CHECK 约束。
- 新增 `OrgService`，通过 org repository 展开当前用户所属活跃部门和用户组；`PermissionService` 在节点 ACL 判断和文件列表批量权限评估中同时匹配用户、部门和用户组主体，仍保持显式 deny 优先。
- 节点 ACL 创建接口改为使用 `subject_type` 和 `subject_id`，不保留旧 `subject_user_id` 字段；创建前会验证用户、部门或用户组存在且可用。
- 文件树、下载、上传初始化和 multipart complete 入口均注入同一事务内的 `OrgService`，部门/用户组 ACL 会覆盖高危动作二次校验。
- 部门/用户组 ACL 变更写入 `permission.changed` outbox event 时携带主体信息，不携带 `affected_user_id`，当前由 `permission.invalidate_cache` 保守失效租户内节点权限缓存。
- 新增 search 模块 ACL token builder，可从空间成员角色和搜索可见 allow ACL 生成 `acl_tokens`，并从搜索可见 deny ACL 生成 `deny_acl_tokens`；当前 token 词表包括 `space:{space_id}:role:{role}`、`user:{user_id}`、`department:{department_id}`、`group:{group_id}`，不提前生成 `public:{tenant_id}`，公共/外链主体等分享模块建模后再接入。`upload` 等非搜索可见授权不写入索引 token，仍由权限引擎二次校验兜底。
- 权限变更现在同事务额外写入 `search.acl_rebuild_requested` outbox event，避免搜索 worker 与权限缓存 worker 抢占同一条 `permission.changed` 事件。
- 新增 `search.dispatch_outbox` Celery 任务并路由到 `search` 队列；当前只消费已实现的 `search.index_requested` 事件，避免把尚未实现处理器的 `search.acl_rebuild_requested` 提前标记为 sent。
- 新增搜索适配层 `SearchIndexAdapter` 和 OpenSearch 实现，文件索引文档从 PostgreSQL 重新加载 `nodes`、当前 `file_versions`、`file_blobs`、`space_members` 和节点路径 ACL 后构建，不依赖 outbox payload 拼业务对象。
- 秒传和 multipart complete 成功后会在同一事务中写入 `search.index_requested` outbox event；`search.dispatch_outbox` 会写入 OpenSearch `drive_files_v1`，索引字段包含 `acl_tokens` 与 `deny_acl_tokens`。
- `search.dispatch_outbox` 已消费 `search.acl_rebuild_requested` 事件：`scope=space` 时重建空间内活跃文件，`scope=node` 时重建该文件或目录子树下活跃文件，确保 ACL token 随权限变更刷新。
- 新增 `GET /api/v1/search` 查询接口，使用当前用户空间角色、用户、部门和用户组构建查询 token，在 OpenSearch 查询层加入 `tenant_id`、`is_deleted=false`、`acl_tokens` allow 过滤和 `deny_acl_tokens` 排除过滤。
- 搜索结果返回前会从 PostgreSQL 重新加载节点路径，并调用 `PermissionService.can_access_node(..., action=read_meta)` 二次校验，避免权限变更后索引尚未刷新时泄露文件名或元数据。
- 搜索查询已接入 `search.query` 基础限流，按 `tenant + user + search + IP` 维度计数；新增 `DRIVE_SEARCH_QUERY_RATE_LIMIT_COUNT` 和 `DRIVE_SEARCH_QUERY_RATE_LIMIT_WINDOW_SECONDS` 配置。
- 补充搜索查询测试，覆盖空间角色可见文件、查询层 `deny_acl_tokens` 排除、索引 ACL 滞后二次权限校验过滤，以及搜索查询限流。
- 文件重命名、移动、删除到回收站、恢复和彻底删除会在同一业务事务中为受影响文件写入 `search.index_requested`；目录操作会对子树内文件逐个写入事件。
- 搜索 worker 继续复用 `SearchIndexService.index_file` 从 PostgreSQL 重新加载事实：文件仍活跃时更新 OpenSearch 文档，文件已删除或已彻底删除时删除索引文档。
- 补充文件变更搜索同步测试，覆盖单文件重命名/删除/恢复 outbox 写入、目录移动/删除/彻底删除对子文件写入索引事件，以及 worker 消费后更新和删除内存索引文档。
- 搜索查询已支持签名 cursor 分页：OpenSearch 适配器使用 `search_after`，cursor 绑定查询词和排序值，篡改或跨查询复用返回 `CURSOR_INVALID`。
- 搜索查询响应已返回 HTML 编码的 `<mark>` 高亮片段，当前覆盖 `name`、`normalized_name` 和 `content` 字段；内存搜索适配器同步模拟分页和高亮，便于单元测试覆盖。
- 补充搜索查询测试，覆盖分页不重复、`next_cursor` 返回、游标绑定查询词和搜索高亮。
- 新增搜索全文抽取入口：上传秒传和 multipart complete 成功后写入 `search.extract_requested` outbox event，`search.dispatch_outbox` 会消费该事件并调用 `SearchExtractionService`。
- `file_versions` 新增 `search_status`、`search_error` 和 `search_text` 字段；当前抽取处理 MIME 或扩展名可判定为文本、PDF、DOCX、PPTX 或 XLSX 的小文件，读取上限由 `DRIVE_SEARCH_TEXT_EXTRACT_MAX_BYTES` 控制。
- 文本/PDF/DOCX/PPTX/XLSX 抽取成功后写入 `search_text` 并刷新 OpenSearch 索引 `content` 字段；不支持的格式、源文件过大、OOXML zip 条目/未压缩大小超限或抽取后正文超过上限标记为 `skipped`，UTF-8 解码、PDF/OOXML 解析失败或加密 PDF 标记为 `failed` 且不重试，对象存储读取失败标记为 `failed` 并让 outbox 退避重试。
- 按 AGENT 规则保持抽取入口简洁可维护：本轮不自研 PDF/Office 解析器，PDF 正文抽取接入成熟开源库 `pypdf`，当前解析到版本 `6.14.2`，许可证元数据为 `BSD-3-Clause`，Python 要求 `>=3.9`，适配本项目 Python 3.12；PDF 默认最多抽取前 50 页；DOCX 正文抽取接入成熟开源库 `python-docx`，当前解析到版本 `1.2.0`，许可证元数据为 `MIT`，Python 要求 `>=3.9`，其依赖 `lxml 6.1.1` 许可证元数据为 `BSD-3-Clause`；PPTX 正文抽取接入成熟开源库 `python-pptx`，当前解析到版本 `1.0.2`，许可证元数据为 `MIT`，Python 要求 `>=3.8`；XLSX 正文抽取接入成熟开源库 `openpyxl`，当前解析到版本 `3.1.5`，许可证元数据为 `MIT`，Python 要求 `>=3.8`，其依赖 `et_xmlfile 2.0.0` 许可证元数据为 `MIT`；均适配本项目 Python 3.12；OCR 等复杂格式后续继续使用成熟开源工具或标准适配层接入。
- 新增 `TextExtractor` 协议、UTF-8 文本抽取器、`PdfTextExtractor`、`DocxTextExtractor`、`PptxTextExtractor` 和 `XlsxTextExtractor`，`SearchExtractionService` 只负责编排存储读取、状态更新和索引刷新，便于后续继续挂接 OCR 抽取器。
- 补充搜索抽取测试，覆盖上传写入抽取事件、文本正文入索引、不支持格式跳过、解码失败终态和存储读取失败重试。
- 建立分享模块基础数据模型和迁移：新增 `shares`、`share_items`、`share_recipients`、`share_access_logs`，覆盖内部分享、外链分享、提取码哈希、过期时间、访问/下载次数限制、撤销状态、分享项、内部接收人和访问日志。
- 新增 `ShareService` 和 `ShareRepository`，创建分享时逐个校验 root 节点和全部分享项的节点级 `share` 权限，分享项必须与 root 节点属于同一空间；外链原始 token 只在创建响应中返回一次，数据库只保存 token hash，提取码只保存 Argon2id hash。
- 分享创建和撤销会写入 `share.created` / `share.revoked` 审计事件，并通过既有审计 outbox 生成 `audit.share.created` / `audit.share.revoked` 事件。
- 补充分享服务测试，覆盖外链 token/passcode 哈希存储、内部分享接收人、撤销审计、仅创建者可查看/撤销、无 `share` 权限拒绝，以及额外分享项跨空间拒绝。
- 接入分享基础 HTTP API：`POST /api/v1/shares`、`GET /api/v1/shares/{share_id}`、`POST /api/v1/shares/{share_id}/revoke`，沿用 BFF Cookie Session 和 CSRF 校验。
- 分享 API 响应会在外链创建时返回一次性 `raw_token`；详情和撤销当前仅允许创建者访问，非创建者统一返回 `SHARE_NOT_FOUND`，避免泄露分享存在性。
- 补充分享路由测试，覆盖创建/详情/撤销闭环、缺少 CSRF 被拒、非创建者详情和撤销隐藏。
- 接入外链分享访问入口 `POST /api/v1/public/shares/access`：请求体使用 `tenant_slug + raw_token` 建立租户边界，按 `tenant_id + token_hash` 加载外链分享，校验状态、过期时间、提取码和访问次数限制。
- 外链访问成功时通过数据库条件 update 原子增加 `view_count`，返回分享基础信息和分享项节点 ID；成功和失败都会写入 `share_access_logs`，并通过审计服务写入 `share.external.accessed` outbox 事件。
- 外链访问已复用 Redis Lua 固定窗口限流，按 IP 总量和 `token + IP` 维度计数；新增 `DRIVE_SHARE_EXTERNAL_ACCESS_RATE_LIMIT_COUNT` 和 `DRIVE_SHARE_EXTERNAL_ACCESS_RATE_LIMIT_WINDOW_SECONDS` 配置。
- 补充外链访问测试，覆盖提取码错误、成功访问写日志、过期、撤销、访问次数耗尽和外链访问限流。
- 接入外链分享下载入口 `POST /api/v1/public/shares/download`：请求体使用 `tenant_slug`、`raw_token`、`node_id` 和可选 `passcode`，按租户边界加载外链分享。
- 外链下载会校验分享状态、过期时间、提取码、分享权限是否为 `download`、请求节点是否属于 root 或分享项、节点是否仍是同一空间内的文件、当前版本和 blob 是否存在。
- 外链下载成功时通过数据库条件 update 原子增加 `download_count`，再通过既有 `StorageAdapter.presign_download` 返回短期私有对象下载 URL；成功和失败都会写入 `share_access_logs`，并通过审计服务写入 `share.external.downloaded` outbox 事件。
- 外链下载已复用 Redis Lua 固定窗口限流，按 IP 总量和 `token + node + IP` 维度计数；新增 `DRIVE_SHARE_EXTERNAL_DOWNLOAD_RATE_LIMIT_COUNT` 和 `DRIVE_SHARE_EXTERNAL_DOWNLOAD_RATE_LIMIT_WINDOW_SECONDS` 配置。
- 补充外链下载测试，覆盖成功下载写日志和计数、下载次数耗尽、preview 权限拒绝和未分享节点隐藏；本轮按 AGENT 规则复用 `StorageAdapter`、`FileRepository` 和 SQLAlchemy 条件更新，没有引入云服务 SDK 或自研下载协议。
- 新增预览基础迁移 `20260701_0012_preview_base.py`：为 `file_versions` 增加 `preview_status` / `preview_error`，新增 `preview_artifacts` 私有预览产物表。
- 上传秒传和 multipart complete 成功后会写入 `preview.render_requested` outbox event，`preview.dispatch_outbox` 接入 Celery `preview` 队列并消费该事件。
- 扩展 `StorageAdapter.put_object_bytes`，预览 worker 通过既有对象存储适配层写入私有预览产物，没有直接依赖云服务 SDK。
- 新增图片预览渲染服务，使用成熟开源库 Pillow 将图片生成 WebP 预览产物，写入 `previews/{tenant_id}/{node_id}/{version_id}/image.webp`；非图片或超限文件明确标记为 `unsupported`。
- 新增 `GET /api/v1/files/{node_id}/preview`，按节点级 `preview` 权限校验后返回短期私有预览 URL；无产物时返回当前预览状态和错误原因。
- 补充预览测试，覆盖上传写入预览事件、worker 生成 WebP 产物、预览 URL 权限入口返回产物，以及文本文件被标记为 `unsupported`。
- 新增 PDF 预览转换器协议和 Poppler `pdftoppm` 适配器，PDF 在临时目录内渲染首页 PNG，再复用 Pillow 生成 WebP 私有预览产物；命令执行使用参数列表，不拼接 shell 字符串。
- PDF 预览新增超时、DPI 和渲染输出大小配置：`DRIVE_PREVIEW_PDF_COMMAND`、`DRIVE_PREVIEW_PDF_DPI`、`DRIVE_PREVIEW_PDF_MAX_RENDERED_BYTES`、`DRIVE_PREVIEW_COMMAND_TIMEOUT_SECONDS`。
- `PreviewRenderService` 已支持图片、PDF 和 Office 三类预览检测：缺少 PDF 渲染器标记 `unsupported/pdf_renderer_missing`，PDF 渲染超时或失败标记 `failed` 并交给 outbox 退避重试。
- 补充 PDF 预览测试，使用 fake converter 覆盖 PDF 首页生成 WebP 产物，并覆盖未配置 PDF 渲染器时标记为 `pdf_renderer_missing`，避免单元测试依赖本机 Poppler 安装状态。
- 新增 Office 预览转换器协议和 LibreOffice headless 适配器，Office 文档先在临时目录中转换为 PDF，再复用 Poppler 首页渲染和 Pillow WebP 产物链路；LibreOffice 调用使用参数列表、独立临时 profile、超时和输出大小限制，不拼接 shell 字符串。
- Office 预览新增配置：`DRIVE_PREVIEW_OFFICE_COMMAND` 和 `DRIVE_PREVIEW_OFFICE_MAX_PDF_BYTES`；缺少 Office 渲染器会标记 `unsupported/office_renderer_missing`，Office 转码超时或失败会标记 `failed` 并交给 outbox 退避重试，转码 PDF 超限会标记 `unsupported/office_preview_output_too_large`。
- 补充 Office 预览测试，使用 fake Office/PDF converter 覆盖 DOCX 预览产物生成、缺少 Office renderer 的终态，以及 LibreOffice 适配器缺失工具和扩展名校验。
- `preview.dispatch_outbox` 已补充 Celery 任务级软/硬超时和速率限制配置：`DRIVE_PREVIEW_TASK_SOFT_TIME_LIMIT_SECONDS`、`DRIVE_PREVIEW_TASK_TIME_LIMIT_SECONDS`、`DRIVE_PREVIEW_TASK_RATE_LIMIT`，在不引入新调度器的前提下限制预览队列资源占用。
- 预览 worker 已在渲染 unsupported/failed 终态和 retryable exception 时输出结构化日志字段，包括 `event_id`、`tenant_id`、`version_id`、`preview_status`、`preview_reason` 和 `retry_count`；JSON 日志 formatter 已保留 `extra` 字段，便于后续日志告警和指标接入。
- 新增 Prometheus 指标入口 `/metrics`，使用成熟开源库 `prometheus-client` 暴露文本格式指标；预览 worker 会在 unsupported/failed 终态和 retryable exception 时递增 `preview_failures_total{status,reason}`。
- 补充 metrics 和 preview worker 测试，覆盖 `/metrics` 可访问、`preview_failures_total` 暴露、预览终态失败和异常失败都会写入对应指标。
- 当时新增 `docs/deployment-preview-worker.md`，按旧方向记录宿主机 Nginx、systemd/Kubernetes 资源示例；该默认方向已在 2026-07-14 被 Windows 11 Docker Compose 部署替代，文档现已改为独立 `worker-preview` 容器、LibreOffice/Poppler 工具检查、CPU、内存、临时磁盘配额和 `/metrics` 告警建议。
- 升级 `backend-ci` workflow 使用的 `actions/checkout`、`actions/setup-python` 和 `astral-sh/setup-uv` 版本；其中 `setup-uv` 固定到已发布 tag `v8.2.0`，避免 GitHub Actions 无法解析不存在的浮动主版本。
- 已将上传/下载链路的企业级补强缺口写入 `PROJECT_PLAN.md` 和《企业网盘开发者技术计划书.md》：MinIO SDK multipart 私有方法风险、孤儿最终对象扫描、用户/租户/策略化配额、维护任务调度告警和清理指标、高密级下载代理与 Range/审计/水印/DLP、同 hash 首次上传竞争测试、真实对象存储集成测试。
- 新增对象存储反向扫描能力：`StorageAdapter.list_objects` 支持按 prefix 和 `start_after` 游标列出私有对象，MinIO 适配器复用 SDK 公开 `list_objects`，测试适配器按 key 排序模拟分页。
- 新增 `file.cleanup_orphaned_objects` 维护任务并路由到 `maintenance` 队列，默认 `dry_run=True`，按对象存储游标扫描受控 `objects/{tenant_id}/{hash_prefix}/{sha256}` key，显式 `dry_run=False` 时才删除没有 DB blob 元数据引用的孤儿最终对象。
- 孤儿最终对象扫描以 PostgreSQL `file_blobs.storage_key` 为事实来源，不处理 `uploads/`、`previews/` 等非最终对象前缀，也会跳过不符合受控 key 形态的对象；dry-run、清理成功和对象存储删除失败均写入系统审计，审计 metadata 不记录原始 storage key。
- 新增 `orphan_object_cleanup_total{status}` Prometheus counter，记录孤儿最终对象扫描、跳过、dry-run planned、清理成功和删除失败计数。
- 补充孤儿最终对象清理测试，覆盖 dry-run 不删除、真实删除并写审计、已被 DB blob 引用的对象不删除、非受控 key 跳过、对象存储删除失败审计、worker 在 `limit=1` 下通过对象游标扫完整个租户前缀。
- 按最新要求在 `PROJECT_PLAN.md` 增补独立的“上传下载企业级补强计划”小节，明确 MinIO SDK multipart 私有方法风险、孤儿最终对象持续治理、多维配额、维护任务调度告警、高密级下载代理、同 hash 首次上传并发测试和真实对象存储集成测试仍是上线前重点。
- 新增真实 MinIO 集成测试 `tests/test_storage_minio_integration.py`，默认通过 `DRIVE_RUN_MINIO_TESTS=1` 显式启用，覆盖对象读写、copy、delete、list 游标、预签名下载、multipart 私有方法封装、预签名分片 PUT、complete 后 hash 校验和孤儿最终对象扫描。
- `backend-ci` 已在 GitHub Actions 中启动临时 MinIO，并通过环境变量启用上述集成测试；`pytest` 默认本地运行时仍跳过外部服务测试，避免普通单元测试依赖对象存储。
- `pyproject.toml` 已注册 `integration` pytest marker，避免新增集成测试产生 unknown mark 警告。
- 本机已用 Docker 临时启动 MinIO 完成真实集成测试，测试后已删除 `enterprise-drive-test-minio` 容器。

### 进行中

- Sprint 5 分享、搜索和预览模块已开始；基础分享、外链访问/下载、搜索索引/抽取、PDF 正文抽取、DOCX 正文抽取、PPTX 正文抽取、XLSX 正文抽取、图片 WebP 预览、PDF 首页 WebP 预览、Office 经 LibreOffice headless 转 PDF 的基础链路、preview worker 任务超时/限速、结构化失败日志、预览失败指标和资源配额部署说明已完成。上传/下载链路已补首组真实 MinIO 集成测试；下一步推进 MinIO multipart 私有方法稳定性替换评估、异常恢复和升级兼容测试、高密级下载代理、多维配额和维护任务调度告警；搜索/预览侧继续补充真实 LibreOffice 环境联调和 OCR 等复杂格式抽取工具适配。

### 阻塞与风险

- MinIO Python SDK 的 multipart create/complete/abort 在当前适配中需要调用 `_create_multipart_upload`、`_complete_multipart_upload`、`_abort_multipart_upload` 私有方法，已限定在 `infrastructure` 适配层；这不是业务层随意自研，但 SDK 升级稳定性不够企业级，后续应评估公开 API、稳定开源 S3 兼容客户端或标准 HTTP/SigV4 实现，并用真实对象存储集成测试锁定行为。
- 当前 Redis 限流仍是固定窗口策略，适用于上传初始化、分片签名和下载预签名的基础保护；若后续需要滑动窗口、令牌桶、多层级动态规则或管理端配置，应切换成熟限流库。
- 当前空间、文件树、上传、下载、空间成员管理和节点 ACL 管理接口已接入权限检查；文件列表已返回当前页子节点的批量权限评估结果；权限变更 outbox 事件已接入 Redis 缓存失效 worker；org 部门/用户组 ACL 主体和搜索 ACL 重建事件已接入。
- 搜索当前已完成 token builder、outbox 事件、文件索引文档构建、`search.index_requested` 写入 OpenSearch 入口、`search.acl_rebuild_requested` 的保守范围重建、`search.extract_requested` UTF-8 文本类、PDF 可复制正文、DOCX 段落/表格、PPTX 文本框/表格和 XLSX 单元格抽取入口、`/api/v1/search` 查询过滤、签名 cursor 分页、HTML 编码 highlight，以及上传完成、重命名、移动、删除、恢复和彻底删除后的索引同步；PDF 抽取当前依赖 `pypdf`，只覆盖可复制文本，不覆盖扫描件 OCR；DOCX/PPTX/XLSX 抽取分别依赖 `python-docx`、`python-pptx`、`openpyxl`，只覆盖 OOXML 格式，不覆盖旧 `.doc/.ppt/.xls`；OCR 和大文件解析需后续使用成熟开源工具接入。
- 预览当前支持图片、PDF 首页和 Office 文档生成 WebP 产物；PDF 依赖 Poppler `pdftoppm`，Office 依赖 LibreOffice `soffice`。当时本机已发现 `pdftoppm` 可用但 LibreOffice/soffice 不可用，因此只能通过 fake converter 和缺失工具测试验证 Office 代码路径；原 systemd/Kubernetes 资源说明已在 2026-07-14 改为 Windows Docker Compose 下的 Preview Worker 镜像与资源限制，真实 Office 转码需在最终容器中联调。
- 部门/用户组 ACL 变更当前无法精确枚举所有受影响用户缓存，已采用通配模式保守失效租户内节点权限缓存；若后续权限缓存读路径启用并出现大租户性能压力，应补充 subject membership 反向索引或异步展开任务。
- 当前 Redis 权限缓存已完成失效 worker，但权限判断读路径尚未启用 Redis 缓存；接入读缓存时必须保持数据库为事实来源，高危动作继续二次查库。
- 当前节点 ACL 路径加载采用逐级父节点查询并限制最大深度 64，适合一期目录深度可控场景；若后续目录深度、列表批量权限展示或搜索过滤压力升高，应引入递归 CTE、closure table 或批量权限评估缓存。
- 过期上传清理已覆盖数据库会话终态、multipart abort 和 `uploads/...` 临时对象删除；对象复制成功但数据库最终化失败后的 `objects/...` 孤儿最终对象扫描已由 `file.cleanup_orphaned_objects` 兜底，真实 MinIO 集成测试已覆盖 list/delete 主路径，后续仍需生产调度告警、异常恢复和运行指标验证。
- 当前容量实现已覆盖空间维度的文件版本创建、彻底删除释放、空间容量校准和 DB 驱动的 blob/object 清理；用户维度、租户维度和基于策略的配额仍需后续补齐。
- `file.cleanup_unreferenced_blobs` 只清理仍有 DB blob 元数据且已无版本引用的最终对象；对象存储里没有 DB 元数据的孤儿最终对象由 `file.cleanup_orphaned_objects` 反向扫描，当前已补真实 MinIO 主路径集成测试，后续还需补异常恢复和调度告警验证。
- 当前维护任务仍偏“可手动跑/worker 可消费”的阶段，尚未系统接入定时调度配置、失败告警、清理指标和治理看板。
- 并发下同 hash 首次上传主要依赖唯一约束和补偿路径，已有基础处理，但仍需补更细的竞争测试、对象归档幂等检查和失败恢复路径。
- 真实对象存储集成测试已覆盖 MinIO multipart、copy、delete、list、presign、hash 校验和孤儿最终对象扫描主路径；后续仍需补异常恢复、SDK 升级兼容、并发竞争和失败补偿场景。
- 当前基础限流覆盖上传初始化、分片签名、下载预签名、搜索查询、外链访问和外链下载；登录失败和管理接口限流仍需随对应模块接入。
- 分享模块当前已开放创建/详情/撤销 API、带限流的外链访问入口和外链下载入口；内部下载和外链下载现阶段仍以短期预签名直连为主，高密级文件需要后端代理、HTTP Range、增强审计、水印或 DLP 策略。

### 下一步

- 优先推进 MinIO multipart 私有方法替换评估或更稳定的标准 HTTP/SigV4 窄适配，并补异常恢复、SDK 升级兼容和同 hash 首次上传并发竞争测试；随后推进高密级下载代理、多维配额和维护任务调度告警。

### 验证

- 已运行 `DRIVE_RUN_MINIO_TESTS=1 ... uv run pytest tests/test_storage_minio_integration.py -q`，结果 `3 passed`。
- 已运行 `uv run ruff format .`，结果 `182 files left unchanged`。
- 已运行 `uv run ruff check .`，结果 `All checks passed!`。
- 已运行 `uv run ruff format --check .`，结果 `182 files already formatted`。
- 已运行 `uv run mypy app`，结果 `Success: no issues found in 139 source files`。
- 已运行 `uv run pytest`，结果 `141 passed, 3 skipped`；3 个 skipped 为未显式启用的 MinIO 集成测试。
- 已运行 `uv run alembic upgrade head --sql`，成功生成升级 SQL。
- 已运行 `git diff --check`，仅有 Windows 换行提示，无空白错误。

### 涉及文件

- `backend/app/modules/upload/cleanup.py`
- `backend/app/modules/upload/repository.py`
- `backend/app/modules/upload/audit.py`
- `backend/app/modules/upload/lifecycle.py`
- `backend/app/modules/upload/storage_keys.py`
- `backend/app/workers/upload_tasks.py`
- `backend/app/infrastructure/queue/celery_app.py`
- `backend/app/infrastructure/rate_limit/base.py`
- `backend/app/infrastructure/rate_limit/redis.py`
- `backend/app/infrastructure/rate_limit/testing.py`
- `backend/app/infrastructure/storage/s3.py`
- `backend/app/infrastructure/storage/base.py`
- `backend/app/infrastructure/storage/testing.py`
- `backend/app/api/deps.py`
- `backend/app/core/config.py`
- `backend/app/core/pagination.py`
- `backend/app/modules/audit/dispatcher.py`
- `backend/app/modules/file/validators.py`
- `backend/app/modules/upload/hash.py`
- `backend/app/modules/upload/router.py`
- `backend/app/modules/file/router.py`
- `backend/app/modules/file/blob_cleanup.py`
- `backend/app/modules/file/repository.py`
- `backend/app/modules/file/models.py`
- `backend/app/modules/file/schemas.py`
- `backend/app/modules/file/acl.py`
- `backend/app/modules/file/acl_audit.py`
- `backend/app/modules/file/acl_router.py`
- `backend/app/modules/file/download.py`
- `backend/app/modules/file/router.py`
- `backend/app/modules/file/service.py`
- `backend/app/modules/file/tree.py`
- `backend/app/modules/org/models.py`
- `backend/app/modules/org/repository.py`
- `backend/app/modules/org/service.py`
- `backend/app/modules/quota/repository.py`
- `backend/app/modules/quota/service.py`
- `backend/app/modules/quota/reconciliation.py`
- `backend/app/modules/permission/constants.py`
- `backend/app/modules/permission/actions.py`
- `backend/app/modules/permission/cache.py`
- `backend/app/modules/permission/models.py`
- `backend/app/modules/permission/events.py`
- `backend/app/modules/permission/repository.py`
- `backend/app/modules/permission/schemas.py`
- `backend/app/modules/permission/service.py`
- `backend/app/modules/permission/validators.py`
- `backend/app/modules/preview/events.py`
- `backend/app/modules/preview/converters.py`
- `backend/app/modules/preview/models.py`
- `backend/app/modules/preview/renderer.py`
- `backend/app/modules/preview/repository.py`
- `backend/app/modules/preview/schemas.py`
- `backend/app/modules/preview/service.py`
- `backend/app/modules/preview/storage_keys.py`
- `backend/app/infrastructure/preview/libreoffice.py`
- `backend/app/infrastructure/preview/poppler.py`
- `backend/app/infrastructure/queue/celery_app.py`
- `backend/app/core/logging.py`
- `backend/app/core/metrics.py`
- `backend/app/main.py`
- `backend/app/modules/search/acl.py`
- `backend/app/modules/search/cursor.py`
- `backend/app/modules/search/events.py`
- `backend/app/modules/search/extractor.py`
- `backend/app/modules/search/extractors.py`
- `backend/app/modules/search/router.py`
- `backend/app/modules/search/schemas.py`
- `backend/app/modules/search/service.py`
- `backend/app/modules/search/indexer.py`
- `backend/app/modules/search/repository.py`
- `backend/app/modules/share/constants.py`
- `backend/app/modules/share/models.py`
- `backend/app/modules/share/repository.py`
- `backend/app/modules/share/external_access.py`
- `backend/app/modules/share/external_download.py`
- `backend/app/modules/share/router.py`
- `backend/app/modules/share/schemas.py`
- `backend/app/modules/share/service.py`
- `backend/migrations/versions/20260701_0011_share_base.py`
- `backend/migrations/versions/20260701_0012_preview_base.py`
- `backend/app/infrastructure/search/base.py`
- `backend/app/infrastructure/search/opensearch.py`
- `backend/app/infrastructure/search/testing.py`
- `backend/app/infrastructure/storage/testing.py`
- `backend/migrations/versions/20260701_0010_file_version_search_state.py`
- `backend/app/modules/space/members.py`
- `backend/app/modules/space/router.py`
- `backend/app/modules/space/member_audit.py`
- `backend/app/modules/upload/service.py`
- `backend/app/modules/upload/lifecycle.py`
- `backend/app/db/models.py`
- `backend/app/api/v1/router.py`
- `backend/app/modules/audit/dispatcher.py`
- `backend/app/modules/audit/repository.py`
- `backend/app/workers/audit_tasks.py`
- `backend/app/workers/permission_tasks.py`
- `backend/app/workers/preview_tasks.py`
- `backend/app/workers/quota_tasks.py`
- `backend/app/workers/search_tasks.py`
- `backend/app/workers/file_tasks.py`
- `backend/app/modules/auth/repository.py`
- `backend/app/modules/auth/router.py`
- `backend/app/modules/auth/service.py`
- `backend/app/modules/audit/service.py`
- `backend/app/modules/auth/models.py`
- `backend/app/modules/auth/schemas.py`
- `backend/app/core/security.py`
- `backend/migrations/versions/20260630_0001_auth_base.py`
- `backend/migrations/versions/20260701_0006_permission_base.py`
- `backend/migrations/versions/20260701_0007_acl_entries.py`
- `backend/migrations/versions/20260701_0008_org_base.py`
- `backend/migrations/versions/20260701_0009_acl_subjects.py`
- `backend/tests/test_upload_cleanup.py`
- `backend/tests/test_rate_limit.py`
- `backend/tests/test_file_operations.py`
- `backend/tests/test_preview.py`
- `backend/tests/test_preview_office.py`
- `backend/tests/test_preview_libreoffice.py`
- `backend/tests/test_preview_worker.py`
- `backend/tests/test_app.py`
- `backend/tests/test_auth.py`
- `backend/tests/test_space_file.py`
- `backend/tests/test_space_members.py`
- `backend/tests/test_node_acl.py`
- `backend/tests/test_org_repository.py`
- `backend/tests/test_permission_cache.py`
- `backend/tests/test_search_acl.py`
- `backend/tests/test_search_query.py`
- `backend/tests/test_share_router.py`
- `backend/tests/test_share_service.py`
- `backend/tests/test_quota_reconciliation.py`
- `backend/tests/test_blob_cleanup.py`
- `backend/tests/test_storage_minio_integration.py`
- `backend/tests/helpers.py`
- `backend/.env.example`
- `backend/pyproject.toml`
- `backend/uv.lock`
- `.github/workflows/backend-ci.yml`
- `README.md`
- `backend/README.md`
- `AGENT.md`
- `PROJECT_PLAN.md`
- `docs/code-audit-2026-07-01.md`
- `docs/deployment-preview-worker.md`
- `企业网盘开发者技术计划书.md`

### 验证

- 已运行 `uv run ruff format app/infrastructure/search/base.py app/infrastructure/search/opensearch.py app/infrastructure/search/testing.py app/modules/search/cursor.py app/modules/search/router.py app/modules/search/schemas.py app/modules/search/service.py tests/test_search_query.py`，格式化搜索分页和高亮相关文件。
- 已运行 `uv run ruff check app/infrastructure/search/base.py app/infrastructure/search/opensearch.py app/infrastructure/search/testing.py app/modules/search/cursor.py app/modules/search/router.py app/modules/search/schemas.py app/modules/search/service.py tests/test_search_query.py`，结果为 All checks passed。
- 已运行 `uv run mypy app`，结果为 no issues found in 114 source files。
- 已运行 `uv run pytest tests/test_search_query.py -q`，结果为 4 passed。
- 已运行 `uv run ruff format app/modules/search/extractor.py app/workers/search_tasks.py tests/test_search_acl.py`，格式化搜索文本抽取相关文件。
- 已运行 `uv run pytest tests/test_search_acl.py tests/test_search_query.py -q`，结果为 18 passed。
- 已运行 `uv run ruff check app/modules/search/extractor.py app/workers/search_tasks.py tests/test_search_acl.py`，结果为 All checks passed。
- 已运行 `uv run mypy app`，结果为 no issues found in 115 source files。
- 已运行 `uv add "pypdf>=5.0"`，新增并锁定 `pypdf==6.14.2`。
- 已运行 `uv run python -` 通过 `importlib.metadata` 确认 `pypdf` 版本 `6.14.2`、许可证元数据 `BSD-3-Clause`、`Requires-Python >=3.9`。
- 已运行 `uv run pytest tests/test_search_acl.py -q`，结果为 18 passed，覆盖 PDF 抽取器、PDF 页数上限、`search.extract_requested` PDF 正文入库/入索引和抽取后正文超限跳过。
- 已运行 `uv add "python-docx>=1.2"`，新增并锁定 `python-docx==1.2.0` 和 `lxml==6.1.1`。
- 已运行 `uv run python -` 通过 `importlib.metadata` 确认 `python-docx` 版本 `1.2.0`、许可证元数据 `MIT`、`Requires-Python >=3.9`，以及 `lxml` 版本 `6.1.1`、许可证元数据 `BSD-3-Clause`、`Requires-Python >=3.8`。
- 已运行 `uv run pytest tests/test_search_acl.py -q`，结果为 21 passed，覆盖 DOCX 段落/表格抽取、`search.extract_requested` DOCX 正文入库/入索引和 DOCX zip 归档超限跳过。
- 已运行 `uv add "python-pptx>=1.0" "openpyxl>=3.1"`，新增并锁定 `python-pptx==1.0.2`、`openpyxl==3.1.5`、`xlsxwriter==3.2.9` 和 `et-xmlfile==2.0.0`。
- 已运行 `uv add --dev types-openpyxl`，为 `openpyxl` 补充 mypy 类型 stub，当前锁定 `types-openpyxl==3.1.5.20260518`。
- 已运行 `uv run python -` 通过 `importlib.metadata` 确认 `python-pptx` 版本 `1.0.2`、许可证元数据 `MIT`、`Requires-Python >=3.8`；`openpyxl` 版本 `3.1.5`、许可证元数据 `MIT`、`Requires-Python >=3.8`；`XlsxWriter` 版本 `3.2.9`、许可证元数据 `BSD-2-Clause`、`Requires-Python >=3.8`；`et_xmlfile` 版本 `2.0.0`、许可证元数据 `MIT`、`Requires-Python >=3.8`。
- 已运行 `uv run pytest tests/test_search_acl.py -q`，结果为 27 passed，覆盖 PPTX 文本框/表格抽取、XLSX 单元格抽取、`search.extract_requested` PPTX/XLSX 正文入库/入索引，以及 PPTX/XLSX zip 归档超限跳过。
- 已运行 `uv run ruff format app/modules/search/extractors.py tests/test_search_acl.py`，结果为 2 files left unchanged。
- 已运行 `uv run ruff check app/modules/search/extractors.py tests/test_search_acl.py`，结果为 All checks passed。
- 已运行 `uv run mypy app`，结果为 no issues found in 139 source files。
- 已运行 `uv run ruff format --check .`，结果为 146 files already formatted。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已再次运行 `uv run mypy app`，结果为 no issues found in 115 source files。
- 已运行 `uv run pytest -q`，结果为 93 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认 `20260701_0010_file_version_search_state.py` 会按“加 nullable 列、回填 pending、加 not null”的顺序生成 PostgreSQL SQL。
- 已运行 `uv run ruff format .`，结果为 181 files left unchanged。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run ruff format --check .`，结果为 181 files already formatted。
- 已运行 `uv run mypy app`，结果为 no issues found in 139 source files。
- 已运行 `uv run pytest`，结果为 136 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认新增 PDF/DOCX/PPTX/XLSX 搜索抽取依赖和代码不影响当前迁移链。
- 已运行 `git diff --check`，未发现空白错误。
- 本轮未启动 API、Worker 或 Docker Compose 服务。
- 已运行 `uv run pytest tests/test_share_service.py -q`，结果为 6 passed。
- 已运行 `uv run ruff format app/modules/share app/db/models.py migrations/versions/20260701_0011_share_base.py tests/test_share_service.py`，格式化分享模块基础实现。
- 已运行 `uv run ruff format --check .`，结果为 154 files already formatted。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run mypy app`，结果为 no issues found in 121 source files。
- 已运行 `uv run pytest -q`，结果通过，共 99 个测试点。
- 已运行 `uv run alembic upgrade head --sql`，确认新增分享迁移 `20260701_0011_share_base.py` 可生成 PostgreSQL SQL。
- 已运行 `uv run ruff format app/api/deps.py app/core/config.py app/modules/share tests/test_share_router.py`，格式化外链下载相关文件。
- 已运行 `uv run pytest tests/test_share_service.py tests/test_share_router.py -q`，结果为 14 passed。
- 已运行 `uv run mypy app/modules/share app/api/deps.py app/core/config.py`，结果为 Success。
- 已运行 `uv run ruff format --check .`，结果为 158 files already formatted。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run mypy app`，结果为 no issues found in 124 source files。
- 已运行 `uv run pytest -q`，结果为 107 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认当前迁移仍可生成 PostgreSQL SQL。
- 已运行 `git diff --check`，未发现空白错误；仅有 Windows 工作区 LF/CRLF 提示。
- 本轮未启动 API、Worker、Docker Compose 或其他常驻服务。
- 已运行 `uv run pytest tests/test_preview.py -q`，结果为 2 passed。
- 已运行 `uv run pytest tests/test_upload.py tests/test_search_acl.py tests/test_file_operations.py -q`，结果为 36 passed。
- 已运行 `uv run ruff format .`，格式化预览链路相关文件。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run ruff format --check .`，结果为 169 files already formatted。
- 已运行 `uv run mypy app`，结果为 no issues found in 133 source files。
- 已运行 `uv run pytest -q`，结果为 109 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认新增预览迁移 `20260701_0012_preview_base.py` 可生成 PostgreSQL SQL。
- 已运行 `git diff --check`，未发现空白错误；仅有 Windows 工作区 LF/CRLF 提示。
- 本轮未启动 API、Worker、Docker Compose 或其他常驻服务。
- 已运行 `uv run pytest tests/test_preview.py tests/test_preview_pdf.py tests/test_preview_poppler.py -q`，结果为 6 passed，覆盖图片、文本 unsupported、PDF fake converter、PDF renderer missing 和 Windows/Codex Poppler 包装器解析。
- 已运行 `uv run ruff format .`，结果为 175 files left unchanged。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run ruff format --check .`，结果为 175 files already formatted。
- 已运行 `uv run mypy app`，结果为 no issues found in 136 source files。
- 已运行 `uv run pytest`，结果为 113 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认 PDF 预览配置变更不影响当前迁移链。
- 已运行 `git diff --check`，未发现空白错误；仅有 Windows 工作区 LF/CRLF 提示。
- 已检查本机预览工具：`pdftoppm` 可用，适配器已解析到真实 `pdftoppm.exe` 并通过 `-v` smoke test；`libreoffice` / `soffice` 缺失，Office 预览接入时需安装 LibreOffice 或记录不可用原因。
- 本轮未启动 API、Worker、Docker Compose 或其他常驻服务，并已确认 `18080`、`15432`、`16379`、`19000`、`19001`、`19200`、`19600` 未监听。
- GitHub Actions `backend-ci` 在提交 `a9c8e73` 的 pytest 步骤失败，原因是 `test_resolve_executable_prefers_windows_poppler_exe` 为模拟 Windows 直接 monkeypatch `os.name='nt'`，导致 Linux CI 上 `pathlib` 尝试实例化 `WindowsPath` 并抛出 `NotImplementedError`。
- 已修复 Poppler 适配器测试边界：新增 `_is_windows()` 封装平台判断，测试改为 monkeypatch 模块内函数，不再改写全局 `os.name`。
- 已运行 `uv run pytest tests/test_preview_poppler.py -q`，结果为 2 passed。
- 已运行 `uv run ruff format .`，结果为 175 files left unchanged。
- 已运行 `uv run ruff format --check .`，结果为 175 files already formatted。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run mypy app`，结果为 no issues found in 136 source files。
- 已运行 `uv run pytest`，结果为 113 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认迁移链仍可生成 PostgreSQL SQL。
- 已运行 `git diff --check`，未发现空白错误；仅有 Windows 工作区 LF/CRLF 提示。
- 本轮未启动 API、Worker、Docker Compose 或其他常驻服务，并已确认项目常用端口未监听。
- 已运行 `uv run ruff format .`，结果为 178 files left unchanged。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run ruff format --check .`，结果为 178 files already formatted。
- 已运行 `uv run mypy app`，结果为 no issues found in 137 source files。
- 已运行 `uv run pytest`，结果为 118 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认 Office 预览配置和适配器变更不影响当前迁移链。
- 已运行 `git diff --check`，未发现空白错误；仅有 Windows 工作区 LF/CRLF 提示。
- 已检查本机预览工具：`pdftoppm` 可用；`soffice` / `libreoffice` 缺失，因此本轮 Office 预览通过 fake converter、缺失工具测试和扩展名校验覆盖，真实 LibreOffice 转码需在安装 LibreOffice 后联调。
- 本轮未启动 API、Worker、Docker Compose 或其他常驻服务，并已确认 `18080`、`15432`、`16379`、`19000`、`19001`、`19200`、`19600` 未监听。
- 已运行 `uv run ruff format .`，结果为 179 files left unchanged。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run ruff format --check .`，结果为 179 files already formatted。
- 已运行 `uv run mypy app`，结果为 no issues found in 137 source files。
- 已运行 `uv run pytest`，结果为 122 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认 preview worker 任务配置和日志变更不影响当前迁移链。
- 已运行 `git diff --check`，未发现空白错误；仅有 Windows 工作区 LF/CRLF 提示。
- 本轮未启动 API、Worker、Docker Compose 或其他常驻服务，并已确认 `18080`、`15432`、`16379`、`19000`、`19001`、`19200`、`19600` 未监听。
- 已运行 `uv run ruff format .`，结果为 180 files left unchanged。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run ruff format --check .`，结果为 180 files already formatted。
- 已运行 `uv run mypy app`，结果为 no issues found in 138 source files。
- 已运行 `uv run pytest tests/test_app.py tests/test_preview_worker.py -q`，结果为 9 passed。
- 已运行 `uv run pytest`，结果为 123 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认 metrics 入口和 Prometheus 依赖变更不影响当前迁移链。
- 已运行 `git diff --check`，未发现空白错误；仅有 Windows 工作区 LF/CRLF 提示。
- 本轮未启动 API、Worker、Docker Compose 或其他常驻服务，并已确认 `18080`、`15432`、`16379`、`19000`、`19001`、`19200`、`19600` 未监听。
- 已运行 `git diff --check`，未发现空白错误。
- 已运行 `uv run pytest tests/test_share_router.py -q`，结果为 3 passed。
- 已运行 `uv run ruff format --check .`，结果为 156 files already formatted。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run mypy app`，结果为 no issues found in 122 source files。
- 已运行 `uv run pytest -q`，结果通过，共 102 个测试点。
- 已运行 `uv run alembic upgrade head --sql`，确认分享 API 接入后迁移链仍可生成 PostgreSQL SQL。
- 已运行 `git diff --check`，未发现空白错误。
- 已运行 `uv run ruff format app/api/deps.py app/core/config.py app/modules/share tests/test_share_router.py`，格式化外链访问入口、限流和测试。
- 已运行 `uv run pytest tests/test_share_service.py tests/test_share_router.py -q`，结果为 12 passed。
- 已运行 `uv run mypy app/modules/auth/service.py app/modules/share`，结果为 no issues found in 9 source files。
- 已运行 `uv run ruff format --check .`，结果为 157 files already formatted。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run mypy app`，结果为 no issues found in 123 source files。
- 已运行 `uv run pytest -q`，结果通过，共 105 个测试点。
- 已运行 `uv run alembic upgrade head --sql`，确认外链访问入口接入后迁移链仍可生成 PostgreSQL SQL。
- 已运行 `git diff --check`，未发现空白错误。
- 本轮未启动 API、Worker 或 Docker Compose 服务。
- 已运行 `uv run ruff format --check .`，结果为 144 files already formatted。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已再次运行 `uv run mypy app`，结果为 no issues found in 114 source files。
- 已运行 `uv run pytest -q`，结果为 87 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认当前迁移仍可生成 PostgreSQL SQL。
- 已运行 `uv run pytest tests/test_upload_cleanup.py tests/test_upload.py`，结果为 12 passed。
- 已运行 `uv run ruff format .`。
- 已运行 `uv run ruff format --check .`，结果为 89 files already formatted。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run mypy app`，结果为 no issues found in 72 source files。
- 已运行 `uv run pytest`，结果为 41 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认当前迁移仍可生成 PostgreSQL SQL。
- 已确认启动前 `18080`、`15432`、`16379`、`19000`、`19001`、`19200`、`19600` 未监听。
- 已从 `backend` 目录启动 Docker Compose 依赖服务 `postgres`、`redis`、`minio`、`opensearch`。
- 已运行 `uv run alembic upgrade head`，真实 PostgreSQL migration 通过。
- 已运行 `uv run python -m scripts.seed_admin`，管理员 seed 通过。
- 已使用真实 PostgreSQL 和 MinIO 验证过期上传清理：创建 multipart 上传会话后强制过期，调用 `UploadCleanupService.expire_upload_sessions` 返回 `scanned=1`、`expired=1`、`aborted=1`、`deleted=1`、`storage_errors=0`；数据库会话状态为 `expired`，`upload.expired` 审计 actor_type 为 `system`，outbox 状态为 `pending`，MinIO 中对应 `uploads/...` 对象不存在。
- 验证完成后已关闭本次启动的 Docker Compose 服务，并确认 `18080`、`15432`、`16379`、`19000`、`19001`、`19200`、`19600` 不再监听。
- 已运行 `uv run pytest tests/test_rate_limit.py`，结果为 4 passed。
- 已运行 `uv run ruff format .`。
- 已运行 `uv run pytest tests/test_file_operations.py -q`，结果为 9 passed。
- 已运行 `uv run ruff format .`，格式化彻底删除容量释放相关文件。
- 已运行 `uv run ruff format --check .`，结果为 94 files already formatted。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run mypy app`，结果为 no issues found in 76 source files。
- 已运行 `uv run pytest`，结果为 48 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认当前迁移仍可生成 PostgreSQL SQL。
- 已暂停未完成的容量校准草稿并保存到 Git stash：`stash@{0}`，说明为 `paused quota reconciliation draft`。
- 本次规则更新为 Markdown 文档改动，已检查 `AGENT.md` 和 `PROJECT_PROGRESS.md` 写入内容。
- 已再次修正 `AGENT.md`，移除“云服务 SDK”优先项并补充“不要默认引入或直接依赖云厂商专有 SDK”的约束。
- 已运行 `uv run ruff format --check .`，结果为 94 files already formatted。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run mypy app`，结果为 no issues found in 76 source files。
- 已运行 `uv run pytest`，结果为 45 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认当前迁移仍可生成 PostgreSQL SQL。
- 已确认启动前 `18080`、`15432`、`16379`、`19000`、`19001`、`19200`、`19600` 未监听。
- 已从 `backend` 目录启动 Docker Compose `redis` 服务，使用真实 Redis 验证 `RedisFixedWindowRateLimiter`：同一 key 在 `limit=1` 窗口内第一次允许、第二次拒绝且 `retry_after_seconds > 0`。
- 已从 `backend` 目录启动 Docker Compose `postgres`、`redis`、`minio` 服务，运行真实 PostgreSQL migration 和管理员 seed 后，通过 ASGI + 真实 Redis + 真实 MinIO 验证上传初始化限流：环境变量设置 `DRIVE_UPLOAD_INIT_RATE_LIMIT_COUNT=1` 后，同一用户第一次 `POST /api/v1/uploads/init` 返回 201，第二次返回 429，错误码为 `RATE_LIMITED`，`details.action=upload.init`。
- 验证完成后已关闭本次启动的 Docker Compose 服务，并确认 `18080`、`15432`、`16379`、`19000`、`19001`、`19200`、`19600` 不再监听。
- 本轮认证、对象存储和限流审计整改未启动 API、Worker 或 Docker Compose 服务。
- 已运行 `uv run ruff format .`，结果为 94 files left unchanged。
- 已运行 `uv run ruff format --check .`，结果为 94 files already formatted。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run mypy app`，结果为 no issues found in 76 source files。
- 已运行 `uv run pytest`，结果为 49 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认初始迁移已生成 `auth_sessions` 表且当前迁移可生成 PostgreSQL SQL。
- 已运行 `git diff --check`，未发现空白错误。
- 将认证测试命名从 refresh 语义收束为 session rotate 语义后，已运行 `uv run pytest tests/test_auth.py tests/test_space_file.py -q`，结果为 13 passed。
- 已再次运行 `uv run ruff check .`，结果为 All checks passed。
- 已再次运行 `uv run pytest`，结果为 49 passed。
- 已再次运行 `git diff --check`，未发现空白错误。
- 恢复容量校准草稿后，已运行 `uv run pytest tests/test_quota_reconciliation.py -q`，结果为 4 passed。
- 已运行 `uv run ruff format .`，格式化容量校准相关文件。
- 已运行 `uv run ruff format --check .`，结果为 97 files already formatted。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run mypy app`，结果为 no issues found in 78 source files。
- 已运行 `uv run pytest`，结果为 53 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认当前迁移仍可生成 PostgreSQL SQL。
- 已运行 `git diff --check`，未发现空白错误。
- 本轮容量校准恢复未启动 API、Worker 或 Docker Compose 服务；已确认 `18080`、`15432`、`16379`、`19000`、`19001`、`19200`、`19600` 未监听。
- 本次重新恢复已掉出 `refs/stash` 的 `paused quota reconciliation draft`，确认有效实现已在当前代码中吸收，并继续修正容量校准 worker 的批量扫描边界。
- 已运行 `uv run pytest tests/test_quota_reconciliation.py -q`，结果为 4 passed，覆盖 `limit=1` 时 worker 通过 cursor 扫描同租户多个空间。
- 已运行 `uv run ruff format app/infrastructure/queue/celery_app.py app/modules/quota/repository.py app/modules/quota/reconciliation.py app/workers/quota_tasks.py tests/test_quota_reconciliation.py`，格式化本轮涉及的 Python 文件。
- 已运行 `uv run ruff format --check .`，结果为 118 files already formatted。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run mypy app`，结果为 no issues found in 94 source files。
- 已运行 `uv run pytest`，结果为 65 passed。
- 已运行 `git diff --check`，未发现空白错误。
- 本轮没有数据库结构变更，未新增 Alembic migration；未启动 API、Worker 或 Docker Compose 服务。
- 已运行 `uv run pytest tests/test_permission_cache.py tests/test_outbox_dispatcher.py -q`，结果为 7 passed，覆盖 Redis 权限缓存失效范围、`permission.changed` worker 消费和审计 dispatcher 跳过权限事件。
- 已运行 `uv run ruff format app/modules/audit/repository.py app/modules/audit/dispatcher.py app/workers/audit_tasks.py app/modules/permission/cache.py app/workers/permission_tasks.py app/infrastructure/queue/celery_app.py tests/test_permission_cache.py`，格式化本轮涉及的 Python 文件。
- 已运行 `uv run ruff format --check .`，结果为 121 files already formatted。
- 已运行 `uv run ruff check .`，结果为 All checks passed；本机 `.ruff_cache` 写入出现 Windows 权限警告，但检查已完成。
- 已运行 `uv run mypy app`，结果为 no issues found in 96 source files。
- 已运行 `uv run pytest`，结果为 68 passed。
- 已运行 `git diff --check`，未发现空白错误。
- 本轮没有数据库结构变更，未新增 Alembic migration；未启动 API、Worker 或 Docker Compose 服务。
- 已运行 `uv run pytest tests/test_org_repository.py -q`，结果为 2 passed，覆盖部门/用户组成员关系、活跃主体过滤和唯一约束。
- 已运行 `uv run ruff format app/modules/org tests/test_org_repository.py app/db/models.py migrations/versions/20260701_0008_org_base.py`，格式化本轮涉及的 Python 文件和迁移文件。
- 已运行 `uv run ruff format --check .`，结果为 126 files already formatted。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run mypy app`，结果为 no issues found in 99 source files。
- 已运行 `uv run pytest`，结果为 70 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认 `departments`、`department_members`、`user_groups`、`user_group_members` 表、索引和约束可生成 PostgreSQL SQL。
- 已运行 `git diff --check`，未发现空白错误。
- 本轮未启动 API、Worker 或 Docker Compose 服务。
- 已重新定位掉出 `refs/stash` 的 `paused quota reconciliation draft`，确认草稿有效实现已在当前代码中吸收，并继续按 AGENT 规则修正容量校准修复幂等和 worker 返回体量。
- 已运行 `uv run pytest tests/test_quota_reconciliation.py -q`，结果为 4 passed，覆盖重复修复不追加账本差额和 worker 明细截断。
- 已运行 `uv run ruff format app/modules/quota/repository.py app/modules/quota/reconciliation.py app/workers/quota_tasks.py tests/test_quota_reconciliation.py`，格式化本轮涉及的 Python 文件。
- 本次复核 `paused quota reconciliation draft` 后，已运行 `uv run ruff format app/modules/quota/reconciliation.py tests/test_quota_reconciliation.py`，格式化容量校准修复统计相关文件。
- 已运行 `uv run ruff format --check app/modules/quota/reconciliation.py tests/test_quota_reconciliation.py`，结果为 2 files already formatted。
- 已运行 `uv run ruff check app/modules/quota/reconciliation.py tests/test_quota_reconciliation.py`，结果为 All checks passed。
- 已运行 `uv run mypy app`，结果为 no issues found in 115 source files。
- 已运行 `uv run pytest tests/test_quota_reconciliation.py -q`，结果为 5 passed。
- 已运行 `uv run ruff format --check .`，结果为 126 files already formatted。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run mypy app`，结果为 no issues found in 99 source files。
- 已运行 `uv run pytest`，结果为 70 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认当前迁移仍可生成 PostgreSQL SQL。
- 本轮未启动 API、Worker 或 Docker Compose 服务。
- 已运行 `uv run pytest tests/test_node_acl.py tests/test_permission_cache.py tests/test_org_repository.py -q`，结果为 9 passed，覆盖部门 allow、用户组 deny、组织主体权限缓存保守失效和 org repository 行为。
- 已运行 `uv run alembic upgrade head --sql`，确认新增 `20260701_0009_acl_subjects.py` 可生成 ACL 主体 CHECK 约束更新 SQL。
- 已运行 `uv run ruff format app/modules/permission app/modules/file app/modules/org app/modules/upload migrations/versions/20260701_0009_acl_subjects.py tests/test_node_acl.py tests/test_permission_cache.py`，格式化本轮涉及的 Python 文件和迁移文件。
- 已运行 `uv run ruff format --check .`，结果为 128 files already formatted。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run mypy app`，结果为 no issues found in 100 source files。
- 已运行 `uv run pytest`，结果为 71 passed。
- 本轮未启动 API、Worker 或 Docker Compose 服务。
- 已运行 `uv run pytest tests/test_search_acl.py tests/test_permission_cache.py tests/test_node_acl.py tests/test_space_members.py tests/test_quota_reconciliation.py -q`，结果为 19 passed，覆盖搜索 ACL token 构建、search outbox 独立消费、权限变更写入搜索重建事件、权限缓存、节点/空间 ACL 既有行为和容量校准复原状态。
- 已运行 `uv run pytest tests/test_search_acl.py tests/test_upload.py tests/test_permission_cache.py -q`，结果为 21 passed，覆盖 `search.index_requested` 写入、文件索引文档构建、search worker 消费索引事件、上传既有行为和权限缓存事件边界。
- 已运行 `uv run pytest tests/test_search_acl.py tests/test_permission_cache.py tests/test_node_acl.py tests/test_space_members.py -q`，结果为 18 passed，覆盖 `search.acl_rebuild_requested` 消费、ACL token 范围重建、权限缓存、节点 ACL 和空间成员既有行为。
- 已运行 `uv run ruff format app/modules/search app/workers/search_tasks.py app/modules/permission/events.py app/infrastructure/queue/celery_app.py tests/test_search_acl.py`，格式化本轮涉及的 Python 文件。
- 已运行 `uv run ruff format --check .`，结果为 139 files already formatted。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run mypy app`，结果为 no issues found in 110 source files。
- 已运行 `uv run pytest`，结果为 79 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认当前迁移链仍可生成 PostgreSQL SQL。
- 本轮未启动 API、Worker 或 Docker Compose 服务。
- 已运行 `uv run pytest tests/test_node_acl.py tests/test_space_file.py -q`，结果为 10 passed，覆盖文件列表批量权限字段和节点 ACL 继承 deny 行为。
- 已运行 `uv run ruff format app/modules/permission/service.py app/modules/file/service.py app/modules/file/schemas.py tests/test_node_acl.py`，格式化本轮涉及的 Python 文件。
- 已运行 `uv run ruff format --check .`，结果为 118 files already formatted。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run mypy app`，结果为 no issues found in 94 source files。
- 已运行 `uv run pytest`，结果为 65 passed。
- 已运行 `git diff --check`，未发现空白错误。
- 本轮没有数据库结构变更，未新增 Alembic migration；未启动 API、Worker 或 Docker Compose 服务。
- 已运行 `uv run ruff format .`，格式化 blob 清理相关文件。
- 已运行 `uv run pytest tests/test_blob_cleanup.py`，结果为 5 passed。
- 已运行 `uv run pytest tests/test_upload.py tests/test_file_operations.py`，结果为 19 passed。
- 已运行 `uv run ruff format .`，结果为 105 files left unchanged。
- 已运行 `uv run pytest tests/test_space_file.py`，结果为 7 passed。
- 已运行 `uv run ruff format --check .`，结果为 105 files already formatted。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run mypy app`，结果为 no issues found in 84 source files。
- 已运行 `uv run pytest`，结果为 58 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认 `space_members` 表、唯一索引和角色 CHECK 约束可生成 PostgreSQL SQL。
- 已运行 `git diff --check`，未发现空白错误。
- 本轮空间成员基础表实现未启动 API、Worker 或 Docker Compose 服务。
- 已运行 `uv run ruff format .`，结果为 107 files left unchanged。
- 已运行 `uv run pytest tests/test_space_file.py tests/test_download.py tests/test_upload.py`，结果为 21 passed。
- 已运行 `uv run ruff format --check .`，结果为 107 files already formatted。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run mypy app`，结果为 no issues found in 86 source files。
- 已运行 `uv run pytest`，结果为 59 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认当前权限迁移链仍可生成 PostgreSQL SQL。
- 已运行 `git diff --check`，未发现空白错误。
- 本轮空间级 PermissionService 接入未启动 API、Worker 或 Docker Compose 服务。
- 已运行 `uv run pytest tests/test_space_members.py`，结果为 3 passed。
- 已运行 `uv run ruff format .`，格式化空间成员管理测试文件。
- 已运行 `uv run ruff format --check .`，结果为 110 files already formatted。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run mypy app`，结果为 no issues found in 88 source files。
- 已运行 `uv run pytest`，结果为 62 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认当前迁移链仍可生成 PostgreSQL SQL。
- 已运行 `git diff --check`，未发现空白错误。
- 本轮空间成员管理 API 实现未启动 API、Worker 或 Docker Compose 服务。
- 已运行 `uv run pytest tests/test_node_acl.py`，结果为 3 passed。
- 已运行 `uv run ruff format --check .`，结果为 118 files already formatted。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run mypy app`，结果为 no issues found in 94 source files。
- 已运行 `uv run pytest`，结果为 65 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认 `acl_entries` 表、唯一索引、CHECK 约束和 JSONB 动作集合可生成 PostgreSQL SQL。
- 已运行 `git diff --check`，未发现空白错误。
- 本轮节点 ACL 基础闭环实现未启动 API、Worker 或 Docker Compose 服务。
- 已运行 `uv run pytest tests/test_space_members.py tests/test_node_acl.py`，结果为 6 passed。
- 已运行 `uv run ruff format --check .`，结果为 118 files already formatted。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run mypy app`，结果为 no issues found in 94 source files。
- 已运行 `uv run pytest`，结果为 65 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认当前迁移链仍可生成 PostgreSQL SQL。
- 已运行 `git diff --check`，未发现空白错误。
- 本轮 `permission.changed` 事件写入实现未启动 API、Worker 或 Docker Compose 服务。
- 已运行 `uv run ruff format --check .`，结果为 100 files already formatted。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run mypy app`，结果为 no issues found in 80 source files。
- 已运行 `uv run pytest`，结果为 58 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认 `file_blobs.status` 和 `idx_file_blobs_cleanup` 可生成 PostgreSQL SQL。
- 已运行 `git diff --check`，未发现空白错误。
- 本轮 blob/object 清理实现未启动 API、Worker 或 Docker Compose 服务。

## 2026-06-30

### 已完成

- 建立项目协作约束 `AGENT.md`。
- 明确生产部署时 Nginx 使用宿主机安装和管理，不放入 Docker。
- 建立项目 README、执行版项目计划和 Git 忽略规则。
- 创建 GitHub 公开仓库 `ChaceQC/enterprise-drive` 并推送初始提交。
- 创建日常开发分支 `dev`。
- 建立 `backend` 后端工程底座：uv 项目、FastAPI 应用入口、配置加载、结构化日志、`X-Request-ID` 中间件、统一错误响应、健康检查和 `/api/v1/ping`。
- 补充 Alembic 基础目录、SQLAlchemy 基类、本地依赖 Docker Compose、后端 README 和 GitHub Actions 后端 CI。
- 根据协作约束补充“缺少必要工具或依赖时自行安装或补齐”的规则。
- 补充 `tenants`、`users`、`refresh_tokens` SQLAlchemy 模型和 Alembic 初始迁移。
- 实现本地账号登录、JWT access token、refresh token 服务端哈希存储和 refresh token family 轮换。
- 实现旧 refresh token 复用检测，复用时吊销整个 token family。
- 实现 `/api/v1/auth/login`、`/api/v1/auth/refresh`、`/api/v1/auth/me`。
- 补充管理员 seed 脚本 `scripts/seed_admin.py`。
- 补充认证服务和认证 API 测试。
- 补充 `audit_logs`、`outbox_events` SQLAlchemy 模型和 Alembic 迁移。
- 实现审计写入服务，事务内同步写入 audit log 和 outbox event。
- 在登录成功、登录失败、刷新令牌成功、刷新令牌过期、用户失效和 refresh token 复用检测中写入认证审计事件。
- 补充认证审计和 outbox 测试。
- 补充 Celery app 基础配置和 `audit.dispatch_outbox` 任务。
- 实现 outbox dispatcher，支持 pending/failed 到期事件领取、发送成功标记、失败指数退避、超过最大重试进入 dead。
- 补充 outbox dispatcher 状态流转测试。
- 补充 `spaces`、`nodes`、`file_blobs`、`file_versions` SQLAlchemy 模型和 Alembic 迁移。
- 为 `nodes` 增加普通同目录同名唯一索引和空间根目录唯一索引，避免 PostgreSQL 中 `parent_id = null` 导致根节点唯一性失效。
- 实现签名 cursor pagination 工具。
- 实现 `/api/v1/spaces` 空间创建与列表接口，创建空间时同步创建根目录节点。
- 实现 `/api/v1/files/folders` 文件夹创建接口和 `/api/v1/files` 目录子节点列表接口。
- 文件夹名称执行 Unicode NFC 归一化，禁止路径分隔符、NUL、控制字符和路径穿越片段。
- 空间创建和文件夹创建写入审计日志与 outbox event。
- 补充空间和文件树 API 测试，覆盖创建空间、重复空间标识、创建文件夹、重复文件夹名、非法文件夹名和非拥有者访问边界。
- 同步更新 README、后端 README、执行计划和完整技术计划书中的空间/文件树 API、索引与当前阶段说明。
- 实现文件树节点重命名、移动、删除到回收站和恢复接口。
- 重命名、移动、删除和恢复均写入审计日志与 outbox event。
- 禁止根目录重命名、移动和删除，禁止目录移动到自身或自身子目录。
- 删除目录时同步标记当前子树进入回收站；恢复目录时仅恢复同一批删除的子树，避免误恢复更早单独删除的节点。
- 将文件树服务拆分为 `audit`、`tree`、`validators` 辅助模块，避免 `FileService` 职责膨胀。
- 将测试公共夹具抽到 `tests/helpers.py`，并拆分空间/基础文件树测试与文件操作测试。
- 补充 S3/MinIO 对象存储适配器，业务层通过 `StorageAdapter` 协议隔离 boto3 SDK，并用 `asyncio.to_thread` 避免阻塞 async endpoint。
- 补充 `upload_sessions`、`upload_parts` SQLAlchemy 模型和 Alembic 迁移。
- 补充上传相关配置：S3 access key、region、上传会话 TTL、分片大小和分片预签名有效期。
- 实现 `/api/v1/uploads/init` 上传初始化接口，未命中秒传时创建 provider multipart upload 和数据库上传会话。
- 实现 `/api/v1/uploads/{session_id}` 上传状态查询接口。
- 实现 `/api/v1/uploads/{session_id}/parts/{part_no}/presign` 分片上传预签名接口，首次签名时将会话推进为 `uploading`。
- 实现秒传分支：命中同租户、同 hash、同大小 blob 时直接创建文件节点和首个版本，更新 `node.current_version_id` 并递增 `file_blobs.ref_count`。
- 上传初始化和秒传均写入审计日志与 outbox event。
- 测试客户端默认覆盖上传存储依赖为 `InMemoryStorageAdapter`，避免单元测试依赖真实对象存储。
- 同步更新 README、后端 README、执行计划和完整技术计划书中的上传接口、环境变量、当前限制和下一步说明。
- 扩展 `StorageAdapter`，补充 multipart complete 能力；S3 适配器在合并后通过 `head_object` 获取对象大小，测试适配器记录 completed/aborted 状态。
- 实现 `/api/v1/uploads/{session_id}/complete`，完成 multipart 上传后记录分片、写入 `file_blobs`、`nodes`、`file_versions`，更新 `upload_sessions.completed_*`，并支持已完成会话幂等返回同一结果。
- 实现 `/api/v1/uploads/{session_id}/abort`，未完成会话可标记为 `aborted` 并取消对象存储 multipart upload，重复 abort 幂等返回。
- complete、abort 和失败分支均写入审计日志与 outbox event。
- 补充上传 complete/abort 测试，覆盖完整上传、幂等 complete、缺片拒绝和取消后的终态限制。
- 抽出共享 `get_storage_adapter` 依赖，上传和下载模块统一通过 `StorageAdapter` 协议访问对象存储。
- 扩展 `StorageAdapter`，补充 `presign_download` 能力；S3/MinIO 适配器使用 `get_object` 生成短期下载 URL，并通过 `ResponseContentDisposition` 处理中文文件名。
- 实现 `GET /api/v1/files/{node_id}/download`，基于 `nodes.current_version_id` 查找当前版本和 blob，返回下载 URL、过期时间、文件名、版本、大小和 MIME。
- 下载成功写入 `file.downloaded` 审计日志与 outbox event；目录下载、非空间拥有者下载、节点缺失和版本缺失等拒绝分支也写入 `result=denied` 审计。
- 补充下载接口测试，覆盖成功下载审计、目录拒绝审计和临时空间拥有者边界。
- 同步更新 README、后端 README、执行计划和完整技术计划书中的下载接口、环境变量、当前限制和下一步说明。
- 补充 `quota_accounts` 和 `quota_ledger` SQLAlchemy 模型与 Alembic 迁移。
- 新增 `quota` 模块，封装空间容量账户创建、容量预检查、原子扣减和容量流水写入。
- 空间创建时同步初始化默认空间容量账户，默认配额由 `DRIVE_DEFAULT_SPACE_QUOTA_BYTES` 控制。
- 上传初始化会快速检查空间剩余容量；秒传和 multipart complete 创建文件版本时原子增加空间容量快照并写入 `quota_ledger`。
- 补充空间和上传测试，覆盖空间容量账户创建、秒传容量流水、multipart complete 容量流水和容量不足拒绝。
- 同步更新 README、后端 README、执行计划和完整技术计划书中的容量账本初版状态、环境变量和后续限制。
- 新增上传 hash 工具，仅允许 `sha256` 上传 hash 算法，并在初始化上传时统一规范化 hash。
- 扩展 `StorageAdapter`，补充已完成对象的服务端 hash 计算能力；S3/MinIO 适配器通过 `get_object` 流式计算 `sha256`，测试适配器按对象内容或分片大小模拟 hash。
- multipart complete 在对象存储合并和大小校验后，会服务端计算对象 `sha256` 并与初始化时的 `content_hash` 比对，匹配后才创建 `file_blobs`、`nodes`、`file_versions` 和 `quota_ledger`。
- hash 不匹配时上传会话标记为 `failed`，写入 `upload.failed` 审计事件，返回 `UPLOAD_HASH_MISMATCH`，不创建文件版本、blob 和容量流水。
- 同步更新 README、后端 README、执行计划和完整技术计划书中的服务端 hash 校验、错误码、失败行为和后续限制。
- 扩展 `StorageAdapter`，补充对象复制和删除能力；S3/MinIO 适配器通过 `copy_object` 将完成后的临时上传对象归档到最终对象 key，通过 `delete_object` 清理临时对象。
- 新增上传对象 key 工具，统一生成 `uploads/{tenant_id}/{hash_hint}/{uuid}` 临时 key 和 `objects/{tenant_id}/{hash_prefix}/{content_hash}` 最终内容 key。
- multipart complete 在大小和 hash 校验通过后，若同租户同 hash、同大小 blob 已存在则复用既有 blob 并清理本次临时对象；若不存在则先复制到最终内容 key，再写入 blob、文件版本、容量流水和完成审计。
- 下载预签名 URL 已改为使用 `file_blobs.storage_key` 中的最终内容 key，避免暴露临时上传 key。
- 同步更新 README、后端 README、执行计划和完整技术计划书中的最终对象 key 规整状态、临时对象清理行为和后续限制。

### 进行中

- Sprint 3 过期上传清理任务、上传/下载限流、容量释放和容量校准设计与实现。

### 阻塞与风险

- 当前空间和文件树接口暂以“当前租户 + 空间拥有者”作为访问边界，空间成员、目录 ACL、继承权限和拒绝优先策略尚未接入；该边界已在 README 和后端 README 标为临时实现，后续需要由权限模块替换。
- 当前目录删除和恢复为同步遍历当前子树，适合 Sprint 2 骨架和普通目录验证；大目录后续需要改为后台任务或引入 `deleted_root_id` 等冗余状态，避免长事务。
- `conflict_policy` 当前实现为 fail-only，同名冲突返回 `NODE_NAME_EXISTS`；`keep_both` 和 `replace` 后续按上传/版本策略补充。
- 当前上传下载接口已完成 init、status、part presign、complete、abort、download presign、空间容量账本初版、multipart complete 后服务端 `sha256` 校验和最终对象 key 规整；过期会话清理、上传/下载限流、容量释放和容量校准尚未接入。
- 当前上传和下载权限仍沿用“当前租户 + 空间拥有者”临时边界，后续需要由 Sprint 4 权限模块替换。
- 当前对象存储上传完成后，新 blob 已使用 `objects/{tenant_id}/{hash_prefix}/{content_hash}` 作为最终内容 key；对象复制成功但数据库最终化失败等孤儿对象场景仍需后续生命周期扫描和清理任务兜底。
- 当前容量初版仅覆盖空间维度和文件版本创建场景；用户/租户维度配额、删除释放容量、历史空间回填和定期校准任务仍需后续补齐。

### 下一步

- 实现过期上传清理任务：扫描过期的 `initiated`、`uploading`、`completing` 上传会话，调用对象存储 abort 或删除临时对象，将会话标记为 `expired` 并写入审计；随后补上传/下载限流、容量释放和容量校准。

### 涉及文件

- `backend/app/modules/file/download.py`
- `backend/app/modules/file/router.py`
- `backend/app/modules/file/repository.py`
- `backend/app/modules/file/schemas.py`
- `backend/app/infrastructure/storage/base.py`
- `backend/app/infrastructure/storage/s3.py`
- `backend/app/infrastructure/storage/testing.py`
- `backend/app/api/deps.py`
- `backend/app/modules/upload/router.py`
- `backend/app/modules/upload/service.py`
- `backend/app/modules/upload/lifecycle.py`
- `backend/app/modules/upload/hash.py`
- `backend/app/modules/upload/storage_keys.py`
- `backend/app/modules/quota/models.py`
- `backend/app/modules/quota/repository.py`
- `backend/app/modules/quota/service.py`
- `backend/migrations/versions/20260630_0005_quota_base.py`
- `backend/app/core/config.py`
- `backend/tests/test_download.py`
- `backend/tests/test_space_file.py`
- `backend/tests/test_upload.py`
- `backend/tests/helpers.py`
- `README.md`
- `backend/README.md`
- `PROJECT_PLAN.md`
- `企业网盘开发者技术计划书.md`

### 验证

- 已检查 GitHub CLI 登录状态。
- 已检查目标仓库名 `ChaceQC/enterprise-drive` 当前不存在。
- 已运行 `uv sync --all-extras --dev`。
- 已运行 `uv sync --frozen --all-extras --dev`。
- 已运行 `uv run ruff format --check .`。
- 已运行 `uv run ruff check .`。
- 已运行 `uv run mypy app`。
- 已运行 `uv run pytest`，结果为 14 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认认证、审计和 outbox 迁移可生成 PostgreSQL SQL。
- 已启动 Docker Desktop，并运行 `docker compose up -d postgres redis minio opensearch`。
- 已运行 `uv run alembic upgrade head`，真实 PostgreSQL migration 通过。
- 已运行 `uv run python -m scripts.seed_admin`，管理员 seed 通过。
- 已启动本地 API `uv run uvicorn app.main:app --host 127.0.0.1 --port 18080`。
- 已验证 `/healthz`、`/readyz`、`/api/v1/auth/login`、`/api/v1/auth/me`、`/api/v1/auth/refresh`。
- 验证完成后已关闭本次启动的 API 和 Docker Compose 服务，并确认 `18080`、`15432`、`16379`、`19000`、`19001`、`19200`、`19600` 不再监听。
- 已运行 `uv run ruff format .`，格式化本次新增 Python 文件。
- 已运行 `uv run ruff check .`。
- 已运行 `uv run mypy app`。
- 已运行 `uv run pytest`，结果为 20 passed。
- 已运行 `uv run pytest tests/test_space_file.py`，结果为 6 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认空间和文件树迁移可生成 PostgreSQL SQL。
- 已启动 Docker Compose 依赖服务 `postgres`、`redis`、`minio`、`opensearch` 并等待健康。
- 已运行 `uv run alembic upgrade head`，真实 PostgreSQL migration 升级到 `20260630_0003` 通过。
- 已运行 `uv run python -m scripts.seed_admin`，管理员 seed 通过。
- 已启动本地 API `uv run uvicorn app.main:app --host 127.0.0.1 --port 18080`。
- 已真实验证 `/api/v1/auth/login`、`POST /api/v1/spaces`、`POST /api/v1/files/folders`、`GET /api/v1/files`。
- 验证完成后已关闭本次启动的 API 和 Docker Compose 服务，并确认 `18080`、`15432`、`16379`、`19000`、`19001`、`19200`、`19600` 不再监听。
- 已运行 `uv run ruff format .`。
- 已运行 `uv run ruff check .`。
- 已运行 `uv run mypy app`。
- 已运行 `uv run pytest tests/test_space_file.py tests/test_file_operations.py`，结果为 12 passed。
- 已运行 `uv run pytest tests/test_upload.py`，结果为 3 passed。
- 已运行 `uv run ruff format .`，格式化上传接口相关文件。
- 已运行 `uv run ruff format --check .`。
- 已运行 `uv run ruff check .`。
- 已运行 `uv run mypy app`。
- 已再次运行 `uv run pytest tests/test_upload.py`，结果为 3 passed。
- 已运行 `uv sync --frozen --all-extras --dev`。
- 已运行 `uv run ruff format --check .`。
- 已运行 `uv run ruff check .`。
- 已运行 `uv run mypy app`。
- 已运行 `uv run pytest`，结果为 26 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认当前迁移可生成 PostgreSQL SQL。
- 已启动 Docker Compose 依赖服务 `postgres`、`redis`、`minio`、`opensearch` 并等待健康。
- 已运行 `uv run alembic upgrade head`，真实 PostgreSQL migration 通过。
- 已运行 `uv run python -m scripts.seed_admin`，管理员 seed 通过。
- 已启动本地 API `uv run uvicorn app.main:app --host 127.0.0.1 --port 18080`。
- 已真实验证 `/api/v1/auth/login`、`POST /api/v1/spaces`、`POST /api/v1/files/folders`、`PATCH /api/v1/files/{node_id}`、`POST /api/v1/files/{node_id}/move`、`DELETE /api/v1/files/{node_id}`、`POST /api/v1/files/{node_id}/restore`、`GET /api/v1/files`。
- 验证完成后已关闭本次启动的 API 和 Docker Compose 服务，并确认 `18080`、`15432`、`16379`、`19000`、`19001`、`19200`、`19600` 不再监听。
- 已运行 `uv sync --frozen --all-extras --dev`。
- 已运行 `uv run ruff format --check .`，结果为 72 files already formatted。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run mypy app`，结果为 no issues found in 62 source files。
- 已运行 `uv run pytest`，结果为 29 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认上传迁移 `20260630_0004` 可生成 PostgreSQL SQL。
- 已确认启动前 `18080`、`15432`、`16379`、`19000`、`19001`、`19200`、`19600` 未监听。
- 已启动 Docker Compose 依赖服务 `postgres`、`redis`、`minio`、`opensearch` 并等待健康。
- 已运行 `uv run alembic upgrade head`，真实 PostgreSQL migration 升级到 `20260630_0004` 通过。
- 已运行 `uv run python -m scripts.seed_admin`，管理员 seed 通过。
- 已启动本地 API `uv run uvicorn app.main:app --host 127.0.0.1 --port 18080`。
- 已真实验证 `/healthz`、`/api/v1/auth/login`、`POST /api/v1/spaces`、`POST /api/v1/uploads/init`、`GET /api/v1/uploads/{session_id}`、`POST /api/v1/uploads/{session_id}/parts/{part_no}/presign`；multipart 初始化返回 2 个分片，分片签名后状态由 `initiated` 变为 `uploading`，MinIO 预签名 URL 包含 upload id。
- 验证完成后已关闭本次启动的 API 和 Docker Compose 服务，并确认 `18080`、`15432`、`16379`、`19000`、`19001`、`19200`、`19600` 不再监听。
- 已运行 `uv run ruff format .`，格式化 lifecycle 和上传测试。
- 已运行 `uv run pytest tests/test_upload.py`，结果为 6 passed。
- 已运行 `uv run ruff format --check .`。
- 已运行 `uv run ruff check .`。
- 已运行 `uv run mypy app`，结果为 no issues found in 63 source files。
- 已运行 `uv sync --frozen --all-extras --dev`。
- 已运行 `uv run ruff format --check .`，结果为 77 files already formatted。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run mypy app`，结果为 no issues found in 63 source files。
- 已运行 `uv run pytest`，结果为 32 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认当前迁移仍可生成 PostgreSQL SQL。
- 已确认启动前 `18080`、`15432`、`16379`、`19000`、`19001`、`19200`、`19600` 未监听。
- 已启动 Docker Compose 依赖服务 `postgres`、`redis`、`minio`、`opensearch` 并等待健康。
- 已运行 `uv run alembic upgrade head`，真实 PostgreSQL migration 通过。
- 已运行 `uv run python -m scripts.seed_admin`，管理员 seed 通过。
- 已启动本地 API `uv run uvicorn app.main:app --host 127.0.0.1 --port 18080`。
- 初次使用 PowerShell `Invoke-WebRequest` PUT 预签名 URL 时暴露 MinIO 签名兼容问题，已通过 S3 client 显式 `s3v4` 和 path-style 配置修复；随后 PowerShell 对 8MB byte array PUT 出现客户端空引用，改用 Python/httpx 执行真实联调。
- 已使用 Python/httpx 真实验证 `/healthz`、`/api/v1/auth/login`、`POST /api/v1/spaces`、`POST /api/v1/uploads/init`、`POST /api/v1/uploads/{session_id}/parts/{part_no}/presign`、直接 PUT 两个分片到 MinIO 预签名 URL、`POST /api/v1/uploads/{session_id}/complete`、`GET /api/v1/uploads/{session_id}` 和 `POST /api/v1/uploads/{session_id}/abort`；两个分片 PUT 均为 200，complete 后状态为 `completed`，已上传分片为 `[1, 2]`，abort 返回 `aborted`。
- 验证完成后已关闭本次启动的 API 和 Docker Compose 服务，并确认 `18080`、`15432`、`16379`、`19000`、`19001`、`19200`、`19600` 不再监听。
- 已再次运行 `uv run ruff format --check .`，结果为 77 files already formatted。
- 已再次运行 `uv run ruff check .`，结果为 All checks passed。
- 已再次运行 `uv run mypy app`，结果为 no issues found in 63 source files。
- 已再次运行 `uv run pytest`，结果为 32 passed。
- 已再次运行 `uv run alembic upgrade head --sql`，确认当前迁移仍可生成 PostgreSQL SQL。
- 已运行 `uv run ruff format .`，格式化下载接口和测试相关文件。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run pytest tests/test_download.py`，结果为 3 passed。
- 已运行 `uv run pytest tests/test_download.py tests/test_upload.py`，结果为 9 passed。
- 已运行 `uv sync --frozen --all-extras --dev`。
- 已运行 `uv run ruff format --check .`，结果为 79 files already formatted。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run mypy app`，结果为 no issues found in 64 source files。
- 已运行 `uv run pytest`，结果为 35 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认当前迁移仍可生成 PostgreSQL SQL。
- 已确认启动前 `18080`、`15432`、`16379`、`19000`、`19001`、`19200`、`19600` 未监听。
- 已启动 Docker Compose 依赖服务 `postgres`、`redis`、`minio`、`opensearch` 并等待健康。
- 已运行 `uv run alembic upgrade head`，真实 PostgreSQL migration 通过。
- 已运行 `uv run python -m scripts.seed_admin`，管理员 seed 通过。
- 已启动本地 API `uv run uvicorn app.main:app --host 127.0.0.1 --port 18080`。
- 已使用 Python/httpx 真实验证 `/healthz`、`/api/v1/auth/login`、`POST /api/v1/spaces`、`POST /api/v1/uploads/init`、`POST /api/v1/uploads/{session_id}/parts/{part_no}/presign`、直接 PUT 两个分片到 MinIO 预签名 URL、`POST /api/v1/uploads/{session_id}/complete`、`GET /api/v1/files/{node_id}/download` 和直接 GET 下载预签名 URL；下载返回 200，下载字节数 8,392,704，与原始内容一致。
- 验证完成后已关闭本次启动的 API 和 Docker Compose 服务，并确认 `18080`、`15432`、`16379`、`19000`、`19001`、`19200`、`19600` 不再监听。
- 已运行 `uv run ruff format .`，格式化容量账本相关文件。
- 已运行 `uv run pytest tests/test_space_file.py tests/test_upload.py`，结果为 13 passed。
- 已运行 `uv run mypy app`，结果为 no issues found in 68 source files。
- 已运行 `uv run alembic upgrade head --sql`，确认新增 quota 迁移 `20260630_0005` 可生成 PostgreSQL SQL。
- 已运行 `uv sync --frozen --all-extras --dev`。
- 已运行 `uv run ruff format --check .`，结果为 84 files already formatted。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run pytest`，结果为 36 passed。
- 已确认启动前 `18080`、`15432`、`16379`、`19000`、`19001`、`19200`、`19600` 未监听。
- 已启动 Docker Compose 依赖服务 `postgres`、`redis`、`minio`、`opensearch` 并等待健康。
- 已运行 `uv run alembic upgrade head`，真实 PostgreSQL migration 升级到 `20260630_0005` 通过。
- 已运行 `uv run python -m scripts.seed_admin`，管理员 seed 通过。
- 已启动本地 API `uv run uvicorn app.main:app --host 127.0.0.1 --port 18080`。
- 已使用 Python/httpx 真实验证 `/healthz`、`/api/v1/auth/login`、`POST /api/v1/spaces`、`POST /api/v1/uploads/init`、`POST /api/v1/uploads/{session_id}/parts/{part_no}/presign`、直接 PUT 两个分片到 MinIO 预签名 URL 和 `POST /api/v1/uploads/{session_id}/complete`；随后直接查询真实 PostgreSQL，确认空间 `quota_accounts.used_bytes` 和 `quota_ledger.delta_bytes` 均为 8,390,656，`quota_ledger.reason=file_version_created`。
- 验证完成后已关闭本次启动的 API 和 Docker Compose 服务，并确认 `18080`、`15432`、`16379`、`19000`、`19001`、`19200`、`19600` 不再监听。
- 已运行 `uv run ruff format .`，格式化服务端 hash 校验相关代码和测试。
- 已运行 `uv run pytest tests/test_upload.py tests/test_download.py`，结果为 12 passed。
- 已运行 `uv sync --frozen --all-extras --dev`。
- 已运行 `uv run ruff format --check .`，结果为 85 files already formatted。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run mypy app`，结果为 no issues found in 69 source files。
- 已运行 `uv run pytest`，结果为 38 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认当前迁移仍可生成 PostgreSQL SQL。
- 已确认启动前 `18080`、`15432`、`16379`、`19000`、`19001`、`19200`、`19600` 未监听。
- 已启动 Docker Compose 依赖服务 `postgres`、`redis`、`minio`、`opensearch` 并等待健康。
- 已运行 `uv run alembic upgrade head`，真实 PostgreSQL migration 通过。
- 已运行 `uv run python -m scripts.seed_admin`，管理员 seed 通过。
- 已启动本地 API `uv run uvicorn app.main:app --host 127.0.0.1 --port 18080`。
- 已使用 Python/httpx 真实验证 `/healthz`、`/api/v1/auth/login`、`POST /api/v1/spaces`、`POST /api/v1/uploads/init`、`POST /api/v1/uploads/{session_id}/parts/{part_no}/presign`、直接 PUT 两个分片到 MinIO 预签名 URL、`POST /api/v1/uploads/{session_id}/complete` 和 `GET /api/v1/files/{node_id}/download`；服务端 `sha256` 与原始内容匹配时 complete 成功，下载字节数 8,390,708 且内容一致。
- 已使用 Python/httpx 真实验证错误 `content_hash` 的 multipart complete 返回 `UPLOAD_HASH_MISMATCH`；随后直接查询真实 PostgreSQL，确认失败会话状态为 `failed`，`completed_node_id`、`completed_version_id`、`completed_blob_id` 均为空，文件版本/blob/容量流水数量未增加，`upload.failed` 审计 metadata reason 为 `hash_mismatch`。
- 验证完成后已关闭本次启动的 API 和 Docker Compose 服务，并确认 `18080`、`15432`、`16379`、`19000`、`19001`、`19200`、`19600` 不再监听。
- 已运行 `uv run ruff format .`，格式化最终对象 key 规整相关代码和测试。
- 已运行 `uv run pytest tests/test_upload.py tests/test_download.py`，结果为 13 passed。
- 已运行 `uv run ruff format --check .`，结果为 86 files already formatted。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run mypy app`，结果为 no issues found in 70 source files。
- 已运行 `uv run pytest`，结果为 39 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认当前迁移仍可生成 PostgreSQL SQL。
- 已确认启动前 `18080`、`15432`、`16379`、`19000`、`19001`、`19200`、`19600` 未监听。
- 已启动 Docker Compose 依赖服务 `postgres`、`redis`、`minio`、`opensearch` 并等待健康。
- 已运行 `uv run alembic upgrade head`，真实 PostgreSQL migration 通过。
- 已运行 `uv run python -m scripts.seed_admin`，管理员 seed 通过。
- 已启动本地 API `uv run uvicorn app.main:app --host 127.0.0.1 --port 18080`。
- 已使用 Python/httpx 与 boto3 真实验证 `/healthz`、`/api/v1/auth/login`、`POST /api/v1/spaces`、`POST /api/v1/uploads/init`、`POST /api/v1/uploads/{session_id}/parts/{part_no}/presign`、直接 PUT 两个分片到 MinIO 预签名 URL、`POST /api/v1/uploads/{session_id}/complete`、`GET /api/v1/files/{node_id}/download` 和直接 GET 下载预签名 URL；随后直接查询真实 PostgreSQL 与 MinIO，确认 `file_blobs.storage_key` 为 `objects/{tenant_id}/{hash_prefix}/{content_hash}`，最终对象存在且大小为 8,403,608 字节，临时 `uploads/...` 对象已删除，下载内容与原始内容一致。
- 验证完成后已关闭本次启动的 API 和 Docker Compose 服务，并确认 `18080`、`15432`、`16379`、`19000`、`19001`、`19200`、`19600` 不再监听。
