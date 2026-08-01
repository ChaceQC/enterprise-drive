# 企业网盘

企业网盘工程，当前已实现的代码为版本 `0.4.0` 后端，目标是形成可试点上线的企业级文件管理服务；后续已规划 Rust 桌面客户端、Web 用户端与管理后台、企业身份和规模化治理。项目以《企业网盘开发者技术计划书.md》为技术基线，优先保障文件元数据、对象存储、权限、审计、搜索和异步任务之间的一致性。

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
- Prometheus client、OpenTelemetry
- Windows 11
- Docker Desktop（WSL2 / Linux containers）
- Docker Compose v2
- Compose 内 Nginx gateway
- Rust stable、Cargo workspace、Tauri 2（二期桌面客户端）
- TypeScript、React、Vite、OpenAPI 生成 client、Playwright（Web 用户端与管理后台）

## 一期范围

- 本地账号登录、管理员 seed、BFF + HttpOnly Cookie Session、CSRF 防护。
- 空间、文件树、文件版本、回收站、基础容量账本。
- S3 兼容对象存储上传下载，支持 multipart upload。
- 目录权限、空间角色、拒绝优先、权限缓存和高危动作二次校验。
- 内部分享、外链分享、提取码、过期、次数限制、撤销。
- 预览 Worker、搜索索引 Worker、审计 outbox dispatcher。
- API/Worker 结构化日志、Prometheus 指标和 OpenTelemetry tracing。
- Docker Compose 本地开发环境、Windows 11 Docker 正式部署、自动化备份/校验/隔离恢复、Alembic migration、CI 质量门禁。

## 二期 Rust 桌面客户端

当前仓库尚无桌面客户端代码。桌面端已正式纳入 Sprint 7 和 Sprint 8，目标版本为 `0.5.0`，采用 Rust stable、Cargo workspace 和 Tauri 2，Windows 11 优先交付。

- Rust 负责 API client、设备会话、同步状态机、本地 SQLite 索引、文件系统监听、上传下载队列、系统凭据存储和更新签名校验。
- 首个 Alpha 提供登录、空间与目录浏览、上传下载队列、同步目录选择、暂停/继续/取消、离线元数据和任务栏托盘。
- 双向同步依赖后端先补齐设备会话、增量变更游标、删除 tombstone、版本前置条件和幂等客户端操作 ID。
- 冲突保留双方内容并生成冲突副本，下载采用临时文件、hash 校验和原子替换，默认不跟随符号链接或 Windows junction。
- 首发平台为 Windows 11；签名安装包和更新验签稳定后，再推进 macOS 和 Linux。

## 后续产品路线

当前仓库尚无 `frontend/` Web 工程，以下能力已从概念升级为正式 Sprint 和工程任务：

- Sprint 9 / `0.6.0`：文件版本、回收站列表、批量文件操作、内部分享接收端和完整管理 API。
- Sprint 10 / `0.7.0`：TypeScript + React + Vite Web 用户端与管理后台，覆盖批量操作、分享通知，使用生成的 OpenAPI client 和 Playwright E2E。
- Sprint 11 / `0.8.0`：登录失败防护、账号锁定、密码与会话管理、OIDC/OAuth 2.1 + PKCE、LDAP 同步及对应用户端/管理端身份页面。
- Sprint 12 / `0.9.0`：大目录后台化、完整生命周期、OCR、审计分区、Outbox dead-letter、治理页面、备份签名与离线恢复治理。
- Sprint 13 / `1.0.0`：后端、Web、桌面端统一 UAT、性能、安全、升级回滚和正式发布。

虚拟盘、macOS/Linux 文件提供器、WebDAV、SMB、移动端、在线协同、复杂 DLP、跨地域双活和计费已进入带编号与入口条件的远期 Backlog。

## 当前状态

当前仓库已完成 Sprint 1 工程底座、Sprint 2 空间和文件树、Sprint 3 上传下载主链路，并已落地 Sprint 4 权限系统与 Sprint 5 分享、预览、搜索的基础能力。已建立 `backend` 后端工程、uv 依赖锁定、FastAPI 应用入口、配置加载、带 request/task/trace 关联的 JSON 结构化日志、`X-Request-ID` 中间件、统一错误响应、健康检查、Prometheus 指标、OpenTelemetry FastAPI/Celery tracing、本地依赖 Compose 和后端 CI。认证基础能力已落地：租户、用户、`auth_sessions` 表，管理员 seed，本地账号登录、服务端 opaque session、HttpOnly Cookie、CSRF 校验、会话轮换和登出。基础审计、outbox 和 Celery audit 队列 dispatcher 已接入；`GET /api/v1/admin/audit-logs` 已提供系统管理员专用的租户隔离审计查询，支持用户、资源、动作、结果、风险、请求 ID、时间范围和签名 cursor 筛选，并审计允许与拒绝查询。空间和文件树已具备 `spaces`、`nodes`、`file_blobs`、`file_versions` 元数据表，支持创建空间、创建文件夹、按游标列出目录节点、重命名、移动、删除到回收站和恢复。

Sprint 3 已落地上传会话基础：`upload_sessions`、`upload_parts` 迁移，`quota_accounts`、`quota_ledger` 容量账本迁移，MinIO Python SDK 对象存储适配器，`POST /api/v1/uploads/init` 初始化上传，`GET /api/v1/uploads/{session_id}` 查询状态，`POST /api/v1/uploads/{session_id}/parts/{part_no}/presign` 获取分片上传预签名 URL，`POST /api/v1/uploads/{session_id}/complete` 完成 multipart 上传并创建文件节点、blob 和首个版本，`POST /api/v1/uploads/{session_id}/abort` 取消未完成上传，`GET /api/v1/files/{node_id}/download` 生成短期私有对象下载预签名 URL，`DELETE /api/v1/files/{node_id}/purge` 彻底删除回收站节点。初始化时若命中同租户同 hash、同大小的 `file_blobs`，会走秒传分支并创建文件节点和版本，同时增加 blob 引用计数并写入审计与 outbox；若同 hash blob 正在清理，会返回 `BLOB_DELETING` 让客户端稍后重试。multipart complete 在对象存储合并后会服务端计算 `sha256` 并与 `content_hash` 比对，大小和 hash 都匹配后才将新对象归档到 `objects/{tenant_id}/{hash_prefix}/{content_hash}`，再写入 blob、版本和容量流水；hash 不匹配会标记上传失败并写入 `upload.failed` 审计。过期上传清理任务 `upload.expire_sessions` 已接入 Celery `maintenance` 队列，会按租户扫描过期的 `initiated`、`uploading`、`completing` 会话，标记为 `expired`，最佳努力中止 multipart upload、删除 `uploads/...` 临时对象，并写入 `upload.expired` 审计。上传初始化、分片签名和下载预签名已接入 Redis Lua 原子固定窗口基础限流，触发后返回 `RATE_LIMITED`。空间创建会初始化默认容量账户；`BE-033` 已把版本容量扣减扩展为 `space`、可选 `tenant`、可选 `user` 和匹配的 `policy` 账户，所有启用维度在同一数据库事务内使用条件更新防止超额，并分别写入 `quota_ledger`。`quota_policies` 可按扩展名或 MIME 前缀匹配累计额度和单文件上限；用户/租户默认额度为 `0` 时关闭对应维度。删除到回收站不释放容量，彻底删除会按文件版本的正向流水释放全部关联维度、删除节点元数据和版本记录并扣减 blob 引用计数。容量校准任务 `quota.reconcile_space_usage` 仍只校准空间账户；用户、租户和策略账户的管理 API 与通用校准归 `BE-044`。Blob 垃圾回收任务 `file.cleanup_unreferenced_blobs` 已接入 `maintenance` 队列，会扫描 `file_blobs.ref_count=0` 且无 `file_versions` 引用的 active blob，先标记为 `deleting`，再删除对象存储内容和 blob 元数据，成功或失败均写入系统审计。孤儿最终对象扫描任务 `file.cleanup_orphaned_objects` 已接入 `maintenance` 队列，默认 dry-run 并按对象存储游标分批扫完整个租户的受控 `objects/{tenant_id}/{hash_prefix}/{sha256}` key，只以 PostgreSQL `file_blobs.storage_key` 为事实来源判断是否孤儿；真实删除需显式 `dry_run=False`，成功、失败和 dry-run 计划均写入系统审计，审计不记录原始 storage key，`/metrics` 暴露 `orphan_object_cleanup_total{status}`。下载接口会返回下载地址、过期时间、文件名、当前版本、大小和 MIME，并记录成功与拒绝审计。

回收站保留期任务 `file.cleanup_expired_trash` 已接入 `maintenance` 队列和 Celery beat，默认保留 30 天。任务按租户扫描超过保留期的删除批次根节点，排除同一 `deleted_at/deleted_by` 批次内的子节点，事务锁定根节点与全部已删除后代后复用彻底删除语义：删除版本和节点、扣减 blob 引用、按版本流水释放全部配额维度、写入搜索删除事件与系统审计。迁移 `20260731_0013` 增加 `idx_nodes_trash_cleanup`，`/metrics` 暴露 `trash_cleanup_total{status}` 和 `trash_cleanup_released_bytes_total`。

项目文件传输正式使用 `Drive Transfer Protocol v1`（`DTP/1`）。上传、文件下载和外链下载允许客户端发送 `X-Drive-Transfer-Protocol: DTP/1`，未知版本返回 HTTP 426；JSON 传输响应返回 `protocol_version=DTP/1`，代理文件流返回同名响应头。DTP/1 只定义 HTTPS 之上的状态机、分片、断点、校验、幂等和错误码；普通文件正文通过短期预签名 HTTPS 直达 MinIO/S3，高密级或强审计场景可使用 `GET /api/v1/files/{node_id}/content` 由 API 流式代理。

`BE-034` 已新增受控代理下载：复用节点级 `download` 权限和当前版本/blob 事实，支持完整流式响应与标准单段 `Range`（`start-end`、`start-`、`-suffix`），返回 `Accept-Ranges`、`Content-Range`、`Content-Length`、ETag、UTF-8 文件名和 `X-Drive-Transfer-Protocol: DTP/1`。不可满足、多段或超过配置上限的 Range 返回 HTTP 416；允许与拒绝均写入 `file.downloaded`，审计包含 `delivery_mode=proxy`、版本、范围和响应字节数。普通预签名入口保持不变，水印和内容 DLP 仍由后续策略接入。

`BE-027` 可观测性已完成：API `/metrics` 暴露路由模板维度的请求数/延迟、上传下载、权限、Outbox 和搜索延迟指标，正式 2-worker Uvicorn 使用 Prometheus multiprocess 聚合；5 个 Celery Worker 分别在 Compose 内部 `9100` 暴露 task 数量、状态、耗时及本进程业务指标。JSON 日志自动关联 `service`、`env`、`request_id`、`task_id`、`trace_id` 和 `span_id`；OpenTelemetry exporter 默认 `none`，可配置 Console 或 OTLP/HTTP。

`BE-030` 已完成 API 与网络安全矩阵；新增代理下载后运行时 OpenAPI 为 37 个 route，其中排除 ping/login 后的 35 个受保护或业务入口均继续纳入矩阵。损坏/超大图片、文档路径与扩展名注入、Range 权限、预签名 URL 和轮换 token 外链穷举也已覆盖。Trusted Host/CORS 已通过动态测试，真实 Nginx raw HTTP smoke 已验证 CL/TE 冲突、重复 Content-Length、API 请求体 413 与 storage 流式入口，并固化进 CI。

Sprint 4 权限系统已新增 `space_members` 基础表，创建空间时会自动写入当前用户的 `owner` 角色成员关系。空间列表、文件树、上传初始化、multipart complete 和下载已通过 `PermissionService` 做空间级成员角色检查：`viewer` 可列表和下载，`editor` 可上传与修改，`owner/admin` 可执行全部空间级动作。空间成员管理 API 已接入，支持 owner/admin 添加、调整和移除成员，权限变更会递增空间权限版本并写入审计。节点 ACL 已支持 `user`、`department`、`group` 三类主体，基于 org 事实表展开用户部门和用户组，支持 allow/deny、继承开关和 deny 优先，并已覆盖文件列表、创建文件夹、上传初始化、multipart complete 和下载入口；文件列表响应会通过批量权限评估返回每个子节点的常用动作权限，避免列表页逐项查询。空间成员和节点 ACL 变更都会写入 `permission.changed` outbox event，`permission.invalidate_cache` 会消费该事件并删除匹配的 Redis 权限缓存 key；部门/用户组 ACL 变更当前保守失效租户内节点权限缓存。搜索 ACL 已新增 token builder 和 `search.acl_rebuild_requested` outbox event；秒传、multipart complete、重命名、移动、删除、恢复和彻底删除会写入 `search.index_requested`，上传完成还会写入 `search.extract_requested`。`search.dispatch_outbox` 会从 PostgreSQL 重新构建文件索引文档写入 OpenSearch，不再活跃或已彻底删除的文件会删除索引文档，并在 ACL 变更后按 space 或 node 子树保守重建索引 token；搜索抽取入口当前支持安全的小型 UTF-8 文本类文件、PDF 可复制正文、DOCX 段落/表格、PPTX 文本框/表格和 XLSX 单元格抽取，PDF 使用成熟开源库 `pypdf`，DOCX 使用成熟开源库 `python-docx`，PPTX 使用成熟开源库 `python-pptx`，XLSX 使用成熟开源库 `openpyxl`，抽取结果写入 `file_versions.search_text` 并刷新索引 `content` 字段，解码或解析失败标记为 `failed`，归档或正文超限标记为 `skipped`，对象存储读取失败交给 outbox 重试。预览基础链路已接入 `preview.render_requested` outbox event 和 `preview` 队列，当前使用成熟开源库 Pillow 将图片生成私有 WebP 预览产物，通过 Poppler `pdftoppm` 将 PDF 首页渲染为图片后复用同一 WebP 产物链路，并通过 LibreOffice headless 将 Office 文档先转换为 PDF 再复用 PDF/图片链路；`preview.dispatch_outbox` 已配置 Celery 软/硬超时、速率限制、结构化失败日志和 `preview_failures_total` 指标；`GET /api/v1/files/{node_id}/preview` 会通过 `preview` 权限校验后返回短期私有预览 URL。`GET /api/v1/search` 已接入查询层 `acl_tokens` allow 过滤、`deny_acl_tokens` 排除过滤、签名 cursor 分页、HTML 编码的 `<mark>` 高亮片段、`search.query` 限流和 `read_meta` 二次权限校验。最终对象的 DB 驱动清理由 `file.cleanup_unreferenced_blobs` 承担；对象存储中没有 DB 元数据的孤儿最终对象由 `file.cleanup_orphaned_objects` 承担。

分享模块已建立基础数据模型、迁移、服务层和基础 HTTP API：支持内部分享、外链分享、提取码哈希、过期时间、访问/下载次数上限、撤销状态、分享项、内部接收人和访问日志表。创建分享会逐个校验节点级 `share` 权限，外链只返回一次 256-bit 级随机 `raw_token`，数据库只保存全局唯一 token hash 和提取码 hash；`POST /api/v1/shares`、`GET /api/v1/shares/{share_id}`、`POST /api/v1/shares/{share_id}/revoke` 已接入 Cookie Session、CSRF、创建者边界、审计与 outbox。`POST /api/v1/public/shares/access` 已接入 `tenant_slug`、外链 token、提取码、状态、过期、访问次数校验，以及 IP 总量和 `token + IP` 维度限流，会在带租户边界的查询后原子增加 `view_count` 并写入 `share_access_logs`。`POST /api/v1/public/shares/download` 已接入外链下载：请求体使用 `tenant_slug`、`raw_token`、`node_id` 和可选 `passcode`，校验分享状态、提取码、下载权限、分享项范围、文件当前版本和下载次数限制，通过数据库条件 update 原子增加 `download_count`，返回短期私有对象下载 URL，并写入 `share_access_logs` 和 `share.external.downloaded` 审计；当前外链下载仍采用预签名 URL，Range/后端代理策略后续按高密级或水印场景补齐。

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

GitHub `backend-ci` 会启动临时 MinIO，并运行这组真实对象存储集成测试，覆盖 MinIO SDK multipart 私有方法封装、预签名上传/下载、copy、delete、list、hash 校验和孤儿最终对象扫描。

BE-029 目标规模数据准备使用 `uv run python -X utf8 -m performance.target_data`，OpenSearch 文档和审计日志分阶段批量生成，state checkpoint 支持中断恢复；`--max-batches` 默认只推进 1 批，显式传 `0` 才表示本次不限批次，大于 100,000 条的数据仍必须显式确认。`performance.runner upload_complete` 还提供真实 MinIO multipart complete、Server-Timing 分段和 `BE-029/2` 机器/镜像/索引/磁盘/分位报告。目标规模灌入与完整 target profile 当前暂停，不再阻塞 `BE-033` 及后续工程任务。详见 `docs/performance-benchmark.md`。

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
- `docs/deployment-preview-worker.md`：预览 Worker 资源配额和部署说明。
- `docs/maintenance-monitoring.md`：maintenance 周期任务状态、指标、告警规则和排障顺序。
- `docs/performance-benchmark.md`：`BE-029` Locust 性能基准、fixture、资源边界和报告格式。
- `docs/security-testing.md`：`BE-030` 威胁模型、Bandit/pip-audit 门禁、登录防护和安全修复记录。

## 部署说明

正式部署目标为 Windows 11 + Docker Desktop（WSL2/Linux containers）。仓库根 `compose.windows.yml` 是唯一正式编排入口，根 `.env.windows.example` 是环境变量模板，`deploy/windows/manage.ps1` 是 PowerShell 管理入口；`backend/docker-compose.yml` 继续只用于本地依赖开发。`manage.ps1 up` 默认使用 `--no-build --pull never`，只启动已经准备好的本地镜像；首次部署或代码变更后的镜像构建必须显式使用 `up -Build`，第三方镜像拉取也应单独执行，避免把下载、构建和服务启动混入备份测试。

应用本身也会在 `DRIVE_ENVIRONMENT=production` 时执行 fail-fast 配置校验，因此绕过 `manage.ps1` 直接启动 API、Worker、beat、migration 或 seed 仍会拒绝示例/过短 secret、无强密码连接 URL、关闭限流、Wildcard Trusted Hosts 和不安全公网 HTTP/Cookie 配置。默认 `localhost:18080/19000` HTTP 基线仅在全部浏览器与 S3 公共端点均为 localhost/回环地址时允许。

Compose 内的 Nginx gateway 是唯一宿主端口入口。默认本机模式继续使用 API `http://localhost:18080` 和 S3 外部端点 `http://localhost:19000`。公网 TLS 模式已提供 ACME HTTP-01 bootstrap、Certbot 证书卷、TLS server block、HTTP `308` 跳转、`80/443` 双域名 Host 分流、证书续期与 Nginx 热重载命令；生产使用 `https://drive.example.com`、`https://storage.example.com` 时，必须先配置真实 DNS、邮箱、API/MinIO CORS、Trusted Hosts、Secure Cookie 和 S3 公共端点，执行 `manage.ps1 tls-init -Tls` 后再运行 `manage.ps1 up -Tls -Build` 启动全部 Worker 和 beat。API、Worker、PostgreSQL、Redis、OpenSearch、MinIO API/Console 等内部服务不发布宿主端口；Worker metrics `9100` 也只暴露在 Compose 网络内。容器内 API/Worker 通过 `http://minio:9000` 访问对象存储，不能把内部服务名返回给浏览器。

正式编排还包含真实 PostgreSQL `/readyz` 探针、独立 Celery beat、隔离的 Preview Worker、named volumes 和 `v0.4.0` 自动化备份恢复。`manage.ps1 backup` 会生成 PostgreSQL custom dump、MinIO/Redis/OpenSearch/TLS 停止状态卷归档、CMS 环境文件密文和严格 manifest；manifest 从 15 个无 profile 默认服务的实际 Compose 容器记录 image ID，并记录工件大小/SHA-256、精确 `compose.windows.yml` SHA-256、Git commit、项目版本、S3 bucket、OpenSearch index、`DRIVE_TLS_CERT_NAME` lineage 名称、Alembic revision 与 WAL LSN。`backup-verify` 要求当前 Git HEAD、Compose、项目版本、configuration lineage 和全部 15 个服务镜像与 manifest 精确一致，并在无网络、只读、drop capabilities 的临时容器/卷中预解包扫描 tar。备份辅助容器默认限制为 `0.50 CPU / 512m memory / 512m memory-swap / 128 PIDs`，`pg_dump` 和 gzip 默认使用压缩等级 `1`；这些值可通过 `.env.windows` 中的 `DRIVE_BACKUP_*` 变量调整，但不得取消资源边界。

`backup` 和 `restore` 同时使用 project 级与逐 physical volume Windows mutex；备份根目录会拒绝卷根、仓库目录/祖先及未预先使用 restricted ACL 的既有非空目录，staging/正式备份、`-ForceRestore` rollback archive 和恢复后的 CMS 文件会自动应用只允许当前用户、SYSTEM、Administrators 的 restricted ACL。`restore` 只接受不同且已停止的 Compose project，并拒绝 source/target 卷重叠、错误卷标签、foreign attachment；使用 `-ForceRestore` 时会先归档原非空卷，失败后还原原非空卷、清空原空卷、删除新卷并停止 target，回滚异常则保留并报告归档路径。恢复提交后的 rollback cleanup 异常只报告维护失败，不会反向回滚已恢复数据。CMS 明文输出必须使用仓库和备份目录外的绝对新文件路径、已有父目录，并只在本次恢复模式全部门禁成功的末尾原子发布；若发布竞态中目标被其他进程创建，脚本保留该 foreign file。真实随机 source/target project 演练已验证数据库和对象回到同一备份点、CMS 环境文件解密、TLS lineage、Worker/beat、gateway 与健康检查。

备份安全边界如下：Windows CMS 只加密 `.env.windows`，PostgreSQL dump、MinIO/Redis/OpenSearch 原始卷归档和 TLS 证书卷归档仍依赖 BitLocker、restricted NTFS ACL 与加密外部介质；SHA-256 只证明内容与 manifest 一致，不认证备份制作者身份；Redis/OpenSearch 原始卷只适用于相同 image reference/image ID、单节点同拓扑；`-ForceRestore` rollback 属于尽力恢复。当前 MinIO Server/Client 仍有 19/12 个 Critical 基线，CI 阻断新增 Critical 不代表现有风险已经消除。

本机已用自签名双域名证书在标准宿主 `80/443` 启动完整编排，验证 HTTP `308`、API readiness、MinIO CORS/S3v4、临时 ACME bootstrap、原 gateway 恢复和彻底清理；公网受信证书签发与真实续期仍需要生产 DNS/网络环境。完整流程见 [Windows 11 Docker 部署说明](docs/deployment-windows-docker.md)，预览资源限制见 [预览 Worker 部署说明](docs/deployment-preview-worker.md)。Kubernetes、systemd 仅作为未来可选迁移方案。
