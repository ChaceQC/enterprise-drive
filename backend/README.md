# 后端工程

> 适用项目版本：`v0.4.0`

本目录承载企业网盘后端，使用 Python 3.12+、uv、FastAPI、SQLAlchemy、PostgreSQL、Redis、S3 兼容对象存储、OpenSearch 和 Celery。

## 本地准备

若本机缺少 `uv`、Python 3.12、Docker、GitHub CLI 或后端依赖包等必要工具，可按命令提示自行安装或补齐；确因权限、网络或平台限制无法安装时，需记录到项目进度。

搜索 PDF 正文抽取使用成熟开源库 `pypdf` 读取可复制文本，DOCX 正文抽取使用成熟开源库 `python-docx` 读取段落和表格文本，PPTX 正文抽取使用成熟开源库 `python-pptx` 读取文本框和表格文本，XLSX 正文抽取使用成熟开源库 `openpyxl` 读取单元格文本；预览 PDF 需要安装 Poppler，并确保 `pdftoppm` 在 `PATH` 中；Office 预览需要安装 LibreOffice，并确保 `soffice` 或配置的命令在 `PATH` 中。业务代码只编排 pypdf、python-docx、python-pptx、openpyxl、LibreOffice、Poppler、Pillow 等成熟开源工具，不自研文档解析器。

```powershell
uv python install 3.12
uv sync --all-extras --dev
Copy-Item .env.example .env
docker compose up -d postgres redis minio opensearch
uv run alembic upgrade head
uv run python -m scripts.seed_admin
uv run fastapi dev app/main.py --host 127.0.0.1 --port 18080
uv run celery -A app.infrastructure.queue.celery_app worker -Q audit,permission,preview,search,maintenance -l info
```

本目录的 `docker-compose.yml` 只用于本地依赖开发，不包含正式 API、Worker 或 gateway。Windows 11 正式部署必须回到仓库根目录使用 `compose.windows.yml`，Nginx gateway 位于 Compose 内并且是唯一宿主端口入口；完整流程见 `../docs/deployment-windows-docker.md`。

正式部署使用根 `.env.windows.example` 生成未提交的 `.env.windows`，并通过 `deploy/windows/manage.ps1` 管理：

```powershell
Set-Location ..
Copy-Item .env.windows.example .env.windows
.\deploy\windows\manage.ps1 config
.\deploy\windows\manage.ps1 up -Build
.\deploy\windows\manage.ps1 status
```

`up -Build` 是显式构建入口；普通 `up` 固定使用 `--no-build --pull never`，不会在后台补构建或拉取缺失镜像。第三方镜像应先单独 `docker pull`，项目 runtime/preview 镜像应先单独构建或明确执行一次 `up -Build`，随后再运行部署、备份或恢复门禁。

正式环境中 API/Worker 使用 `http://minio:9000` 等 Compose 内部服务端点；默认浏览器预签名地址为 gateway 提供的 `http://localhost:19000`，默认 API 入口为 `http://localhost:18080`。公网模式把真实 `.env.windows` 中的 API/存储域名、`DRIVE_S3_PUBLIC_ENDPOINT_URL`、`DRIVE_CORS_ORIGINS`、`MINIO_CORS_ALLOWED_ORIGIN`、Trusted Hosts、Secure Cookie 和 Certbot 邮箱改为生产值后，可使用以下命令完成 ACME bootstrap、证书签发和 TLS gateway 启动：

```powershell
.\deploy\windows\manage.ps1 config -Tls -Quiet
.\deploy\windows\manage.ps1 tls-init -Tls
.\deploy\windows\manage.ps1 up -Tls -Build
.\deploy\windows\manage.ps1 tls-register-renewal -Tls
.\deploy\windows\manage.ps1 status -Tls
```

公网入口使用 `https://drive.example.com` 和 `https://storage.example.com`，gateway 在 `80/443` 按 Host 分流并把 HTTP 重定向到 HTTPS。外部 S3 端点不能使用 `/s3` 等路径前缀。生产证书签发和续期要求两个域名解析到当前 Windows 宿主、外部 TCP 80/443 可达，并且 Docker Desktop 运行；`tls-renew` 和计划任务注册只接受 `tls-init` 建立的 Certbot renewal lineage，单独挂载的手工证书不具备该续期状态。Preview Worker 的 CPU、内存和临时磁盘配额请参考 `../docs/deployment-preview-worker.md`。

正式 Compose 中 API 使用受控 SQLAlchemy QueuePool；各 Celery Worker 会覆盖 `DRIVE_DATABASE_POOL_MODE=null`。这是因为当前同步 Celery task 使用 `asyncio.run()` 执行异步服务，不能跨任务事件循环复用 asyncpg 连接池。

### 可观测性

- API `/metrics` 只暴露 API 进程内的 `http_requests_total`、`http_request_duration_seconds`、上传/下载、权限判断、Outbox 和搜索延迟指标。HTTP 标签使用完整路由模板，不使用原始 URL、路径参数、用户/租户 ID 或 token；抓取 `/metrics` 自身不进入 HTTP 请求指标。
- 正式 Compose 的 API 默认运行 2 个 Uvicorn worker，使用 `PROMETHEUS_MULTIPROC_DIR=/tmp/enterprise-drive/prometheus` 聚合。Docker runtime entrypoint 只在容器启动前清理旧 `.db` metric 文件；运行中的 worker 不清理共享目录。
- API 与 Celery Worker 是不同容器。`worker-audit`、`worker-permission`、`worker-search`、`worker-maintenance` 和 `worker-preview` 各自在 Compose 内部 `9100` 暴露 `worker_tasks_total`、`worker_task_duration_seconds` 及本进程业务指标，不发布宿主端口。监控系统应按服务分别抓取，不能只抓 API `/metrics`。
- JSON 日志自动包含 `service`、`env`、`request_id`、`task_id`、`trace_id`、`span_id`、tenant/user/resource 上下文；HTTP 请求结束日志包含 route、method、status、`latency_ms`，Worker 结束日志包含 task、queue、status 和耗时。
- FastAPI 与 Celery 使用 OpenTelemetry。`DRIVE_TRACING_EXPORTER=none` 是默认值，只生成关联上下文；可改为 `console` 或 `otlp_http`。OTLP/HTTP 使用完整 traces endpoint，例如 `http://otel-collector:4318/v1/traces`；认证 header 通过 JSON 格式的 `DRIVE_TRACING_OTLP_HEADERS` 注入，不写入仓库。
- 常用配置包括 `DRIVE_SERVICE_NAME`、`DRIVE_TRACING_ENABLED`、`DRIVE_TRACING_SAMPLE_RATIO`、`DRIVE_TRACING_EXPORTER`、`DRIVE_TRACING_OTLP_ENDPOINT`、`DRIVE_TRACING_OTLP_HEADERS`、`DRIVE_TRACING_EXPORT_TIMEOUT_SECONDS`、`DRIVE_METRICS_DATABASE_REFRESH_ENABLED` 和 `DRIVE_METRICS_DATABASE_REFRESH_TIMEOUT_SECONDS`。

### 备份、校验与隔离恢复

`v0.4.0` 已通过根目录 `deploy/windows/manage.ps1` 提供 `backup`、`backup-verify` 和 `restore`。备份目录必须是仓库外的绝对专用目录，不得是卷根、仓库目录或仓库祖先；若既有目录非空，则必须已经使用本项目 restricted ACL，脚本不会直接重写任意宽范围目录 ACL。正式备份默认使用当前 Windows 用户证书存储中的 CMS 文档加密证书保护 `.env.windows`。建议创建可导出私钥的专用证书，并把 PFX 单独保存在加密离线介质中：

备份、校验和恢复的临时容器统一使用 `--pull never`，默认限制为 `0.50 CPU`、`512m` 内存、无额外 swap 和 `128` 个 PID；卷归档与 `pg_dump` 默认使用压缩等级 `1`，避免 gzip 高压缩长时间占满 CPU。对应变量为 `DRIVE_BACKUP_HELPER_CPU_LIMIT`、`DRIVE_BACKUP_HELPER_MEMORY_LIMIT`、`DRIVE_BACKUP_HELPER_PIDS_LIMIT`、`DRIVE_BACKUP_GZIP_LEVEL` 和 `DRIVE_BACKUP_PG_DUMP_COMPRESSION_LEVEL`。

```powershell
$backupCertificate = New-SelfSignedCertificate `
    -Subject "CN=Enterprise Drive Backup" `
    -Type DocumentEncryptionCert `
    -KeyExportPolicy Exportable `
    -CertStoreLocation "Cert:\CurrentUser\My" `
    -NotAfter (Get-Date).AddYears(3)

$pfxPassword = Read-Host "Backup certificate PFX password" -AsSecureString
New-Item -ItemType Directory -Path "E:\offline-key-escrow" -Force
Export-PfxCertificate `
    -Cert "Cert:\CurrentUser\My\$($backupCertificate.Thumbprint)" `
    -FilePath "E:\offline-key-escrow\enterprise-drive-backup.pfx" `
    -Password $pfxPassword
```

创建备份后立即执行校验：

```powershell
$backupRoot = "D:\enterprise-drive-backups"
$backupPath = [string](
    .\deploy\windows\manage.ps1 backup `
        -EnvFile .env.windows `
        -BackupDirectory $backupRoot `
        -ConfigEncryptionCertificateThumbprint $backupCertificate.Thumbprint |
        Select-Object -Last 1
)

.\deploy\windows\manage.ps1 backup-verify `
    -EnvFile .env.windows `
    -BackupPath $backupPath
```

manifest 会记录 15 个无 profile 默认服务实际 Compose 容器的 image ID，而不是只记录 PostgreSQL 镜像；校验还要求当前 `compose.windows.yml` SHA-256、Git commit、`backend/pyproject.toml` 项目版本、`DRIVE_S3_BUCKET`、`DRIVE_OPENSEARCH_INDEX_NAME` 和 `DRIVE_TLS_CERT_NAME` lineage 名称与备份完全一致。卷 tar 会先在无网络、只读根文件系统、只读备份挂载、drop all capabilities 和 `no-new-privileges` 的临时容器/临时卷中预解包，拒绝路径穿越、硬链接、特殊文件及越界 symlink 后才进入恢复。

隔离恢复必须使用另一个 `COMPOSE_PROJECT_NAME`。复制目标环境文件后，应同时调整目标宿主端口，并确认目标 project 没有运行中的容器：

```powershell
Copy-Item .env.windows .env.restore.windows
# 编辑 .env.restore.windows：
# - 使用不同的 COMPOSE_PROJECT_NAME
# - 使用不与 source 冲突的 gateway 宿主端口

.\deploy\windows\manage.ps1 restore `
    -EnvFile .env.restore.windows `
    -BackupPath $backupPath `
    -RestoreEnvironmentOutput "D:\enterprise-drive-secure\restored-source.env" `
    -NoStartAfterRestore
```

`backup` 和 `restore` 会同时获取 project 级及每个 source/target physical volume 的 Windows named mutex。默认恢复会拒绝已有容器、非空目标卷、source/target physical volume 重叠、错误 Compose 卷标签或 foreign container attachment；15 个默认服务的 image reference/actual image ID 任一不一致也会拒绝。`-ForceRestore` 只允许清理已停止的 target 容器或非空卷，并会在清空原非空卷前创建 restricted ACL rollback archive；恢复失败时会停止 target、删除新卷、清空原空卷并还原原非空卷，回滚异常时保留并报告归档绝对路径。恢复一旦提交，后续 rollback archive 清理失败只会返回 maintenance cleanup error 并保留归档，不会再次清空或回滚已恢复卷。`-NoStartAfterRestore` 会在 PostgreSQL 恢复和 Alembic revision 校验后停止服务，适合隔离验收。

`-RestoreEnvironmentOutput` 只把备份中的 CMS 环境文件解密到仓库和备份目录外的绝对、尚不存在文件路径，不会替换当前 target 的 `-EnvFile`；父目录必须预先存在且不得经过 reparse point。CMS 明文先保存在内存中，只在本次恢复模式的数据、Alembic revision 和镜像门禁全部成功后的最后一步，通过同目录 restricted ACL 临时文件原子发布；未使用 `-NoStartAfterRestore` 时还会先完成全栈健康和实际容器 image ID 对账。若原子发布时目标路径已被其他进程创建，失败清理会保留该 foreign file。备份根目录、staging/正式备份、rollback archive 和最终 CMS 输出会自动关闭 ACL 继承，并只允许当前用户、SYSTEM、Administrators 完全控制。

Windows CMS 只加密 `.env.windows`。PostgreSQL dump、MinIO/Redis/OpenSearch 原始卷 tar 和包含私钥的 TLS 证书卷 tar 仍依赖 BitLocker、restricted NTFS ACL 与加密外部介质。`manifest.sha256` 和工件 SHA-256 只提供完整性校验，不认证备份制作者身份。Redis/OpenSearch 原始卷恢复只支持相同 image reference、相同 image ID、单节点同拓扑；`-ForceRestore` rollback 属于尽力恢复。当前 MinIO Server/Client 仍有 19/12 个 Critical 基线，正式上线前仍需升级到修复镜像或使用可审计的自建修复镜像。完整操作和验收边界见 `../docs/deployment-windows-docker.md`。

## 常用验证

```powershell
uv run ruff check .
uv run ruff format --check .
uv run bandit -r app -ll --skip B101
uv run pip-audit --local --progress-spinner off
uv run mypy app
uv run pytest
```

### BE-030 路由与对抗输入矩阵

```powershell
uv run pytest tests/test_route_security_matrix.py `
  tests/test_route_security_cross_tenant.py `
  tests/test_security_adversarial.py -q
```

矩阵与运行时 OpenAPI 的 36 个 `/api/v1` route 完全对账，覆盖匿名、CSRF、管理员、真实跨租户资源和活跃会话撤权；对抗输入覆盖损坏/超大图片、文档路径与扩展名注入、Range 权限、预签名 URL、不同 token 外链穷举、Trusted Host 和 CORS。

真实 Nginx 原始 HTTP 安全 smoke：

```powershell
uv run python -X utf8 scripts/smoke_gateway_security_docker.py `
  --image nginx:1.27-alpine `
  --template ..\deploy\windows\nginx\default.conf.template
```

脚本只使用本地已有镜像和 `--pull never`，限制为 `0.25 CPU / 128m / 64 PIDs`，验证冲突 CL/TE、重复 Content-Length、API body limit 和 storage `100 Continue`，结束后删除随机测试容器。`backend-ci` 会先显式 pull，再执行同一 smoke。

真实 Docker 可观测性 smoke：

```powershell
uv run python scripts/smoke_observability_docker.py `
  --image enterprise-drive-backend:windows-local
```

脚本会创建隔离网络，启动真实 PostgreSQL 16、Redis、空库 migration、2-worker API 和 maintenance Worker；它会验证多进程 HTTP 指标、Outbox/Search gauge、真实 `upload.expire_sessions` Celery task 以及 API/Worker request/task/trace 日志，最后自动删除临时容器和网络。

`backend-ci` 会在 runtime image 构建后运行同一脚本，避免只在同进程单测中验证 API/Worker 指标。

### Production Settings 自校验

当 `DRIVE_ENVIRONMENT=production` 时，`Settings` 在 API、Worker、beat、migration 和 seed 读取配置时统一执行 fail-fast 校验：

- `DRIVE_DEBUG=false`、`DRIVE_RATE_LIMIT_ENABLED=true`。
- `DRIVE_SECRET_KEY` 至少 32 字符；S3 secret 和初始管理员密码至少 16 字符；拒绝 `change-me`、已知开发默认值和 `$` 间接插值。
- PostgreSQL、Redis、Celery broker/result URL 必须包含至少 16 字符的非示例密码。
- Trusted Hosts 必须显式列出且不能包含 wildcard；CORS 与 S3 公共端点必须是无凭据、无路径/query/fragment 的 HTTP(S) 根 URL。
- 只有全部公共 Host 都是 localhost/回环地址时才允许本机 HTTP 与非 Secure Cookie；出现任何非回环生产 Host 后，CORS 和 S3 公共端点必须使用 HTTPS、Cookie 必须启用 Secure，S3 外部端点只能使用 443。
- Pydantic 隐藏校验输入，启动失败日志不会把传入 secret 回显到异常文本。

本机 HTTP 基线仍使用 `http://localhost:18080` 与 `http://localhost:19000`；公网配置继续先通过 `deploy/windows/manage.ps1 config -Tls` 校验 DNS 名称、MinIO CORS 对齐、HSTS、bind 和 Certbot 邮箱等宿主部署条件。

真实 MinIO 集成测试默认跳过，避免普通单元测试依赖外部服务。需要验证对象存储真实行为时，先启动本地 MinIO，再显式设置环境变量：

```powershell
$env:DRIVE_RUN_MINIO_TESTS = "1"
$env:DRIVE_TEST_MINIO_ENDPOINT = "http://127.0.0.1:19000"
$env:DRIVE_TEST_MINIO_ACCESS_KEY = "drive-dev"
$env:DRIVE_TEST_MINIO_SECRET_KEY = "drive-dev-password"
$env:DRIVE_TEST_MINIO_BUCKET = "enterprise-drive-test"
uv run pytest tests/test_storage_minio_integration.py -q
```

`backend-ci` 会在 GitHub Actions 中启动临时 MinIO 并运行该集成测试文件，覆盖 MinIO SDK multipart 私有方法封装、预签名 PUT/GET、copy、delete、list、服务端 hash 校验和孤儿最终对象扫描。后续仍需继续扩展异常恢复、SDK 升级兼容和并发竞争场景。

### BE-029 性能基准

性能基准工具位于 `backend/performance/`，使用 dev group 中的 Locust；不会构建、拉取或启动服务。先按 `docs/performance-benchmark.md` 启动已经构建的真实 Compose 环境，再用 `uv run python -X utf8 -m performance.runner` 运行 `smoke`、`baseline` 或显式 `target` profile。报告包含 Locust CSV/HTML 和项目 `report.json`，fixture 默认在运行结束后清理。

`uv run python -X utf8 -m performance.target_data` 独立准备 BE-029 target 数据：OpenSearch 使用专属 `be029-*` index，审计日志使用专属 action；两类数据均按批次写入、原子保存 checkpoint，可中断恢复。`--max-batches` 默认值为 `1`，显式传 `0` 才表示本次不限批次；大于 100,000 条的数据还必须传 `--confirm-large-target`。`status` 查询真实计数，`cleanup --confirm-run-id` 只清理当前 state 所属数据；该工具不会隐式构建、拉取、启动或删除其他资源。

## 当前能力

- FastAPI 应用入口。
- 配置加载，统一使用 `DRIVE_` 环境变量前缀。
- 自动关联 service/env/request_id/task_id/trace_id/span_id 的 JSON 结构化日志。
- `X-Request-ID`、HTTP route/status/latency 中间件。
- 统一错误响应。
- `/healthz` 和 `/readyz` 健康检查。
- API `/metrics` Prometheus 文本指标入口，支持 Uvicorn multiprocess 聚合、HTTP/上传下载/权限/Outbox/Search/预览/清理指标。
- 5 个 Celery Worker 的内部 `9100` 指标端点，暴露真实 task 数量、状态、耗时及本进程业务指标。
- OpenTelemetry FastAPI/Celery tracing，支持采样、Console 和 OTLP/HTTP exporter。
- `/api/v1/ping` 基础 API 连通性检查。
- `tenants`、`users`、`auth_sessions` 基础表和 Alembic 初始迁移。
- `departments`、`department_members`、`user_groups`、`user_group_members` 组织基础表和迁移。
- 本地账号登录、BFF + HttpOnly Cookie Session、CSRF 校验和会话轮换。
- 旧 session 复用检测与 session family 吊销。
- `audit_logs`、`outbox_events` 基础表和迁移。
- 登录、会话轮换、登出和 session 复用检测的认证审计事件。
- 系统管理员审计查询 API，按租户隔离并支持用户、资源、动作、结果、风险、请求 ID、时间范围和签名 cursor 筛选；成功与拒绝查询均写入审计。
- Celery app 基础配置和 `audit.dispatch_outbox`、`permission.invalidate_cache`、`search.dispatch_outbox` 任务。
- outbox dispatcher，支持按事件类型 claim、成功发送、失败重试和 dead 状态。
- `spaces`、`nodes`、`file_blobs`、`file_versions` 基础表和迁移。
- 空间创建时同步创建空间根目录节点。
- `space_members` 基础表和迁移，空间创建时同步写入创建者的 `owner` 角色成员关系。
- 空间成员管理 API，支持 owner/admin 添加、查看、调整和移除成员，并保护最后一个 owner。
- `acl_entries` 基础表和迁移，支持 `user`、`department`、`group` 三类节点 ACL 主体、allow/deny、继承开关和 deny 优先。
- 文件夹创建、目录子节点列表和签名 cursor pagination。
- 文件树节点重命名、移动、删除到回收站、恢复和彻底删除。
- 空间创建、文件夹创建、重命名、移动、删除、恢复和彻底删除审计事件。
- `upload_sessions`、`upload_parts` 基础表和迁移。
- `quota_accounts`、`quota_ledger` 基础表和迁移。
- 空间创建时同步初始化默认空间容量账户。
- MinIO Python SDK 对象存储适配器，业务层通过 `StorageAdapter` 协议隔离具体 SDK。
- 上传初始化、上传状态查询、分片预签名 URL、multipart complete 和 abort 接口。
- 上传、文件下载和外链下载响应使用 `Drive Transfer Protocol v1`（`DTP/1`）标识；客户端可通过 `X-Drive-Transfer-Protocol: DTP/1` 显式协商，未知版本返回 HTTP 426。
- 秒传分支：命中同租户同 hash、同大小 blob 时直接创建文件节点和版本，并增加 blob 引用计数。
- multipart complete 成功合并后服务端校验 `sha256`，通过后将新对象归档到 `objects/{tenant_id}/{hash_prefix}/{content_hash}`，再写入 `file_blobs`、`nodes`、`file_versions`、`upload_parts` 和上传会话完成结果。
- 秒传和 multipart complete 创建文件版本时原子增加空间容量快照，并写入 `quota_ledger` 容量流水。
- 删除到回收站保留空间容量占用；彻底删除回收站节点时释放对应文件版本容量，并写入 `file_purged` 负向容量流水。
- 上传初始化、秒传、complete、abort 和 hash 不匹配等失败审计事件。
- `upload.expire_sessions` 维护任务，按租户清理过期上传会话并写入 `upload.expired` 审计事件。
- `file.cleanup_expired_trash` 维护任务，按删除批次根节点清理超过保留期的回收站子树，释放容量、扣减 blob 引用并写入系统审计和搜索删除事件。
- Redis Lua 原子固定窗口基础限流，覆盖上传初始化、分片签名、下载预签名、搜索查询、外链访问和外链下载。
- `quota.reconcile_space_usage` 维护任务，支持空间容量只读报告和修复模式。
- `file.cleanup_unreferenced_blobs` 维护任务，清理 ref_count 为 0 且无版本引用的最终对象和 blob 元数据。
- `file.cleanup_orphaned_objects` 维护任务，默认 dry-run，按对象存储游标扫描受控 `objects/{tenant_id}/{hash_prefix}/{sha256}` key，清理没有 DB blob 元数据引用的孤儿最终对象。
- 真实 MinIO 集成测试，覆盖对象读写、copy、delete、list 游标、预签名下载、multipart 私有方法封装、预签名分片 PUT、complete 后 hash 校验和孤儿最终对象扫描。
- 真实 PostgreSQL Docker 集成测试，覆盖完整 Alembic migration、`idx_nodes_trash_cleanup`、回收站保留期清理、删除批次去重、行锁、租户隔离、容量账本、blob 引用、审计和搜索 outbox。
- `permission.invalidate_cache` 任务，消费 `permission.changed` outbox event 并失效 Redis 权限缓存 key；审计 dispatcher 只消费 `audit.*`，避免抢占权限事件。
- 搜索 ACL token builder、`search.acl_rebuild_requested` outbox event、`search.index_requested` 文件索引事件、`search.extract_requested` 文本抽取事件和 `GET /api/v1/search` 查询接口；`search.dispatch_outbox` 会从 PostgreSQL 重新加载文件、版本、blob、空间成员和节点 ACL 事实后写入 OpenSearch，不再活跃或已彻底删除的文件会删除索引文档，并在 ACL 变更后按 space 或 node 子树保守重建索引 token；当前抽取支持 UTF-8 文本类文件、PDF 可复制正文、DOCX 段落/表格文本、PPTX 文本框/表格文本和 XLSX 单元格文本，PDF 使用 `pypdf` 解析，DOCX 使用 `python-docx` 解析，PPTX 使用 `python-pptx` 解析，XLSX 使用 `openpyxl` 解析，写入 `file_versions.search_text` 后刷新索引 `content` 字段；图片 OCR 等复杂格式后续继续接入成熟开源解析工具；查询接口使用 `acl_tokens` allow 过滤、`deny_acl_tokens` 排除过滤、签名 cursor 分页、HTML 编码高亮和 `read_meta` 二次权限校验。
- 预览基础链路：上传成功后写入 `preview.render_requested` outbox event，`preview.dispatch_outbox` 消费事件并使用 Pillow 生成图片 WebP 预览产物；PDF 会通过 Poppler `pdftoppm` 在临时目录中渲染第一页 PNG，再复用 Pillow 生成 WebP；Office 文档会通过 LibreOffice headless 转换为 PDF，再复用 PDF/图片链路。产物写入私有对象存储 `previews/{tenant_id}/{node_id}/{version_id}/image.webp`；`GET /api/v1/files/{node_id}/preview` 会校验节点级 `preview` 权限并返回短期私有预览 URL。缺少 `pdftoppm` 或 `soffice` 时会标记为 `unsupported` 并写入明确错误原因，避免无意义重试；`preview.dispatch_outbox` 已配置独立 Celery 软/硬超时、速率限制、结构化失败日志和 `preview_failures_total` 指标，便于后续接入日志告警与指标看板。
- `shares`、`share_items`、`share_recipients`、`share_access_logs` 基础表和迁移；服务层支持内部分享、外链分享、提取码哈希、过期时间、访问/下载次数上限和撤销状态。
- 分享创建会校验 root 节点和全部分享项的节点级 `share` 权限，分享项必须与 root 节点属于同一空间；外链原始 token 只返回一次，数据库只保存全局唯一 token hash，提取码只保存 Argon2id hash。
- 分享创建和撤销会写入 `share.created` / `share.revoked` 审计事件和 `audit.share.*` outbox event；`POST /api/v1/shares`、`GET /api/v1/shares/{share_id}`、`POST /api/v1/shares/{share_id}/revoke` 已接入 Cookie Session、CSRF 和创建者边界；`POST /api/v1/public/shares/access` 已接入 `tenant_slug`、外链 token、提取码、状态、过期、访问次数校验，以及 IP 总量和 `token + IP` 维度限流，会带租户边界查询分享、原子增加 `view_count` 并写入 `share_access_logs`；`POST /api/v1/public/shares/download` 已接入外链下载，会校验分享状态、提取码、下载权限、分享项范围、文件当前版本和下载次数限制，原子增加 `download_count`，返回短期私有对象下载 URL，并写入 `share_access_logs` 和 `share.external.downloaded` 审计。
- 文件下载预签名 URL 接口，按当前文件版本生成短期私有对象下载地址。
- 下载成功和拒绝均写入 `file.downloaded` 审计事件与 outbox event。
- 管理员 seed 脚本。

## 认证接口

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/session/rotate`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`

登录成功后，后端写入 `drive_session` HttpOnly Cookie 和可由前端读取的 `drive_csrf` Cookie；所有 `POST`、`PUT`、`PATCH`、`DELETE` 请求都需要把 `drive_csrf` 的值通过 `X-CSRF-Token` 请求头回传。接口不返回 JWT，也不支持 `Authorization: Bearer` 或旧 `/auth/refresh` 兼容路径。

默认管理员由 `.env` 中的 `DRIVE_ADMIN_*` 配置控制。首次本地启动后运行 `uv run python -m scripts.seed_admin` 创建管理员，并在首次登录后尽快修改默认密码。

## 管理员接口

- `GET /api/v1/admin/audit-logs`

审计查询仅允许当前租户的系统管理员访问。可使用 `actor_id`、`actor_type`、`action`、`resource_type`、`resource_id`、`result`、`risk_level`、`request_id`、`created_from`、`created_to`、`cursor` 和 `page_size` 组合筛选；结果按 `created_at DESC, id DESC` 返回。普通用户访问、非法时间范围和成功查询都会写入 `admin.audit_logs.queried` 审计事件。

## 空间和文件树接口

- `POST /api/v1/spaces`
- `GET /api/v1/spaces`
- `GET /api/v1/spaces/{space_id}/members`
- `POST /api/v1/spaces/{space_id}/members`
- `PATCH /api/v1/spaces/{space_id}/members/{user_id}`
- `DELETE /api/v1/spaces/{space_id}/members/{user_id}`
- `GET /api/v1/files/{node_id}/acl`
- `POST /api/v1/files/{node_id}/acl`
- `PATCH /api/v1/files/{node_id}/acl/{entry_id}`
- `DELETE /api/v1/files/{node_id}/acl/{entry_id}`
- `POST /api/v1/files/folders`
- `GET /api/v1/files?space_id=...&parent_id=...`
- `PATCH /api/v1/files/{node_id}`
- `POST /api/v1/files/{node_id}/move`
- `DELETE /api/v1/files/{node_id}`
- `DELETE /api/v1/files/{node_id}/purge`
- `POST /api/v1/files/{node_id}/restore`
- `GET /api/v1/files/{node_id}/preview`
- `GET /api/v1/search?q=...&limit=...&cursor=...`

当前空间和文件树接口已使用 `PermissionService` 的空间级成员角色和节点 ACL 检查：空间列表按 `space_members` 成员关系返回；成员管理需要 `manage`/`grant`，文件列表需要 `list`，创建文件夹和上传需要 `upload`，重命名和移动需要 `update`，删除和彻底删除需要 `delete`，恢复需要 `restore`。节点 ACL 创建请求使用 `subject_type` 和 `subject_id`，`subject_type` 支持 `user`、`department`、`group`；权限判断会通过 org 模块展开当前用户所属活跃部门和用户组，ACL 显式 deny 仍优先于 allow 和空间角色。文件列表会复用已校验的父路径，为当前页子节点批量评估 `list`、`read_meta`、`preview`、`download`、`upload`、`update`、`delete`、`restore`、`share`、`grant`、`manage` 常用动作，并在每个节点的 `permissions` 字段返回结果；高危操作仍在对应接口二次调用权限引擎确认。成员变更会递增 `spaces.permission_version` 并写入 `permission.space_member.*` 审计事件；节点 ACL 变更会递增 `nodes.permission_version` 并写入 `permission.node_acl.*` 审计事件；两类权限变更都会写入 `permission.changed` outbox event，payload 包含 scope、resource_id、permission_version、reason、主体信息和必要时的 affected_user_id。`permission.invalidate_cache` 会消费该事件并删除匹配的 Redis 权限缓存 key；部门/用户组 ACL 变更当前保守失效租户内节点权限缓存。缓存只用于加速，不作为权限事实来源。权限变更还会写入独立的 `search.acl_rebuild_requested` outbox event，由 `search.dispatch_outbox` 按 space 或 node 子树保守重建 OpenSearch 索引 token；文件重命名、移动、删除、恢复和彻底删除会写入 `search.index_requested`，由搜索 worker 重新加载 PostgreSQL 事实后更新或删除文件索引。上传完成会写入 `search.extract_requested`，搜索 worker 对 MIME 或扩展名判定为文本类、PDF、DOCX、PPTX 或 XLSX 的小文件读取对象内容，UTF-8 文本直接解码，PDF 使用 `pypdf` 抽取可复制正文，DOCX 使用 `python-docx` 抽取段落和表格文本，PPTX 使用 `python-pptx` 抽取文本框和表格文本，XLSX 使用 `openpyxl` 抽取单元格文本，更新 `file_versions.search_status/search_error/search_text`，并刷新索引 `content` 字段；不支持的格式、OOXML zip 归档超限或抽取后正文超限标记为 `skipped`，解码或解析失败标记为 `failed` 但不重试，存储读取失败标记为 `failed` 并由 outbox 退避重试。搜索查询接口会先根据当前用户的空间成员角色、用户主体、部门主体和用户组主体构建查询 token，并在 OpenSearch 查询层同时加入租户、未删除、`acl_tokens` allow 和 `deny_acl_tokens` 排除过滤；分页使用绑定查询词和排序值的签名 cursor，响应返回 `next_cursor`；命中文件返回 HTML 编码的 `<mark>` 高亮片段。返回前再按 PostgreSQL 节点路径调用 `PermissionService.can_access_node(..., action=read_meta)` 二次校验，避免 ACL 变更后索引尚未刷新时泄露文件名和元数据。搜索查询已接入 `search.query` 基础限流，按 `tenant + user + search + IP` 维度计数；触发限流时返回 HTTP 429 和 `RATE_LIMITED`。

文件夹名称会进行 Unicode NFC 归一化并去除首尾空白，禁止 `/`、`\`、NUL、控制字符和路径穿越片段。同一目录下未删除节点的名称由数据库唯一索引兜底，根目录由 `tenant_id + space_id` 唯一索引兜底。

根目录不允许重命名、移动、删除或彻底删除。删除到回收站会同步标记当前活跃子树，不释放容量；恢复只恢复同一批删除的子树，避免误恢复更早单独删除的节点。彻底删除只允许作用于已在回收站的节点，会删除该节点下全部已删除后代的节点元数据和文件版本，扣减相关 blob 引用计数，按版本大小合计释放空间容量并写入 `file.purged` 审计。当前目录删除、恢复和彻底删除仍是同步遍历，适合 Sprint 2/3 骨架和普通目录验证；大目录后续需要改为后台任务或引入 `deleted_root_id` 等冗余状态来避免长事务。

## 分享接口

- `POST /api/v1/shares`
- `GET /api/v1/shares/{share_id}`
- `POST /api/v1/shares/{share_id}/revoke`
- `POST /api/v1/public/shares/access`
- `POST /api/v1/public/shares/download`

创建分享接口支持 `internal` 和 `external` 类型。内部分享必须指定用户、部门或用户组接收人；外链分享会返回一次性明文 `raw_token`，数据库只保存全局唯一 token hash。分享创建会检查 root 节点和全部分享项的 `share` 权限，分享项必须与 root 节点属于同一空间。详情和撤销当前只允许创建者访问。公开外链访问接口不需要登录，请求体需要提供 `tenant_slug`、`raw_token` 和可选 `passcode`；后端先解析租户，再按 `tenant_id + token_hash` 查询外链，校验状态、过期时间、提取码和访问次数限制，并按 IP 总量和 `token + IP` 维度限流。校验通过后原子增加 `view_count`，返回分享基础信息和分享项节点 ID，并写入 `share_access_logs` 和 `share.external.accessed` 审计。

公开外链下载接口不需要登录，请求体需要提供 `tenant_slug`、`raw_token`、`node_id` 和可选 `passcode`。后端按外链 token 和租户边界加载分享，校验状态、过期时间、提取码、分享权限是否为 `download`、请求节点是否为 root 或分享项、节点是否仍是同一空间内的文件、当前版本和 blob 是否存在；通过后用数据库条件 update 原子增加 `download_count`，再通过 `StorageAdapter.presign_download` 返回短期私有对象下载 URL。外链下载限流同时覆盖 IP 总量和 `token + node + IP` 维度；成功和失败都会记录 `share_access_logs`，审计 actor_type 为 `external`。当前公开下载使用预签名 URL，后端 Range 代理、水印导出和更细的 external subject 策略将在高密级下载或预览链路中继续补齐。

## 上传接口

- `POST /api/v1/uploads/init`
- `GET /api/v1/uploads/{session_id}`
- `POST /api/v1/uploads/{session_id}/parts/{part_no}/presign`
- `POST /api/v1/uploads/{session_id}/complete`
- `POST /api/v1/uploads/{session_id}/abort`

上传初始化请求包含 `space_id`、`parent_id`、`file_name`、`size_bytes`、`content_hash`、`hash_algo`、`mime_type` 和 `conflict_policy`。当前 `hash_algo` 仅支持 `sha256`，不支持的算法返回 `UPLOAD_HASH_ALGO_UNSUPPORTED`；当前 `conflict_policy` 仅支持 `fail`，同目录同名返回 `NODE_NAME_EXISTS`。

当 `file_blobs` 已存在同租户、同 hash 算法、同内容 hash、同大小且状态为 `active` 的对象时，初始化接口返回 `mode=instant`，并直接创建文件节点和首个版本。若同 hash blob 正在 `deleting`，接口返回 `BLOB_DELETING`，客户端应稍后重试。当未命中可复用 blob 时，接口创建对象存储 multipart upload 和数据库上传会话，返回 `mode=multipart`、`session_id`、`part_size_bytes`、`total_parts` 和 `expires_at`。

完成 multipart 上传时，客户端提交全部分片的 `part_no`、`etag` 和可选 `size_bytes`。服务端先将会话推进到 `completing`，再调用对象存储合并分片；合并后先检查对象大小，再计算服务端 `sha256` 并与初始化时的 `content_hash` 比对。二者都匹配后，若同租户同 hash、同大小 active blob 已存在，会原子增加引用计数、复用已有 blob 并清理本次 `uploads/...` 临时对象；若不存在，会先复制到 `objects/{tenant_id}/{hash_prefix}/{content_hash}`，再写入 blob、文件节点、版本、分片记录、容量流水和上传完成审计，提交后清理临时对象。若同 hash blob 正在 `deleting`，complete 返回 `BLOB_DELETING` 并标记上传失败，避免复用或新建被垃圾回收占用唯一约束的 blob。hash 不匹配返回 `UPLOAD_HASH_MISMATCH`，上传会话标记为 `failed`，写入 `upload.failed` 审计，不创建文件版本和容量流水。重复调用已完成的 complete 会返回同一完成结果。abort 会将未完成会话标记为 `aborted`，并调用对象存储取消 multipart upload。

过期上传由 Celery 任务 `upload.expire_sessions` 扫描处理，可传入 `tenant_id`、`limit` 和 `request_id`。任务会按租户查找已过期的 `initiated`、`uploading`、`completing` 会话，先标记为 `expired`，再最佳努力调用对象存储取消 multipart upload，并仅删除 `uploads/...` 临时对象，避免误删最终 `objects/...` 内容。对象存储清理失败不会回滚会话终态，会写入 `upload.expired` 审计 metadata 和任务统计中的 `storage_errors`。

上传初始化和分片签名已接入基础限流。上传初始化按 `tenant + user` 维度计数；分片签名按 `tenant + user + upload session` 维度计数。触发限流时返回 HTTP 429，错误码为 `RATE_LIMITED`，错误详情包含 `action`、`limit`、`window_seconds` 和 `retry_after_seconds`。

对象存储和上传策略由以下环境变量控制：

- `DRIVE_S3_ENDPOINT_URL`
- `DRIVE_S3_BUCKET`
- `DRIVE_S3_ACCESS_KEY_ID`
- `DRIVE_S3_SECRET_ACCESS_KEY`
- `DRIVE_S3_REGION`
- `DRIVE_UPLOAD_SESSION_TTL_MINUTES`
- `DRIVE_TRASH_RETENTION_DAYS`
- `DRIVE_TRASH_CLEANUP_INTERVAL_SECONDS`
- `DRIVE_UPLOAD_PART_SIZE_BYTES`
- `DRIVE_UPLOAD_PRESIGN_EXPIRES_SECONDS`
- `DRIVE_DOWNLOAD_PRESIGN_EXPIRES_SECONDS`
- `DRIVE_DEFAULT_SPACE_QUOTA_BYTES`
- `DRIVE_RATE_LIMIT_ENABLED`
- `DRIVE_LOGIN_IP_RATE_LIMIT_COUNT`
- `DRIVE_LOGIN_ACCOUNT_RATE_LIMIT_COUNT`
- `DRIVE_LOGIN_RATE_LIMIT_WINDOW_SECONDS`
- `DRIVE_UPLOAD_INIT_RATE_LIMIT_COUNT`
- `DRIVE_UPLOAD_INIT_RATE_LIMIT_WINDOW_SECONDS`
- `DRIVE_UPLOAD_PART_PRESIGN_RATE_LIMIT_COUNT`
- `DRIVE_UPLOAD_PART_PRESIGN_RATE_LIMIT_WINDOW_SECONDS`
- `DRIVE_DOWNLOAD_PRESIGN_RATE_LIMIT_COUNT`
- `DRIVE_DOWNLOAD_PRESIGN_RATE_LIMIT_WINDOW_SECONDS`
- `DRIVE_SEARCH_QUERY_RATE_LIMIT_COUNT`
- `DRIVE_SEARCH_QUERY_RATE_LIMIT_WINDOW_SECONDS`
- `DRIVE_SHARE_EXTERNAL_ACCESS_RATE_LIMIT_COUNT`
- `DRIVE_SHARE_EXTERNAL_ACCESS_RATE_LIMIT_WINDOW_SECONDS`
- `DRIVE_SHARE_EXTERNAL_DOWNLOAD_RATE_LIMIT_COUNT`
- `DRIVE_SHARE_EXTERNAL_DOWNLOAD_RATE_LIMIT_WINDOW_SECONDS`
- `DRIVE_SEARCH_TEXT_EXTRACT_MAX_BYTES`
- `DRIVE_PREVIEW_MAX_SOURCE_BYTES`
- `DRIVE_PREVIEW_IMAGE_MAX_SIDE`
- `DRIVE_PREVIEW_OFFICE_COMMAND`
- `DRIVE_PREVIEW_OFFICE_MAX_PDF_BYTES`
- `DRIVE_PREVIEW_PDF_COMMAND`
- `DRIVE_PREVIEW_PDF_DPI`
- `DRIVE_PREVIEW_PDF_MAX_RENDERED_BYTES`
- `DRIVE_PREVIEW_COMMAND_TIMEOUT_SECONDS`
- `DRIVE_PREVIEW_TASK_SOFT_TIME_LIMIT_SECONDS`
- `DRIVE_PREVIEW_TASK_TIME_LIMIT_SECONDS`
- `DRIVE_PREVIEW_TASK_RATE_LIMIT`
- `DRIVE_PREVIEW_PRESIGN_EXPIRES_SECONDS`

当前上传接口已通过 `PermissionService` 校验父目录节点级 `upload` 权限；初始化和 multipart complete 都会重新检查，避免会话创建后权限收紧仍可完成上传。容量初版按空间维度实现：空间创建时建立默认容量账户，上传初始化会快速检查空间剩余容量，秒传和 multipart complete 创建文件版本时通过原子 update 增加 `quota_accounts.used_bytes`，并写入 `quota_ledger`。删除到回收站不释放容量；彻底删除回收站节点时通过原子 update 扣减 `quota_accounts.used_bytes`，并写入 `reason=file_purged`、`ref_type=node` 的负向容量流水。容量校准任务 `quota.reconcile_space_usage` 使用 PostgreSQL 中的文件版本记录作为事实来源，默认按 `limit` 批大小和 cursor 扫完整个租户，只报告空间容量快照和账本漂移；传入 `repair=true` 时会修复缺失的空间容量账户，已有账户修复前会锁定账户行并重新聚合实际用量和账本合计，再校准 `quota_accounts.used_bytes`，仅按最新差额写入 `reason=quota_reconciled` 账本流水和 `quota.reconciled` 系统审计。彻底删除接口不在用户请求事务中同步删除最终对象；`file.cleanup_unreferenced_blobs` 会扫描 active、`ref_count=0` 且无 `file_versions` 引用的 blob，先标记为 `deleting`，再删除对象存储内容和 DB 元数据。对象存储删除失败会恢复为 `active` 并计入 `storage_errors`。`file.cleanup_orphaned_objects` 用于对象复制成功但 DB 最终化失败后的反向治理，只扫描受控 `objects/{tenant_id}/{hash_prefix}/{sha256}` key，跳过非受控 key，默认 dry-run，显式 `dry_run=False` 才删除对象；删除成功、失败和 dry-run 计划均写入系统审计，审计 metadata 不保存原始 storage key，并通过 `orphan_object_cleanup_total{status}` 暴露扫描、计划、清理、失败和跳过计数。用户/租户维度配额将在后续步骤补齐。

回收站自动清理由 `file.cleanup_expired_trash` 承担，默认使用 `DRIVE_TRASH_RETENTION_DAYS=30` 和 `DRIVE_TRASH_CLEANUP_INTERVAL_SECONDS=3600`。查询使用 `idx_nodes_trash_cleanup(tenant_id, is_deleted, deleted_at, id)`，只把没有“同删除时间、同删除人父节点”的过期节点视为删除批次根节点，避免一个目录子树被重复领取。任务锁定根节点和子树，删除全部版本与节点，按版本大小释放空间容量并写 `file_purged` 账本，扣减 blob 引用，发送 `reason=trash_retention_expired` 的搜索事件，记录 `file.trash.retention_purged` 系统审计，并通过 `trash_cleanup_total{status}`、`trash_cleanup_released_bytes_total` 暴露结果。普通目录仍在单个事务内处理；超大目录后台分片属于 `BE-046`。

维护任务可通过 Celery 任务调用：

- `quota.reconcile_space_usage(tenant_id=None, limit=100, repair=False, request_id=None, scan_all=True, max_items=1000)`
- `file.cleanup_expired_trash(tenant_id=None, limit=100, retention_days=None, request_id=None)`
- `file.cleanup_unreferenced_blobs(tenant_id=None, limit=100, request_id=None)`
- `file.cleanup_orphaned_objects(tenant_id=None, limit=100, after_storage_key=None, dry_run=True, request_id=None, scan_all=True)`
- `permission.invalidate_cache(batch_size=None)`

## 下载接口

- `GET /api/v1/files/{node_id}/download`

下载接口基于 `nodes.current_version_id` 查询当前版本和 blob，返回 `download_url`、`expires_at`、`file_name`、`version_id`、`size_bytes`、`mime_type` 和额外 `headers`。S3/MinIO 适配器会使用 `ResponseContentDisposition` 设置下载文件名，并同时提供 ASCII `filename` 和 UTF-8 `filename*`。

下载预签名已接入基础限流，按 `tenant + user + node + IP` 维度计数。触发限流时返回 HTTP 429，错误码为 `RATE_LIMITED`。

当前下载接口已通过 `PermissionService` 校验节点级 `download` 权限：非空间成员、空间角色不足或节点 ACL deny 均返回统一的 `NODE_NOT_FOUND`，目录节点返回 `NODE_NOT_FILE`，缺失当前版本返回 `FILE_VERSION_NOT_FOUND`。下载成功与拒绝都会写入 `file.downloaded` 审计事件；后续会把搜索 ACL 更新接入同一权限事实。
