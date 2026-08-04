# 项目阶段进度

更新时间：2026-08-04

## 1. 总体结论

当前项目处于 **v0.9.0、Sprint 12 规模化治理代码、本地门禁与远端 CI 均已完成，下一产品阶段进入 Sprint 13 稳定版发布**：

- 后端核心能力、权限、分享、预览、搜索、完整管理 API、Windows 11 Docker 部署、监控 profile 和备份治理入口已经形成试点基础，Sprint 2 至 Sprint 6 代码侧剩余项为空。
- `BE-036` 至 `BE-050`、`FE-001` 至 `FE-012` 均已实现；后端、Web、Rust workspace、Tauri 安装包、更新器和 OpenAPI 契约已统一到 Sprint 12 目标版本 `0.9.0`。
- `BE-046` 已完成持久化大目录权限重算、固定批次/稳定游标、权限版本变更后重启、失败恢复和治理进度；`BE-047` 已完成租户生命周期策略、乐观版本、dry-run/正式运行记录；`BE-048` 的 OCR/复杂格式能力沿用已完成基线。
- `BE-049` 已完成审计月分区、未来分区维护、保留归档、外部 HMAC 投递和签名归档；`BE-050` 已完成 Outbox 错误分类、jitter、处理超时恢复、最老积压指标、dead-letter 查询和幂等重放。
- `FE-012` 已完成治理后台，覆盖大目录任务、权限重算、生命周期、审计归档/投递、dead-letter 重放和治理告警。
- `OPS-001` 至 `OPS-003` 已完成备份 detached CMS 来源签名、可选完整包加密、离线副本轮换，以及 Redis/OpenSearch 可移植导出、跨版本门禁和自动回退；`QA-001`/`QA-002` 已接入四依赖故障/恢复矩阵和现有 OpenAPI/client 契约门禁。
- Sprint 7 与 Sprint 8 的 `DC-001` 至 `DC-010` 已完成：Rust/Tauri Windows 11 骨架、设备会话、增量游标/tombstone、SQLite 离线队列、DTP/1 双向传输、文件监听、冲突副本、选择性同步、Windows 路径边界、诊断导出、签名更新和失败回退均已落地。
- `frontend/` 已交付 React/Vite/TypeScript 工程、生成式 API client、Cookie Session/CSRF 壳、用户端与管理后台主要流程、公开分享入口、错误恢复和三浏览器 Playwright 配置；Compose 新增内部 `web` 服务，由 gateway 统一代理页面、静态资源和 `/api/v1`。
- Sprint 10 的 `backend-ci` 历史证据继续保留：提交 `8da1abe` 对应 run `30893658311` 的 9 个 job 全部成功。Sprint 11 最终提交为 `e6b4f6d`，`backend-ci` run `30922718148` 成功；changes/backend 成功，7 个未受影响 job 按 scope 跳过，frontend 已由 run `30919983108` 验证，Rust/MinIO/Windows/安装包已由 run `30917345858` 验证。
- Sprint 12 最终功能/修复提交为 `91ad743`，`backend-ci` run `30935875456` 成功：`changes`、`frontend`、`backend` 成功，其余 6 个未受影响 job 按 scope 跳过，后端为 `456 passed, 2 warnings`；本地未重复执行 Sprint 10 浏览器全集、既有 MinIO 全集、性能 target 或桌面历史集合。
- 真实生产 OIDC/LDAPS、DNS/受信证书证据和 MinIO 修复镜像不在当前本机环境内，正式 `v0.4.0` tag/Release 保持阻塞；`v1.0.0` 的完整 UAT、升级回滚、发布包和验收报告仍属于 Sprint 13。

## 2. 当前仓库快照

- 分支：`dev`
- Sprint 3 对象存储稳定性基线：`31a0de1`；配额、安全与性能收尾：`6465c5a`；CI 安全解析与下载达限修复：`404cc08`、`d8185a5`
- 项目版本：`0.9.0`
- Sprint 7 最终代码提交：`a57d3fb`
- Sprint 7 最终 CI：`backend-ci` run `30838990372`（8 个 job 全部成功）
- Sprint 8 最终修复提交：`d3725a3`
- Sprint 8 最终 CI：`backend-ci` run `30854694265`（8 个 job 全部成功）
- Sprint 9 收尾提交：`d31eaaa`
- Sprint 9 最终 CI：`backend-ci` run `30872900207`（8 个 job 全部成功）
- Sprint 10 交付提交：`8da1abe`
- Sprint 10 最终 CI：`backend-ci` run `30893658311`（9 个 job 全部成功）
- Sprint 12 最终功能/修复提交：`91ad743`
- Sprint 12 最终 CI：`backend-ci` run `30935875456`（`changes`、`frontend`、`backend` 成功，其余 6 个 job 按 scope 跳过）
- Sprint 12 四依赖报告：artifact `8903238332`，SHA-256 `4602126048cb0c8a8e3599be4d59f4aa4f75f9f3332967519c2d99b09f7fd989`
- Git tag：当前尚未建立 `v0.4.0` tag
- 当前 OpenAPI 归档：116 个路径、148 个操作、178 个 schemas
- 最新数据库迁移：`20260804_0026`
- Sprint 8 范围：`DC-007` 至 `DC-010` 已完成实现、本地验收和远端 CI
- Sprint 9 收尾：`0.6.0` 版本清单、运行时版本、安装包版本和 OpenAPI 契约已对齐，远端 CI 已全绿
- Sprint 10 代码侧：`FE-001` 至 `FE-009`、`frontend/`、Compose `web`、gateway 路由和 frontend CI 已落地；当前默认无 profile 服务为 16 个
- Sprint 11：`BE-040` 至 `BE-043`、`FE-010` 至 `FE-011`、身份安全 migration、OpenAPI/client 和 Windows 环境透传已落地，本地相关门禁与远端 CI 均已通过
- Sprint 12：`BE-046` 至 `BE-050`、`FE-012`、`OPS-001` 至 `OPS-003`、`QA-001` 至 `QA-002` 已落地，本地新增和直接受影响门禁与远端 CI 均已通过
- 桌面更新公开证书 DER SHA-256：`765e82aba7bd3276f18eeadddd7b33257a68b7a1ddcdac6d4fc7f7bc639a3ca5`
- 正式本机入口：gateway `http://localhost:18080` 同时提供 Web/API，`http://localhost:19000` 提供 S3；`web` 仅暴露 Compose 内部 `8080`
- 当前未完成：真实生产 OIDC/LDAPS 验收、DNS/受信证书、MinIO 修复镜像，以及 Sprint 13 完整 UAT、升级回滚、发布包和 `v1.0.0` 验收

## 3. 各阶段进度

| 阶段 | 已完成 | 尚未完成 |
|---|---|---|
| Sprint 1：工程底座 | FastAPI、uv、配置、日志、错误处理、健康检查、指标、Tracing、PostgreSQL/Redis/MinIO/OpenSearch/Celery、Cookie Session、CSRF、CI | OIDC、LDAP、账号治理属于后续 Sprint 11 |
| Sprint 2：空间和文件树 | 空间、目录、列表、重命名、移动、删除/恢复/彻底删除、大目录后台任务、回收站分页、四类批量操作、批量幂等、`fail/keep_both/replace`、游标分页、基础审计 | 无 |
| Sprint 3：上传下载 | multipart、秒传、断点状态、complete/abort 幂等、预签名/代理/水印下载、服务端 SHA-256、最终对象归档、限流、多维容量账本、账户/策略管理 API、文件安全策略、关键字 DLP、清理任务、真实 MinIO CI、标准 S3 HTTP multipart 控制面、同 hash 并发解析、失败存储清理，以及 10,000 节点/100 万索引/1,000 万审计日志目标规模门禁 | 无 |
| Sprint 4：权限系统 | 空间成员和角色、用户/部门/用户组 ACL、继承、deny 优先、缓存失效、搜索 ACL 过滤、关键入口二次查权，以及用户/部门/用户组的 cursor 列表、详情、创建、更新、停用和成员管理 API | 无 |
| Sprint 5：分享、预览、搜索 | 内外部分享、创建者列表、“分享给我的”、接收人详情与 DTP/1 受控下载、通知已读/失效、部门/用户组授权重算、过期分享维护、图片/PDF/Office 预览、预览产物生命周期、OpenSearch ACL 过滤、图片/扫描 PDF OCR 和旧 Office/ODF 抽取 | 无 |
| Sprint 6：管理、治理、上线 | 审计、用户/部门/用户组/空间/配额/文件安全/统计/维护/导出管理 API；生命周期、指标、Tracing、Prometheus/Alertmanager/Grafana、Windows Compose、Nginx、TLS/ACME、备份校验/轮换/隔离演练和安全门禁 | 仅剩生产环境的真实 DNS/受信证书记录、MinIO 修复镜像和正式 `v0.4.0` 发布标记 |
| Sprint 7：Rust 桌面基础 | `DC-001` 至 `DC-006`：Cargo/Tauri 骨架、设备会话、增量游标/tombstone、Rust API client、SQLite 索引、DTP/1 队列、托盘、同步根和诊断导出；Windows CI 已全绿 | 无 |
| Sprint 8：双向同步与桌面发布 | `DC-007` 至 `DC-010`：文件监听、远端增量、离线队列、重启恢复、冲突副本、选择性同步、限速并发、Windows 路径边界、逐文件诊断、签名安装包、更新验签和回退 | 无 |
| Sprint 9：核心产品闭环 | `BE-036` 至 `BE-039`、`BE-044`、`BE-045` 已完成 | 无 |
| Sprint 10：Web 用户端与管理后台 | `FE-001` 至 `FE-009` 已完成：React/Vite、生成 API Client、用户端、管理后台、公开分享、Compose Web、gateway 路由、frontend CI、Playwright E2E 与远端全 scope 门禁 | 无；真实生产浏览器/网络验收属于后续发布门禁 |
| Sprint 11：身份与账号安全 | `BE-040` 至 `BE-043`、`FE-010` 至 `FE-011` 已完成代码侧交付：账号锁定/解锁、密码与全会话、OIDC/PKCE、LDAP 同步和用户/管理身份页面；本地相关门禁与远端 CI 已通过 | 真实生产 provider/目录验收属于发布门禁 |
| Sprint 12：规模化治理与内容能力 | `BE-046` 至 `BE-050`、`FE-012`、`OPS-001` 至 `OPS-003`、`QA-001` 至 `QA-002` 已完成代码侧交付、直接受影响本地门禁和远端 CI：权限重算、生命周期策略/运行、审计分区/归档/投递、Outbox DLQ、治理页面/看板、备份安全、离线副本、Redis/OpenSearch 可移植迁移和四依赖故障恢复矩阵 | 无代码或 CI 剩余项；生产密钥/外部审计接收端验收属于上线门禁，legal hold、复杂 DLP/内容分类属于远期 `GOV-001` |
| Sprint 13：稳定版发布 | 尚未开始 | UAT、压测、安全验收、升级回滚、统一版本、`v1.0.0`、发布包和验收报告 |

## 4. 已有验证证据

- Sprint 12 治理后端定向测试 `tests/test_sprint12_governance.py` 为 `4 passed`，覆盖权限重算分批恢复/版本重启、生命周期策略与运行持久化、ACL 事件转持久任务和治理管理员 API。
- Sprint 12 前端已通过 lint、typecheck 和 Chromium 聚焦治理 E2E `1 passed`；场景覆盖大目录进度、权限失败重试、生命周期 dry-run、审计归档摘要和 dead-letter 幂等重放，测试端口已清理。
- Sprint 12 版本已统一为 `0.9.0`：`uv lock --check` 通过，版本一致性 `1 passed`，Cargo metadata 确认 9 个本地 `drive-*` 包均为 `0.9.0`，OpenAPI 归档为 116/148/178。
- Sprint 12 OPS 已完成 12 个 PowerShell 脚本 parser、来源签名/完整包加密专项 smoke、离线副本/迁移治理 smoke 和既有直接受影响 backup/governance smoke；本机真实双 project Redis/OpenSearch 导出、应用和自动回退集成已通过，临时容器、卷和端口已清理。
- 四依赖矩阵已在本机真实 Docker 中完成 PostgreSQL、Redis、MinIO、OpenSearch 初始健康、逐项故障探测、恢复和最终全健康；远端后端 job 在同一次 pytest 中通过 `DRIVE_RUN_SPRINT12_MATRIX=1` 复验并上传 UTF-8 JSON 报告。
- 审计/Outbox 定向用例通过；真实 PostgreSQL 空库升级到 `20260804_0026` 并完成 `0026 -> 0024 -> 0026` 往返，分区专项 `1 passed`；Prometheus 规则、Grafana JSON、最终 OpenAPI/client、route matrix、Compose、actionlint 和 CI scope 均已通过本地直接门禁。
- Sprint 12 最终远端证据：提交 `91ad743` 对应 [`backend-ci` run `30935875456`](https://github.com/ChaceQC/enterprise-drive/actions/runs/30935875456) 成功，后端 `456 passed, 2 warnings`；四依赖报告 artifact [`8903238332`](https://github.com/ChaceQC/enterprise-drive/actions/runs/30935875456/artifacts/8903238332) 的 SHA-256 为 `4602126048cb0c8a8e3599be4d59f4aa4f75f9f3332967519c2d99b09f7fd989`。
- Sprint 11 账号安全专项 `tests/test_sprint11_account_security.py` 4 个用例均已分别通过；受影响既有回归为 Auth 8 passed、登录限流 2 passed、管理员用户生命周期 1 passed、桌面设备会话 1 passed。
- Sprint 11 账号安全相关 15 个文件 Ruff/format 通过，Auth/Admin/Device 相关 12 个源码文件 Mypy 通过；管理员创建测试 helper 已同步新密码策略。
- Sprint 11 本地门禁已通过：账号安全 4 项与受影响回归 12 项、OIDC/LDAP 10 项、route matrix 134 条路由及 6 项集合校验、前端三浏览器 12 场景均通过；静态、锁文件、OpenAPI/client、migration、Compose、Cargo metadata 和差异检查均通过。最终提交 `e6b4f6d`，`backend-ci` run `30922718148` 成功；changes/backend 成功，7 个未受影响 job 按 scope 跳过，frontend 已在 `30919983108` 成功，Rust/MinIO/Windows/安装包已在 `30917345858` 成功。
- Sprint 11 当时的运行时 OpenAPI 归档、生成 client 与 route matrix 已精确对账为 105 个路径、134 个操作、162 个 schemas，不能用 Sprint 10 的 83/110/132 替代；当前 Sprint 12 基线为 116/148/178。
- Sprint 6 管理 API 基线：`backend/tests/test_admin_sprint6_management.py` 首轮 `3 passed`；后续只重跑受 CSV/事务边界修改影响的导出生命周期和两个新增 owner transfer/CSV 防护用例，结果 `3 passed`。
- Sprint 6 静态门禁：管理模块、admin Worker、migration、网关 smoke 和测试共 28 个文件 Ruff/format 通过；管理模块与 admin Worker 共 25 个源码文件 Mypy 通过。
- 临时空 PostgreSQL 已从零升级到单一 head `20260803_0021`，确认 `admin_jobs.parameters_json=jsonb`、`spaces.version NOT NULL` 和管理列表索引存在；临时容器已删除。
- Windows 治理脚本保持 ASCII、无 BOM、PowerShell 5.1 parser 通过；新增 smoke 验证 backup ID/checksum、保留轮换、restricted ACL 记录、随机隔离恢复 project、target 清理和公网 IP 分类。
- Prometheus `promtool`、Alertmanager `amtool`、Grafana dashboard JSON 和三镜像 healthcheck 命令均已验证；Compose 同时启用 `monitoring`/`tls-tools` 时仍只有 gateway 发布宿主端口。
- Nginx 本机/TLS 模板 `nginx -t` 通过；真实 raw HTTP smoke 验证未知 API/S3 Host 返回空连接、CL/TE 和重复 Content-Length 拒绝、API 413、storage streaming 与本机 `localhost:19000` 兼容。
- Sprint 10 当时的 OpenAPI 归档与生成 client 为 83 个路径、110 个操作、132 个 schemas；Sprint 11 已同步为 105 个路径、134 个操作、162 个 schemas，写操作 CSRF、设备认证和管理员/登录态读取门禁继续由后端门禁覆盖。
- Sprint 7 后端定向测试：`backend/tests/test_desktop_sprint7.py` 与 OpenAPI 契约测试合计 `5 passed`；Ruff/format 与 `uv lock --check` 通过。
- 空 PostgreSQL 已从零升级至 `20260803_0022`，并确认 `desktop_devices`、`device_sessions`、`client_operations`、`sync_changes` 四张 Sprint 7 表存在。
- Sprint 8 后端版本化上传新增用例 `2 passed`；此前尚未执行的受影响上传回归与 OpenAPI 契约 `17 passed`。
- 空 PostgreSQL 已从零升级到 `20260803_0023`，并完成 `0023 -> 0022 -> 0023` 往返；目标节点、版本前置条件和成对约束均存在。
- Sprint 8 此前 Rust 核心专项 `16 passed`，覆盖 10,000 文件初始索引、离线操作/传输异常退出恢复、Windows 路径、冲突命名、原子替换、1 GiB 分片范围和更新签名篡改拒绝。
- 本轮只运行 8 个新增缺口用例：`drive-local-index` `1 passed`，覆盖多同步根操作/传输队列隔离；`drive-transfer` `4 passed`，覆盖 1 GiB 持久化 Range、真实进程重启续传、旧 `.drivepart` 清理和 hash 失败重试；`drive-sync-engine` `3 passed`，覆盖双端同时修改、目录移动/重命名冲突和设备吊销停止全部同步。
- Rust workspace 已通过 `cargo fmt --all --check`；受影响的 `drive-local-index`、`drive-transfer`、`drive-sync-engine` 通过 GNU Clippy `-D warnings`。本机 MSVC shell 缺少 `link.exe`，完整 Tauri/NSIS/Authenticode 由本次 Windows CI 执行，不重复运行已知会在本机链接阶段停止的全 workspace。
- 最终 `backend-ci` run `30838990372`（提交 `a57d3fb`）的 `rust-desktop`、`rust-dependency-policy`、`backend`、`windows-deployment`、`minio-image-policy`、两组 MinIO supply-chain 和 `windows-desktop-installer` 共 8 个 job 全部成功。
- `backend-ci` run `30854694265`（提交 `d3725a3`）的 8 个 job 全部成功，完成 Sprint 8 Authenticode 指纹校验修复的远端门禁。
- Sprint 9 版本收尾定向验证：`uv lock --check`、Ruff、Python format、Cargo metadata、Cargo fmt、JSON 解析和 `git diff --check` 通过；版本一致性、健康检查与桌面 OpenAPI 契约共 `12 passed`。本机定向 Cargo check 仍受缺少 MSVC `link.exe` 限制，完整 Rust 编译由本次 Windows CI 执行。
- Sprint 9 最终 `backend-ci` run `30872900207`（提交 `d31eaaa`）的 8 个 job 全部成功；远端 Windows runner 已完成 Rust Clippy/tests/release、Tauri/NSIS、Authenticode 和签名更新工件验证。
- Sprint 10 前端专项已确认 `npm ci` 完成 269 个依赖包安装并审计 270 个包、0 vulnerabilities；lint、typecheck、production build、OpenAPI archive/client 漂移均通过，单元测试为 5 个文件、14 个用例，OpenAPI breaking-change checker 为 6 个用例。
- Sprint 10 Playwright 只运行新增和受影响流程并按失败项收敛，Chromium、Firefox、WebKit 累计 `13 passed, 2 skipped`；文件版本回滚、目录接收人分享、上传队列、搜索/回收站/通知、管理员与公开分享路径均已有本地浏览器证据。
- Sprint 10 最终 `backend-ci` run `30893658311`（提交 `8da1abe`）的 `changes`、`frontend`、`backend`、`rust-desktop`、`rust-dependency-policy`、`windows-desktop-installer`、`windows-deployment`、`minio-image-policy` 和 `minio-supply-chain` 共 9 个 job 全部成功。
- Compose 声明 20 个服务，其中 16 个无 profile 默认服务；gateway 仍是唯一宿主端口发布者，`web` 使用内部 `8080` 和 `/web-healthz`，备份 smoke/integration 的服务清单已同步。
- Rust CI 失败项均按实际日志收敛：先修正 Clippy `too_many_arguments`、reqwest `query` feature，再将 Windows 不支持的 cargo-deny 容器 action 移到 Ubuntu；依赖策略最终 advisories、bans、licenses、sources 均通过。
- Sprint 7 的全绿 CI 验证提交为 `a57d3fb`；全绿后仅追加状态文档收尾，不改变该提交中已验证的代码与 CI 配置；未重复执行已通过的后端、MinIO、备份恢复或性能集合。
- 本轮推送前已确认的 GitHub Actions `backend-ci` 基线：运行 `30782429638`、提交 `d8185a5`，5 个 job 全部成功。
- 该 CI 后端门禁：`314 passed`；Ruff、格式检查、Bandit、依赖漏洞审计、Mypy、真实 PostgreSQL/MinIO、Windows 部署和 MinIO 供应链门禁均通过。
- Sprint 4 用户/组织管理集中定向首轮：`92 passed, 1 skipped, 1 failed`；唯一失败修复后只重跑该用例，结果 `1 passed`。
- Sprint 4 临时真实 PostgreSQL：空库升级到 `20260803_0019` 通过，双会话用户组版本竞争和双管理员并发停用保护分别 `1 passed`，临时容器均已删除。
- Sprint 4 静态验证：171 个源码文件 Mypy 通过，Ruff lint 和本轮 Python 文件格式检查通过；OpenAPI 58 个路径、79 个操作与安全矩阵精确对账。
- Sprint 5 集中定向验证覆盖内部分享、通知/授权重算、过期分享、预览生命周期、OCR/复杂格式边界和 Celery schedule；首次相关集合仅 1 个访问日志动作命名不一致，修复后只重跑该失败用例并通过。
- Sprint 5 静态验证：178 个源码文件 Mypy 通过，Ruff、Bandit、Alembic 离线 SQL、单一 migration head 和 Windows Compose 解析通过；当时运行时 OpenAPI 为 64 个路径、85 个操作，migration head 为 `20260803_0020`。
- 临时空 PostgreSQL 已从零升级到 `20260803_0020`，并确认分享授权/通知表及预览最后访问字段存在；内容处理 `preview` 镜像已成功构建并在构建阶段验证 Tesseract `eng`/`chi_sim` 语言包。
- CI 收尾修复：S3 multipart 外部 XML 改用 `defusedxml` 安全解析；外链下载在生成预签名 URL 或写入水印派生对象前原子占用下载次数，达限请求不再产生无效存储副作用。
- `BE-036` 定向验证：`3 passed`。
- `BE-037` 集中定向验证：`3 passed`；安全矩阵 `51 passed`；真实跨租户定向 `1 passed`。
- Sprint 2 剩余增强定向验证：冲突策略 `3 passed`、大目录 `2 passed`；与 schedule/安全矩阵/跨租户合并为 `61 passed`。
- `BE-035` 定向验证：`8 passed`。
- `BE-034` 定向验证：`6 passed`。
- `BE-029` 小规模真实 Docker smoke：170 个请求、0 失败。
- Sprint 3 配额管理定向：既有集中用例 `3 passed`；真实 PostgreSQL 乐观前置条件用例 `1 passed`；空库升级到 `20260803_0018` 通过。
- Sprint 3 文件安全与外链安全集中定向：8 passed；历史版本 DLP 与派生文件真实大小补充用例 2 passed。
- 路由安全矩阵覆盖当前 OpenAPI 的 73 个路径、99 个操作；Sprint 6 管理路由已纳入匿名、CSRF、管理员和跨租户门禁。
- `BE-029` 目标规模：10,000 节点、100 万 OpenSearch 文档、1,000 万审计日志；最终 `upload_complete` 1,936 个样本、0 失败、58.364 RPS、API P95 790 ms，`report.json passed=true`。
- 性能清理：2,000/2,000 个准备节点已 purge，隔离 target 容器、卷和网络为 0。
- Windows 备份恢复的默认数据恢复和完整全栈恢复均已通过。
- 当前无运行中的容器。

## 5. 下一步顺序

1. 进入 Sprint 13，执行全产品 UAT、升级/回滚、性能与安全发布门禁、RPO/RTO 签字和 `v1.0.0` 工件收口。
2. 在真实生产网络执行 OIDC/LDAPS、`tls-validate-public` 和双域名证书验收。
3. 采用受支持修复镜像或可审计补丁镜像解决 MinIO Critical，重新生成 SBOM/Grype 并运行真实 MinIO/备份恢复兼容门禁。

## 6. 状态判断

当前项目已经超过“后端接口样例”阶段，具备完整后端主链路、Web 用户端与管理后台、账号安全、OIDC/LDAP、普通目录双向同步桌面端、规模化治理和可验证部署/备份基础；但距离完整企业产品仍有发布工作量，主要缺口集中在：

- 生产 DNS/受信证书证据、MinIO 修复镜像和正式发布；
- 真实发布环境中的浏览器、网络和受信证书验收；
- 真实生产身份源验收、完整 UAT/升级回滚/RPO-RTO 和 `v1.0.0` 验收。
