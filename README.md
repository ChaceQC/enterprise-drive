# 企业网盘

企业网盘工程，当前候选发布基线为版本 `1.0.0`，已包含后端主链路、Web 用户端与管理后台、OIDC/OAuth 2.1 + PKCE、LDAP 目录同步、规模化治理，以及 Windows 11 Rust/Tauri 桌面端的双向同步、离线恢复和签名更新；目标是形成可试点上线的企业级文件管理服务。项目以《企业网盘开发者技术计划书.md》为技术基线，优先保障文件元数据、对象存储、权限、身份、审计、搜索和异步任务之间的一致性。

## 技术基线

- Python 3.12+
- uv
- FastAPI
- SQLAlchemy 2.x
- PostgreSQL 16+
- Redis
- S3 兼容对象存储
- OpenSearch
- Celery
- Prometheus、Alertmanager、Grafana、OpenTelemetry
- Windows 11
- Docker Desktop（WSL2 / Linux containers）
- Docker Compose v2
- Compose 内 Nginx gateway
- Rust stable、Cargo workspace、Tauri 2（Windows 11 桌面 Alpha）
- TypeScript、React、Vite、OpenAPI 生成 client、Playwright（Web 用户端与管理后台）

## 一期范围

- 本地账号登录、管理员 seed、BFF + HttpOnly Cookie Session、CSRF 防护、登录失败防护、账号锁定和可插拔验证码。
- 密码策略、首次登录强制改密、用户改密、管理员重置/解锁、浏览器与桌面会话列表/吊销，以及全会话吊销。
- OIDC/OAuth 2.1 + PKCE 提供商配置、账号绑定、回调状态校验、单点登录/登出；LDAP 只读目录源配置、连接测试、dry-run/全量/增量同步、稳定外部 ID 映射、冲突报告和离职禁用。
- 空间、文件树、文件版本、回收站、基础容量账本。
- S3 兼容对象存储上传下载，支持 multipart upload。
- 目录权限、空间角色、拒绝优先、权限缓存和高危动作二次校验。
- 内部分享、外链分享、创建者/接收人列表、站内通知、提取码、过期、次数限制、撤销和授权重算。
- 预览 Worker、预览产物生命周期、搜索索引/OCR Worker、审计 outbox dispatcher。
- 大目录权限重算、统一生命周期策略/运行记录、审计分区/归档/外部投递、Outbox dead-letter 查询/重放和治理看板。
- API/Worker 结构化日志、Prometheus 指标和 OpenTelemetry tracing。
- 系统管理员空间、统计、维护任务和异步 CSV 导出 API。
- Docker Compose 本地开发环境、Windows 11 Docker 正式部署、可选监控栈、自动化备份签名/完整包保护/离线轮换/隔离恢复、Redis/OpenSearch 可移植迁移、Alembic migration 和 CI 质量门禁。

## 二期 Rust 桌面客户端

当前仓库已交付 Sprint 7 和 Sprint 8 的 `DC-001` 至 `DC-010`，目标版本为 `0.5.0`，采用 Rust stable、Cargo workspace 和 Tauri 2。

- Rust 负责 API client、设备会话、远端增量消费、本地 SQLite 索引与离线操作队列、上传下载、系统凭据、平台路径边界、更新验签和脱敏诊断导出。
- 桌面端提供登录、空间与目录浏览、上传下载队列、同步目录选择、暂停/继续/取消、离线元数据、任务栏托盘、逐文件同步状态和冲突记录。
- `notify` 监听本地创建、修改、删除、重命名和移动；远端增量、tombstone、版本前置条件和客户端操作 ID 共同驱动双向同步，设备吊销会停止 watcher、操作和传输。
- 冲突默认保留双方内容，生成带设备名和 UTC 时间的副本；目录移动/重命名竞争会终止原排队操作，防止随后覆盖远端结果。
- 下载只在 `.drivepart` 的版本、hash、进度和长度匹配时发送 Range，SHA-256 通过后执行 Windows 原子替换；旧临时内容或 hash 失败会清理并有界重试。
- 支持选择性同步、忽略规则、带宽/并发限制、Windows 保留名、尾随点/空格、Unicode NFC、长路径和默认不跟随链接/reparse point。
- `drive-update` 校验 Ed25519 清单与包签名、SHA-256、平台和版本，支持暂存安装、健康标记和 watchdog 回退；CI 生成 Authenticode 签名安装包，仓库只包含公钥与公开证书。
- 首发平台为 Windows 11；Windows 稳定后再推进 macOS 和 Linux。

## 后续产品路线

当前仓库已经建立 `frontend/` Web 工程，产品路线状态如下：

- Sprint 9 / `0.6.0`：文件版本、回收站/批量文件操作、内部分享接收端与通知，以及用户、部门、用户组、空间、配额、统计、维护和导出管理 API 已完成。
- Sprint 10 / `0.7.0`：TypeScript + React + Vite Web 用户端与管理后台已完成代码侧交付，覆盖文件/批量/上传下载、搜索预览回收站、分享通知、公开分享、管理页面、生成式 OpenAPI client、Compose Web 发布和 Playwright E2E。
- Sprint 11 / `0.8.0`：`BE-040` 至 `BE-043`、`FE-010` 至 `FE-011` 已完成并通过远端 CI；覆盖登录失败防护、账号锁定、密码与会话管理、OIDC/OAuth 2.1 + PKCE、LDAP 同步，以及用户端和管理端身份页面。
- Sprint 12 / `0.9.0`：`BE-046` 至 `BE-050`、`FE-012`、`OPS-001` 至 `OPS-003`、`QA-001` 至 `QA-002` 已完成代码侧交付；覆盖大目录权限重算、生命周期策略/运行、审计分区/归档/投递、Outbox dead-letter、治理页面/看板、备份签名/完整包保护/离线副本、Redis/OpenSearch 可移植迁移和四依赖故障恢复矩阵。legal hold、高级内容分类和复杂 DLP 继续归远期 `GOV-001`。
- Sprint 13 / `1.0.0`：后端、Web、桌面端统一 UAT、性能、安全、升级回滚和正式发布。

虚拟盘、macOS/Linux 文件提供器、WebDAV、SMB、移动端、在线协同、复杂 DLP、跨地域双活和计费已进入带编号与入口条件的远期 Backlog。

## 当前状态

当前仓库已完成 Sprint 1 至 Sprint 12 的代码侧交付，并把后端、Web、桌面安装包、更新器和 OpenAPI 契约统一到 Sprint 13 候选版本 `1.0.0`。其中 Sprint 7 和 Sprint 8 覆盖 `DC-001` 至 `DC-010`，Sprint 9 覆盖 `BE-036` 至 `BE-039`、`BE-044`、`BE-045`，Sprint 10 覆盖 `FE-001` 至 `FE-009`，Sprint 11 覆盖 `BE-040` 至 `BE-043`、`FE-010` 至 `FE-011`，Sprint 12 覆盖 `BE-046` 至 `BE-050`、`FE-012`、`OPS-001` 至 `OPS-003`、`QA-001` 至 `QA-002`。当前运行时 OpenAPI 快照统计为 116 个路径、148 个操作、178 个 schemas；数据库 migration head 为 `20260804_0026`。`frontend/` 包含 React/Vite/TypeScript 用户端与管理后台、生成式 API client、Cookie Session/CSRF、账号安全与 OIDC/LDAP 页面、治理看板、统一错误恢复和 Playwright E2E；桌面端包含 Tauri 2 应用、设备会话、双向同步、SQLite 离线队列、DTP/1 传输、Windows Credential Manager/路径适配、签名更新回退和脱敏诊断。

Sprint 3 上传主链路已包含 `upload_sessions`、multipart init/presign/complete/abort、秒传、服务端 SHA-256、最终对象归档、失败清理、过期会话回收、限流、下载、容量流水以及对象/回收站治理。multipart complete 使用标准 S3 HTTP 控制面；同 hash 首次上传在 PostgreSQL 中通过原子 upsert 只创建一个 blob，异常 complete 可从对象事实恢复，失败路径会清理受控 `uploads/...` 临时对象。

配额管理已提供 `GET /api/v1/admin/quotas/accounts`、`PUT /api/v1/admin/quotas/accounts/{owner_type}/{owner_id}` 以及配额策略的列表、创建、更新和停用接口。空间、租户、用户和策略账户继续由数据库事实驱动；更新现有额度需要乐观前置条件，新额度不得低于已用容量，数据库中已建立的用户/租户账户优先于环境默认值。`quota.reconcile_space_usage` 当前仍只校准空间账户；部门/临时额度和多维通用校准继续归后续治理。

回收站保留期任务 `file.cleanup_expired_trash` 已接入 `maintenance` 队列和 Celery beat，默认保留 30 天。任务按租户扫描超过保留期的删除批次根节点，排除同一 `deleted_at/deleted_by` 批次内的子节点，事务锁定根节点与全部已删除后代后复用彻底删除语义：删除版本和节点、扣减 blob 引用、按版本流水释放全部配额维度、写入搜索删除事件与系统审计。迁移 `20260731_0013` 增加 `idx_nodes_trash_cleanup`，`/metrics` 暴露 `trash_cleanup_total{status}` 和 `trash_cleanup_released_bytes_total`。

项目文件传输正式使用 `Drive Transfer Protocol v1`（`DTP/1`）。上传、文件下载和外链下载允许客户端发送 `X-Drive-Transfer-Protocol: DTP/1`，未知版本返回 HTTP 426；JSON 传输响应返回 `protocol_version=DTP/1`，代理文件流返回同名响应头。DTP/1 只定义 HTTPS 之上的状态机、分片、断点、校验、幂等和错误码；普通文件正文通过短期预签名 HTTPS 直达 MinIO/S3，高密级或强审计场景可使用 `GET /api/v1/files/{node_id}/content` 由 API 流式代理。

文件安全策略已提供 `/api/v1/admin/file-security/policies` 的列表、创建、更新和停用接口，可按扩展名或 MIME 前缀选择 `presigned`、`proxy`、`watermark`、`blocked` 模式，并记录密级、策略版本和审计。当前版本与历史版本下载都会执行关键字 DLP 的 audit/block、fail-closed 和自动选路；内部图片/PDF 可通过 `GET /api/v1/files/{node_id}/watermarked-content` 生成动态水印。公开外链支持 `delivery_mode=presigned|watermark`，水印派生对象使用真实文件名、MIME 和大小记账；要求代理的策略会阻止外链直连。搜索正文已支持图片/扫描 PDF OCR；外链代理流、历史版本专用水印、legal hold 和高级内容分类继续归后续治理。

`BE-036` 已完成文件版本核心 API：`GET /api/v1/files/{node_id}/versions` 使用签名 cursor 分页列出不可变历史并标记当前版本；`GET /api/v1/files/{node_id}/versions/{version_id}/download` 按指定历史版本返回 DTP/1 预签名下载；`POST /api/v1/files/{node_id}/versions/{version_id}/rollback` 在节点行锁和可选当前版本前置条件下创建递增的新版本，不改写旧版本。回滚复用原 blob、增加引用计数、执行多维配额扣减、更新 `current_version_id`，并写入审计、搜索抽取/索引和预览事件。

`BE-037` 已完成回收站与批量操作核心 API：`GET /api/v1/files/trash` 按 `deleted_at/id` 使用签名 cursor，仅返回删除批次根节点；`POST /api/v1/files/batch-delete`、`batch-move`、`batch-restore`、`batch-purge` 每次最多处理 100 个节点，逐项返回成功或错误码。四个写入口强制使用 `Idempotency-Key`，数据库按租户、用户、操作和 key hash 唯一保存请求 hash 与最终响应；相同请求重放原响应，不同请求复用同 key 返回冲突。每个节点在独立 savepoint 中复用单项权限、审计、搜索、容量和 blob 引用语义，单项失败不会回滚其他成功项。

Sprint 2 剩余增强已闭环：创建文件夹、移动、恢复和对应批量入口支持 `fail`、`keep_both`、`replace`。`keep_both` 自动生成 `名称 (n)`，文件名工具会保留扩展名；`replace` 把当前同名节点移入回收站后再完成新操作，不执行不可恢复覆盖。删除、恢复或彻底删除的子树超过 `DRIVE_FILE_TREE_ASYNC_THRESHOLD` 时返回 HTTP 202 和 operation ID，根节点先进入目标状态，maintenance Worker 通过 `file.process_tree_operations` 使用递归 CTE、`deleted_root_id` 和固定批次分段提交后代状态或容量/blob 清理。`GET /api/v1/files/operations/{operation_id}` 查询进度，失败任务可用 `POST .../retry` 恢复；每个批次可重入，Worker 中断后从 PostgreSQL 事实继续。

Sprint 12 治理模块新增 `/api/v1/admin/governance`：系统管理员可查看治理摘要和既有大目录任务，按 space 或 node 创建/查询/重试权限重算，维护租户生命周期策略，并创建 dry-run 或正式运行。权限重算把 snapshot、`permission_version`、稳定 cursor、处理/索引计数和错误码保存在 PostgreSQL；任务中断后继续固定批次，运行期间发现更高权限版本会从新快照重启。生命周期策略统一回收站/预览保留期，以及上传、分享、无引用 blob、孤儿对象开关；策略更新使用乐观版本，运行状态持久化到 `admin_jobs`。legal hold、高级内容分类和复杂 DLP 不在 Sprint 12，继续归远期 `GOV-001`。

审计治理把 `audit_logs` 改为 PostgreSQL 月分区表，并由 `audit.ensure_partitions` 预建未来分区；`audit.archive_retention` 按保留期生成签名 JSONL 归档，可配置归档成功后删除源记录。外部审计 HTTP 投递对正文生成 HMAC-SHA256 签名。Outbox 现按 transient/permanent 分类，使用带 jitter 的有界退避和处理超时恢复；系统管理员可通过 `/api/v1/admin/audit/governance` 与 `/api/v1/admin/outbox/dead-letters` 查看归档/投递摘要、dead-letter 列表/详情并执行幂等重放，响应只暴露 payload key 列表。

`BE-027` 可观测性已完成：API `/metrics` 暴露路由模板维度的请求数/延迟、上传下载、权限、Outbox 和搜索延迟指标，正式 2-worker Uvicorn 使用 Prometheus multiprocess 聚合；5 个 Celery Worker 分别在 Compose 内部 `9100` 暴露 task 数量、状态、耗时及本进程业务指标。可选 `monitoring` profile 内置 Prometheus、Alertmanager 和 Grafana，运行概览、维护治理和 Sprint 12 治理三张预置看板通过 gateway `/grafana/` 访问，三项监控服务都不发布宿主端口。JSON 日志自动关联 `service`、`env`、`request_id`、`task_id`、`trace_id` 和 `span_id`；OpenTelemetry exporter 默认 `none`，可配置 Console 或 OTLP/HTTP。

`BE-030` 已完成 API 与网络安全矩阵；Sprint 11 把账号安全、OIDC/PKCE、LDAP Source/sync 和身份页面纳入 route matrix，Sprint 12 又加入治理策略、权限重算、审计治理和 Outbox dead-letter 写入口的 CSRF、管理员、租户与重放边界。当前 OpenAPI 为 116 个路径、148 个操作、178 个 schemas。损坏/超大图片、OCR 页数/像素/体量边界、文档路径与扩展名注入、Range 权限、预签名 URL、管理 API、OIDC 绑定/回调、LDAP 冲突/离职和治理入口均进入相应测试；真实 Nginx raw HTTP smoke 继续验证未知 API/S3 Host、CL/TE 冲突、重复 Content-Length、API 请求体 413 与 storage 流式入口。

Sprint 4 权限系统已新增 `space_members` 基础表，创建空间时会自动写入当前用户的 `owner` 角色成员关系。空间列表、文件树、上传初始化、multipart complete 和下载已通过 `PermissionService` 做空间级成员角色检查：`viewer` 可列表和下载，`editor` 可上传与修改，`owner/admin` 可执行全部空间级动作。空间成员管理 API 已接入，支持 owner/admin 添加、调整和移除成员，权限变更会递增空间权限版本并写入审计。节点 ACL 已支持 `user`、`department`、`group` 三类主体，基于 org 事实表展开用户部门和用户组，支持 allow/deny、继承开关和 deny 优先，并已覆盖文件列表、创建文件夹、上传初始化、multipart complete 和下载入口；文件列表响应会通过批量权限评估返回每个子节点的常用动作权限，避免列表页逐项查询。系统管理员现可通过管理 API 完成用户生命周期、部门层级重命名/移动/停用、用户组状态以及部门/组成员变更；部门路径更新会原子改写子树并拒绝环路，所有修改使用版本前置条件、租户隔离和审计。空间成员和节点 ACL 变更都会写入 `permission.changed` outbox event，`permission.invalidate_cache` 会消费该事件并删除匹配的 Redis 权限缓存 key；部门/用户组成员或状态变化会写入租户级事件，按受影响用户或整个租户失效权限缓存。搜索 ACL 已新增 token builder 和 `search.acl_rebuild_requested` outbox event；秒传、multipart complete、重命名、移动、删除、恢复和彻底删除会写入 `search.index_requested`，上传完成还会写入 `search.extract_requested`。`search.dispatch_outbox` 会从 PostgreSQL 重新构建文件索引文档写入 OpenSearch，不再活跃或已彻底删除的文件会删除索引文档，并在 ACL 变更后按 space 或 node 子树保守重建索引 token；搜索抽取支持 UTF-8 文本、可复制正文 PDF、DOCX/PPTX/XLSX、图片 OCR、扫描 PDF OCR，以及 LibreOffice 转换后的旧 Office/ODF 文档。Tesseract OCR 受页数、像素、渲染字节、正文字符数和命令超时边界约束，抽取结果写入 `file_versions.search_text` 并刷新索引 `content` 字段。预览链路使用 Pillow、Poppler 和 LibreOffice 生成私有 WebP 产物；`GET /api/v1/files/{node_id}/preview` 会刷新 `last_accessed_at` 并返回短期私有 URL，`preview.cleanup_artifacts` 周期清理非当前旧版本产物和超期孤儿预览对象。`GET /api/v1/search` 已接入 allow/deny token、签名 cursor、HTML 编码高亮、限流和 `read_meta` 二次权限校验。最终对象的 DB 驱动清理由 `file.cleanup_unreferenced_blobs` 承担；对象存储中没有 DB 元数据的孤儿最终对象由 `file.cleanup_orphaned_objects` 承担。

分享模块支持内部分享、外链分享、提取码哈希、过期时间、访问/下载次数上限、撤销、分享项、用户/部门/用户组接收人和访问日志。内部分享新增 `GET /api/v1/shares/created`、`GET /api/v1/shares/received`、`GET /api/v1/shares/{share_id}/items`、`POST /api/v1/shares/{share_id}/download`、通知列表和已读入口；`share_recipient_grants` 将当前接收人展开为用户授权，组织成员变化通过 outbox 重算，撤销、过期和成员移除会失活授权与通知。接收人访问/下载会重新校验创建者当前分享权限、节点/版本/blob、次数限制和文件安全策略，并写入成功/拒绝访问日志与审计。`share.expire_shares` 已由 Celery beat 周期执行。公开外链接口继续支持租户、token、提取码、次数、限流以及预签名或图片/PDF 水印派生下载；外链受控代理流仍属后续边界。

本地后端验证：

若本机缺少 `uv`、Python 3.12、Docker、GitHub CLI 或后端依赖包等必要工具，可按命令提示自行安装或补齐；确因权限、网络或平台限制无法安装时，需要记录到 `PROJECT_PROGRESS.md`。

```powershell
Set-Location backend
uv sync --all-extras --dev
uv run alembic upgrade head
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest
```

BE-030 路由、租户和对抗输入矩阵：

```powershell
uv run pytest tests/test_route_security_matrix.py `
  tests/test_route_security_cross_tenant.py `
  tests/test_security_adversarial.py -q
```

真实 Nginx 原始 HTTP 安全 smoke：

```powershell
uv run python -X utf8 scripts/smoke_gateway_security_docker.py `
  --image nginx:1.27-alpine `
  --template ..\deploy\windows\nginx\default.conf.template
```

真实 Docker 可观测性 smoke 会自动创建并清理隔离的 PostgreSQL、Redis、2-worker API、migration 和 maintenance Worker，验证多进程指标、真实 Celery task 以及 API/Worker trace 日志：

```powershell
Set-Location backend
uv run python scripts/smoke_observability_docker.py `
  --image enterprise-drive-backend:windows-local
```

真实 MinIO 集成测试默认跳过；需要本机已有 MinIO 或通过 Docker 启动临时 MinIO 后显式打开：

```powershell
Set-Location backend
$env:DRIVE_RUN_MINIO_TESTS = "1"
$env:DRIVE_TEST_MINIO_ENDPOINT = "http://127.0.0.1:19000"
$env:DRIVE_TEST_MINIO_ACCESS_KEY = "drive-dev"
$env:DRIVE_TEST_MINIO_SECRET_KEY = "drive-dev-password"
$env:DRIVE_TEST_MINIO_BUCKET = "enterprise-drive-test"
uv run pytest tests/test_storage_minio_integration.py -q
```

GitHub `backend-ci` 会启动临时 MinIO，并运行这组真实对象存储集成测试，覆盖基于公共预签名 API 和标准 S3 HTTP 的 multipart 控制面、预签名上传/下载、copy、delete、list、hash 校验和孤儿最终对象扫描。

`backend-ci` 先通过 `.github/scripts/ci_scope.py` 计算变更范围：Rust crate 源码/测试只运行 `rust-desktop`，Tauri UI/配置/图标/签名只运行安装包 job，Tauri Rust 入口同时运行两者；普通库源码不会因为 push 自动重复构建 NSIS。CI workflow/router、桌面 README 和其他文档变更只保留 `changes` 轻量校验，相关业务代码未变化时直接跳过对应重 job。Rust job 先跑 workspace tests，再以 `--no-deps` 执行 Clippy；Rust 校验与安装包 job共享按 `Cargo.lock`/toolchain 计算的 Cargo registry/git cache，安装包先一次 `cargo fetch` 再以 offline 模式构建。Sprint 13 的安装包 job 还会从 Git 历史构建上一版本回滚安装包，对当前/回滚包执行 Authenticode 与更新签名验证，并生成 `release-manifest.json` 和 `SHA256SUMS`。相同分支的新提交会取消旧运行，MinIO 与 Rust 依赖供应链扫描每周一 UTC 03:17 额外执行，手工 `workflow_dispatch` 仍运行完整门禁。

BE-029 目标规模门禁已完成：10,000 节点、100 万 OpenSearch 文档和 1,000 万审计日志均已进入真实 target 环境；search、audit、mixed、upload-init 沿用既有通过工件，本轮只补此前未通过的 `upload_complete`。最终计入 1,936 个 complete 样本、0 失败，吞吐 `58.364 RPS`，不含 storage merge 的 API P95 为 `790 ms`，端到端 P95 为 `840 ms`，storage merge P95 为 `71 ms`，`report.json passed=true`；2,000 个准备节点已全部清理。详见 `docs/performance-benchmark.md`。

`backend-ci` 在 runtime image 构建后还会执行 `scripts/smoke_observability_docker.py`，使用隔离的真实 PostgreSQL、Redis、2-worker API 和 Celery Worker 验证可观测性进程边界。

回收站清理还提供真实 PostgreSQL Docker 集成测试。测试数据库必须先执行完整 Alembic migration，测试会验证 PostgreSQL 索引、删除批次根节点筛选、行锁路径、租户隔离、容量、blob 引用、审计和搜索 outbox：

```bash
docker run -d --name enterprise-drive-test-postgres \
  -p 15432:5432 \
  -e POSTGRES_DB=enterprise_drive \
  -e POSTGRES_USER=drive \
  -e POSTGRES_PASSWORD=drive-test-password \
  postgres:16-bookworm
cd backend
DRIVE_DATABASE_URL=postgresql+asyncpg://drive:drive-test-password@127.0.0.1:15432/enterprise_drive \
  uv run alembic upgrade head
DRIVE_RUN_POSTGRES_TESTS=1 \
DRIVE_TEST_POSTGRES_URL=postgresql+asyncpg://drive:drive-test-password@127.0.0.1:15432/enterprise_drive \
  uv run pytest tests/test_trash_cleanup_postgres_integration.py -q
docker rm -f enterprise-drive-test-postgres
```

GitHub `backend-ci` 同时启动临时 PostgreSQL 16 容器、执行 Alembic upgrade，并自动运行该真实数据库测试；SQLite 测试不再作为回收站清理 PostgreSQL 并发与索引语义的唯一证据。

## 文档

- `AGENT.md`：开发协作约束。
- `docs/drive-transfer-protocol-v1.md`：`DTP/1` 上传、下载、断点、校验、版本协商与安全边界。
- `PROJECT_PLAN.md`：执行版项目计划。
- `PROJECT_PROGRESS.md`：项目进度记录。
- `企业网盘开发者技术计划书.md`：完整技术计划书。
- `backend/README.md`：后端工程启动与验证说明。
- `docs/deployment-windows-docker.md`：Windows 11 Docker Desktop 正式部署、运维、备份与回滚说明。
- `docs/ops-sprint12-backup-portability.md`：manifest 来源签名、完整包保护、离线副本与 Redis/OpenSearch 可移植迁移。
- `docs/deployment-preview-worker.md`：预览 Worker 资源配额和部署说明。
- `docs/maintenance-monitoring.md`：maintenance 周期任务状态、指标、告警规则和排障顺序。
- `docs/minio-security-risk.md`：固定 MinIO 镜像的 Critical 基线、可达性缓解和正式发布门禁。
- `docs/performance-benchmark.md`：`BE-029` Locust 性能基准、fixture、资源边界和报告格式。
- `docs/security-testing.md`：`BE-030` 威胁模型、Bandit/pip-audit 门禁、登录防护和安全修复记录。
- `docs/identity-security.md`：Sprint 11 本地账号、OIDC/PKCE、LDAP 同步、会话撤销和身份安全边界。
- `docs/release-v1.0.0.md`：`v1.0.0` 候选发布说明、兼容性、工件和阻塞项。
- `docs/sprint13-release-readiness.md`：`REL-001` 至 `REL-005` 的 UAT、性能、安全、升级回滚、RPO/RTO 和签字清单。

## 部署说明

正式部署目标为 Windows 11 + Docker Desktop（WSL2/Linux containers）。仓库根 `compose.windows.yml` 是唯一正式编排入口，根 `.env.windows.example` 是环境变量模板，`deploy/windows/manage.ps1` 是 PowerShell 管理入口；`backend/docker-compose.yml` 继续只用于本地依赖开发。`manage.ps1 up` 默认使用 `--no-build --pull never`，只启动已经准备好的本地镜像；首次部署或代码变更后的镜像构建必须显式使用 `up -Build`。可选监控栈使用 `config/up/down/status/logs -Monitoring`；正式启用时必须配置非示例 Grafana 密码和可达的 Alertmanager webhook 文件。第三方镜像拉取、项目镜像构建、服务启动和备份恢复测试保持为独立步骤。

应用本身也会在 `DRIVE_ENVIRONMENT=production` 时执行 fail-fast 配置校验，因此绕过 `manage.ps1` 直接启动 API、Worker、beat、migration 或 seed 仍会拒绝示例/过短 secret、无强密码连接 URL、关闭限流、Wildcard Trusted Hosts 和不安全公网 HTTP/Cookie 配置。默认 `localhost:18080/19000` HTTP 基线仅在全部浏览器与 S3 公共端点均为 localhost/回环地址时允许。

Compose 内的 Nginx gateway 是唯一宿主端口入口。默认本机模式使用 `http://localhost:18080` 同时提供 Web 页面和 API，S3 外部端点为 `http://localhost:19000`；内部 `web` 服务只在 Compose 网络暴露 `8080`。公网 TLS 模式已提供 ACME HTTP-01 bootstrap、Certbot 证书卷、TLS server block、HTTP `308` 跳转、`80/443` 双域名 Host 分流、证书续期与 Nginx 热重载命令；生产使用 `https://drive.example.com`、`https://storage.example.com` 时，必须先配置真实 DNS、邮箱、API/MinIO CORS、Trusted Hosts、Secure Cookie 和 S3 公共端点，执行 `manage.ps1 tls-init -Tls` 后再运行 `manage.ps1 up -Tls -Build`。Web、API、Worker、PostgreSQL、Redis、OpenSearch、MinIO API/Console 等内部服务不发布宿主端口；Worker metrics `9100` 也只暴露在 Compose 网络内。

正式编排还包含真实 PostgreSQL `/readyz` 探针、独立 Celery beat、隔离的 Preview Worker、内部 Web、named volumes 和自动化备份恢复。`manage.ps1 backup` 会生成 PostgreSQL custom dump、MinIO/Redis/OpenSearch/TLS 停止状态卷归档、CMS 环境文件密文和严格 manifest；manifest v2 从 16 个无 profile 默认服务的实际 Compose 容器记录 image ID，并记录工件大小/SHA-256、精确 `compose.windows.yml` SHA-256、Git commit、项目版本、S3 bucket、OpenSearch index、`DRIVE_TLS_CERT_NAME` lineage 名称、Alembic revision 与 WAL LSN。传入签名证书后会生成 detached CMS `manifest.p7s`；传入完整包加密证书后，payload 使用 AES-256-CBC，加上 HMAC-SHA256 完整性和 RSA-OAEP-SHA256 密钥封装，发布目录不保留明文数据工件。`backup-verify` 要求当前 Git HEAD、Compose、项目版本、configuration lineage 和全部 16 个服务镜像与 manifest 精确一致，并在无网络、只读、drop capabilities 的临时容器/卷中预解包扫描 tar。

`backup` 和 `restore` 同时使用 project 级与逐 physical volume Windows mutex；备份根目录会拒绝卷根、仓库目录/祖先及未预先使用 restricted ACL 的既有非空目录，staging/正式备份、`-ForceRestore` rollback archive 和恢复后的 CMS 文件会自动应用只允许当前用户、SYSTEM、Administrators 的 restricted ACL。`restore` 只接受不同且已停止的 Compose project，并拒绝 source/target 卷重叠、错误卷标签、foreign attachment；使用 `-ForceRestore` 时会先归档原非空卷，失败后还原原非空卷、清空原空卷、删除新卷并停止 target，回滚异常则保留并报告归档路径。恢复提交后的 rollback cleanup 异常只报告维护失败，不会反向回滚已恢复数据。CMS 明文输出必须使用仓库和备份目录外的绝对新文件路径、已有父目录，并只在本次恢复模式全部门禁成功的末尾原子发布；若发布竞态中目标被其他进程创建，脚本保留该 foreign file。真实随机 source/target project 演练已验证数据库和对象回到同一备份点、CMS 环境文件解密、TLS lineage、Worker/beat、gateway 与健康检查。

`backup-retention` 按保留天数和最少份数轮换经过校验的托管备份，`backup-offline-rotate` 把指定或最新托管备份原子复制到离线目录，逐文件对账 size/SHA-256 并记录 canonical inventory digest；`restore-drill` 把最新或指定备份恢复到随机隔离 Compose project 并在结束后删除 target 容器/卷。Redis/OpenSearch 升级不再复制原始卷：`data-migration-export` 生成 Redis RDB 和 OpenSearch settings/mappings/bulk NDJSON，`data-migration-apply` 在修改目标前创建 rollback export、拒绝向更低 major 版本迁移，并在失败时自动回退。完整命令、保留规则和报告字段见 [Sprint 12 备份安全、离线副本与跨版本数据迁移](docs/ops-sprint12-backup-portability.md)。

备份安全边界如下：未启用完整包保护时，PostgreSQL dump、MinIO/Redis/OpenSearch 原始卷归档和 TLS 证书卷仍依赖 BitLocker、restricted NTFS ACL 与加密介质；detached CMS 签名验证来源和 manifest 完整性，但证书信任链、吊销和双人保管仍由组织 PKI 负责；完整包加密证书私钥丢失会使备份永久不可恢复。`-ForceRestore` rollback 与跨版本自动回退都属于有证据的尽力恢复。当前 MinIO Server/Client 仍有 16/9 个 Critical 唯一 ID 基线，其中两个 MinIO 自身 Critical 在固定社区镜像中没有上游 patched version；CI 阻断新增 Critical 不代表现有风险已经消除。正式 `v1.0.0` tag/Release 在采用受支持修复镜像或可审计补丁镜像并重新扫描前保持阻塞，详见 [MinIO 安全风险与发布门禁](docs/minio-security-risk.md)。

本机已用自签名双域名证书在标准宿主 `80/443` 启动完整编排，验证 HTTP `308`、API readiness、MinIO CORS/S3v4、临时 ACME bootstrap、原 gateway 恢复和彻底清理；公网受信证书签发与真实续期仍需要生产 DNS/网络环境。生产完成后使用 `tls-validate-public` 一次性验证双域名只解析到公网地址、HTTP 精确 `308`、HTTPS readiness、证书链和剩余有效期，并保存 JSON 记录。完整流程见 [Windows 11 Docker 部署说明](docs/deployment-windows-docker.md)，预览资源限制见 [预览 Worker 部署说明](docs/deployment-preview-worker.md)。Kubernetes、systemd 仅作为未来可选迁移方案。
