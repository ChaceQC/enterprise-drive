# Windows 11 Docker 正式部署说明

> 适用项目版本：`v0.2.0`
>
> 当前可验证基线：Windows 本机 HTTP `18080/19000`；公网 TLS 为后续上线任务。

## 1. 部署目标

企业网盘正式部署宿主机统一为 Windows 11，使用 Docker Desktop 的 WSL2 后端和 Linux containers。

部署源文件：

- `compose.windows.yml`：仓库根目录的正式编排清单，也是唯一正式部署入口。
- `.env.windows.example`：正式环境变量模板。
- `.env.windows`：实际环境配置，不提交 Git。
- `deploy/windows/manage.ps1`：Windows PowerShell 管理入口。
- `backend/docker-compose.yml`：只用于本地依赖开发，不参与正式部署。

Kubernetes、Linux systemd 可以作为未来迁移方案，但不属于当前默认部署和验收范围。

## 2. 宿主机准备

最低要求：

- Windows 11。
- 已启用虚拟化和 WSL2。
- Docker Desktop 使用 WSL2 engine。
- Docker Desktop 切换到 Linux containers。
- Docker Compose v2 可用。
- PowerShell 7 或 Windows PowerShell 5.1。
- 为 Docker Desktop 预留至少 4 个 CPU、8 GiB 内存和充足磁盘；启用 Preview/OpenSearch 后建议按真实并发继续上调。

只读检查：

```powershell
wsl --status
docker version
docker compose version
docker info --format '{{.OSType}}'
```

`docker info` 的操作系统类型应为 `linux`。

## 3. 服务拓扑

正式 Compose 至少包含：

| 服务 | 职责 | 宿主端口 |
| --- | --- | --- |
| `gateway` | Nginx 入口、API/存储分流、Range、安全响应头；公网阶段补 TLS | 唯一允许发布端口 |
| `api` | FastAPI API | 不发布 |
| `migration` | 一次性 Alembic migration | 不发布 |
| `seed` | migration 后一次性创建或校准初始管理员 | 不发布 |
| `worker-preview` | 图片、PDF、Office 预览 | 不发布 |
| `worker-search` | 文本抽取、索引写入 | 不发布 |
| `worker-audit` | 审计 outbox | 不发布 |
| `worker-permission` | 权限缓存失效 | 不发布 |
| `worker-maintenance` | 生命周期与治理任务 | 不发布 |
| `beat` | 独立运行 Celery beat，负责周期任务调度 | 不发布 |
| `postgres` | PostgreSQL 事实库 | 不发布 |
| `redis` | 缓存、限流、Celery broker/result backend | 不发布 |
| `minio` | 私有 S3 兼容对象存储 | 不发布 |
| `minio-init` | 一次性创建私有 bucket 并确认匿名访问关闭 | 不发布 |
| `opensearch` | 可重建搜索索引 | 不发布 |

默认本机入口：

- API：`http://localhost:18080`
- S3 外部预签名端点：`http://localhost:19000`

两个入口都由同一个 `gateway` 容器发布。MinIO、API 等内部服务本身不配置宿主端口。

默认 `.env.windows.example` 把两个入口绑定到 `127.0.0.1`。需要局域网访问时，才把 `DRIVE_GATEWAY_BIND` 和 `DRIVE_STORAGE_GATEWAY_BIND` 改为 `0.0.0.0`，同时把 S3 外部端点改成客户端可解析的 Windows 主机名或 IP、收紧 CORS/Trusted Hosts，并只为 gateway 的两个端口配置 Windows 防火墙规则。

公网域名目标：

- API：`https://drive.example.com`
- S3 外部端点：`https://storage.example.com`

当前 Nginx 工件只实现 HTTP 本机入口和可配置 Host/端口，尚未包含证书挂载或 TLS server block。公网发布前必须先补充受信证书、TLS server 配置、HTTP 到 HTTPS 跳转和证书续期方案，再让 gateway 发布 `80/443`，按 Host 分流 API 与存储流量，并在转发到 MinIO 时保留原始 Host。

```text
Windows 11
  |
  +-- gateway (唯一宿主端口发布者)
        |
        +-- api
        +-- minio
        |
        +-- Compose internal network
              +-- postgres
              +-- redis
              +-- opensearch
              +-- workers
              +-- beat
```

## 4. 环境变量

首次部署：

```powershell
Copy-Item .env.windows.example .env.windows
```

必须修改：

- 应用 secret。
- PostgreSQL 密码。
- Redis 密码。
- MinIO access key/secret key。
- OpenSearch 初始管理员密码。
- 管理员初始密码。
- CORS origins。
- Trusted Hosts。
- API 外部地址。
- S3 外部地址。
- 公网 HTTPS 阶段所需的 TLS 域名、证书挂载和续期配置；当前基线尚未实现。

容器内连接使用 Compose 服务 DNS，例如：

```dotenv
DRIVE_GATEWAY_BIND=127.0.0.1
DRIVE_GATEWAY_PORT=18080
DRIVE_STORAGE_GATEWAY_BIND=127.0.0.1
DRIVE_STORAGE_GATEWAY_PORT=19000
DRIVE_SERVER_NAME=localhost
DRIVE_STORAGE_SERVER_NAME=storage.localhost
DRIVE_DATABASE_URL=postgresql+asyncpg://drive:PASSWORD@postgres:5432/enterprise_drive
DRIVE_DATABASE_POOL_MODE=queue
DRIVE_DATABASE_POOL_SIZE=3
DRIVE_DATABASE_MAX_OVERFLOW=2
DRIVE_DATABASE_POOL_TIMEOUT_SECONDS=10
DRIVE_REDIS_URL=redis://:PASSWORD@redis:6379/0
DRIVE_CELERY_BROKER_URL=redis://:PASSWORD@redis:6379/1
DRIVE_CELERY_RESULT_BACKEND=redis://:PASSWORD@redis:6379/2
DRIVE_OPENSEARCH_URL=http://opensearch:9200
DRIVE_S3_ENDPOINT_URL=http://minio:9000
DRIVE_S3_PUBLIC_ENDPOINT_URL=http://localhost:19000
```

写入 PostgreSQL 或 Redis URL 的密码若包含 `@`、`:`、`/`、`#`、`?` 等保留字符，必须先进行 URL 百分号编码，并保证独立的 `POSTGRES_PASSWORD`、`REDIS_PASSWORD` 与连接 URL 中的解码后密码一致。

公网 TLS 配置完成后把外部端点改为：

```dotenv
DRIVE_GATEWAY_BIND=0.0.0.0
DRIVE_STORAGE_GATEWAY_BIND=0.0.0.0
DRIVE_SERVER_NAME=drive.example.com
DRIVE_STORAGE_SERVER_NAME=storage.example.com
DRIVE_S3_PUBLIC_ENDPOINT_URL=https://storage.example.com
```

以上变量只表达绑定地址、Host 和外部 URL，不能单独完成公网 HTTPS。公网阶段还需要受控的 Compose/gateway 配置调整：移除本机独立 `19000` 映射，使用同一 gateway 的 Host 分流入口，挂载受信证书并新增 TLS server block，再映射 `80/443` 和执行 HTTPS 实测。

### S3 内外端点分离

- `DRIVE_S3_ENDPOINT_URL` 只供 API/Worker 在 Compose 网络内访问 MinIO。
- `DRIVE_S3_PUBLIC_ENDPOINT_URL` 用于生成浏览器可访问的预签名 URL。
- 默认外部端点是 `http://localhost:19000`。
- 公网 TLS 配置完成后使用独立 Host，例如 `https://storage.example.com`。
- 外部端点不使用 `/s3` 等 base path。MinIO client 和 SigV4 会把 Host、路径、查询参数纳入签名，路径前缀重写会导致签名不匹配。
- gateway 转发存储请求时必须保留原始 Host、查询字符串、HTTP 方法和请求体。
- MinIO Console 不对宿主机发布；运维应通过容器内 CLI 或受控管理流程进行。

## 5. PowerShell 管理入口

宿主机操作统一通过：

```powershell
.\deploy\windows\manage.ps1 <command>
```

当前管理脚本提供以下能力：

| 命令 | 目标 |
| --- | --- |
| `config [-Quiet]` | 使用示例或实际环境文件校验 Compose 渲染结果 |
| `up [-Build]` | 启动服务；`-Build` 会先构建镜像，migration、MinIO 初始化和 seed 由 Compose 依赖链执行 |
| `status` | 查看全部容器与健康状态 |
| `logs [-Service NAME] [-Tail N]` | 查看全部或指定服务日志 |
| `down` | 停止服务并保留 named volumes |
| `down -Volumes` | 显式销毁 named volumes，仅限确认备份后的环境清理 |

脚本默认 `down` 不删除 volumes；`-Volumes` 是显式破坏性开关。`.env.windows`、证书私钥或备份内容不得写入 Git。

底层 Compose 命令应固定使用：

```powershell
docker compose -f compose.windows.yml --env-file .env.windows <command>
```

## 6. 健康检查与启动依赖

### `/healthz`

- 只表示 API 进程存活。
- 不执行复杂外部依赖检查。
- 用于进程 liveness。

### `/readyz`

- 必须通过应用实际数据库连接执行轻量 PostgreSQL 探针，例如 `SELECT 1`。
- 数据库连接成功返回 2xx。
- 数据库连接失败、连接池不可用或探针超时返回 `503`。
- 不得只返回固定 JSON 或只检查配置字符串。
- Compose 的 API healthcheck 和 gateway 上游接流量条件都以 `/readyz` 为准。

推荐启动顺序：

1. PostgreSQL、Redis、MinIO、OpenSearch 启动并通过各自 healthcheck。
2. `migration` 一次性服务执行成功。
3. API 启动并通过真实 `/readyz`。
4. gateway 开始代理 API。
5. 启动各职责 Worker。
6. 最后启动单实例 `beat` 服务。

### 数据库连接池边界

- API 使用 SQLAlchemy QueuePool，Windows Compose 默认 `pool_size=3`、`max_overflow=2`、等待超时 10 秒；每个 Uvicorn worker 都有独立连接池。
- Celery Worker 的同步任务入口会通过 `asyncio.run()` 为每次任务建立事件循环。Worker 必须设置 `DRIVE_DATABASE_POOL_MODE=null`，让每次数据库连接在当前任务事件循环内创建并关闭。
- 不要让 Celery Worker 跨多个 `asyncio.run()` 事件循环复用 asyncpg QueuePool，否则会出现连接累积、`Future attached to a different loop` 或 PostgreSQL `too many clients`。
- migration、seed 是一次性进程；数据库连接池参数仍应通过环境变量统一管理，不在代码或 command 中硬编码。

## 7. Celery Worker 与 Beat

队列至少按职责拆分：

- `preview`
- `search`
- `audit`
- `permission`
- `maintenance`

Preview Worker 不能和 audit/permission 队列混跑。

`beat` 服务中的 Celery beat 只能运行一个有效调度实例，避免重复触发周期任务。正式计划至少覆盖：

- `upload.expire_sessions`
- `file.cleanup_unreferenced_blobs`
- `file.cleanup_orphaned_objects`
- `quota.reconcile_space_usage`
- 后续接入的过期分享、预览产物和其他生命周期治理任务

Beat 使用 UTC。当前 schedule 文件位于容器临时目录，可由静态配置重建；任务事实和执行结果仍以数据库、审计和任务自身状态为准。每个维护任务必须幂等，不能仅依赖 beat 单实例保证。

## 8. Preview Worker

Preview Worker 镜像必须包含：

- LibreOffice `soffice`
- Poppler `pdftoppm`
- Pillow 所需系统库
- 常用中文字体

资源基线：

- `cpus: 2.0`
- `mem_limit: 3g`
- 默认临时目录上限 `1 GiB`，通过 `PREVIEW_TMPFS_SIZE` 调整
- `--concurrency=1`
- `--max-tasks-per-child=20`
- 外部命令超时、Celery soft time limit、hard time limit 和 rate limit

临时目录不与 PostgreSQL、MinIO、OpenSearch 数据卷共用。详细要求见 `docs/deployment-preview-worker.md`。

容器内验证：

```powershell
docker compose -f compose.windows.yml --env-file .env.windows exec worker-preview soffice --version
docker compose -f compose.windows.yml --env-file .env.windows exec worker-preview pdftoppm -v
```

## 9. Named Volumes 与数据边界

正式部署至少持久化：

- PostgreSQL 数据。
- Redis 数据。
- MinIO 对象。
- OpenSearch 索引。

原则：

- named volumes 由 Compose 管理，不写入 Git 工作区。
- 停止、重建 API/Worker/gateway 不删除数据卷。
- `docker compose down` 默认保留数据。
- `docker compose down -v` 只允许在明确销毁环境并已确认备份后手工执行。
- OpenSearch 索引以 PostgreSQL 为事实来源，仍应保留重建索引脚本和演练流程。
- Preview 临时目录属于可清理数据，不作为原文件或唯一预览事实来源。

## 10. Gateway 安全边界

gateway 必须负责：

- 当前默认本机 HTTP `18080/19000` 入口。
- 公网发布前新增受信证书挂载、TLS server block、HTTP 到 HTTPS 跳转和证书续期，再映射 `80/443`。
- API 与存储请求分流。
- 保留存储请求原始 Host。
- WebSocket upgrade。
- HTTP Range。
- 上传大小和超时。
- 真实客户端 IP 头。
- 安全响应头。
- 禁止代理 MinIO Console。

内部服务不得配置宿主 `ports`。可使用 `expose` 表达容器内端口，但安全边界依赖 Compose 网络和 gateway。

生产环境还应：

- 使用强随机 secret 和独立服务密码。
- 定期轮换 MinIO、数据库和管理员凭据。
- 保持 bucket 私有。
- 关闭 FastAPI debug。
- 配置准确的 CORS 和 Trusted Hosts。
- 运行镜像使用非 root 用户。
- 固定镜像版本，不长期依赖 `latest`。
- 限制 Windows 防火墙入站规则。
- 保护 `.env.windows`、TLS 私钥和备份目录的 NTFS 权限。

当前 TLS 边界：

- 当前提交的 gateway 配置只覆盖 HTTP `18080/19000`。
- 证书挂载、TLS server block、自动续期和公网 HTTPS 验收属于上线前后续任务。
- 在这些任务完成前，不得把当前本机 HTTP 基线描述成已完成公网 TLS 部署。

## 11. 备份

更新前至少备份：

1. PostgreSQL：一致性 `pg_dump`。
2. MinIO：对象镜像或版本化备份。
3. `.env.windows`：加密保存，不进入仓库。
4. TLS 证书和 gateway 配置。
5. 当前镜像 tag、Compose 文件版本、migration 版本。

Redis 主要保存缓存、限流和队列状态，不作为权限、容量、文件或审计事实来源。OpenSearch 索引可从 PostgreSQL 与对象存储重建，但仍需记录索引重建步骤和耗时。

备份要求：

- 输出到专用 Windows 目录或备份卷。
- 设置保留期和容量告警。
- 备份文件加密。
- 定期在隔离环境执行恢复演练。
- 恢复 PostgreSQL 与 MinIO 时保持同一业务时间点，避免元数据和对象版本错位。

## 12. 发布与更新

推荐流程：

```powershell
.\deploy\windows\manage.ps1 config -Quiet
# 按本章备份要求完成 PostgreSQL、MinIO、配置和证书备份
.\deploy\windows\manage.ps1 up -Build
.\deploy\windows\manage.ps1 status
```

发布检查：

- CI 的 ruff、format、mypy、pytest 通过。
- `docker compose ... config` 通过。
- 应用镜像构建通过。
- migration 一次性服务退出码为 0。
- `/readyz` 真实数据库探针通过。
- gateway 的 API 与 S3 外部端点可访问。
- Worker 已连接预期队列。
- `beat` 只有一个有效实例。
- Preview 工具版本可读取。
- 容器无持续重启。
- Windows 宿主磁盘空间正常。

## 13. 回滚

应用回滚：

1. 停止 gateway 接收新流量或进入维护窗口。
2. 切回上一可用镜像 tag 和上一版 `compose.windows.yml`。
3. 保留 named volumes。
4. 启动 API 并等待 `/readyz`。
5. 再启动 gateway、Worker 和 beat。
6. 验证 API、下载、上传、队列和审计。

数据库原则：

- migration 默认向前兼容。
- 应用回滚不依赖自动回滚 DDL。
- 破坏性 migration 必须提前使用影子字段、双写和分阶段删除。
- 数据库备份恢复只在明确维护窗口执行。
- Worker payload 至少兼容一个旧版本。

## 14. 验收命令

静态质量：

```powershell
Set-Location backend
uv sync --all-extras --dev
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest
uv run alembic upgrade head --sql
Set-Location ..
```

Compose：

```powershell
Copy-Item .env.windows.example .env.windows
docker compose -f compose.windows.yml --env-file .env.windows config
docker compose -f compose.windows.yml --env-file .env.windows build
docker compose -f compose.windows.yml --env-file .env.windows up -d
docker compose -f compose.windows.yml --env-file .env.windows ps -a
docker compose -f compose.windows.yml --env-file .env.windows logs --no-color --tail 200
```

入口：

```powershell
Invoke-WebRequest http://localhost:18080/healthz
Invoke-WebRequest http://localhost:18080/readyz
```

对象存储应通过真实预签名 PUT/GET 集成测试验证 `http://localhost:19000`，不能只访问 MinIO 根路径判断成功。

内部服务端口检查：

```powershell
Get-NetTCPConnection -State Listen |
    Where-Object LocalPort -In 15432, 16379, 19200, 19600, 9000, 9001
```

正式 Compose 下不应由 PostgreSQL、Redis、OpenSearch 或 MinIO 容器发布这些宿主端口。

停止并保留数据：

```powershell
docker compose -f compose.windows.yml --env-file .env.windows down
```

停止后不得添加 `-v`。重新启动后还应验证 named volumes 中的数据保持、migration 不重复产生副作用、Worker 和 beat 恢复正常。

## 15. 常见问题

### 预签名 URL 出现签名不匹配

检查：

- `DRIVE_S3_PUBLIC_ENDPOINT_URL` 是否为 `http://localhost:19000` 或独立生产存储域名。
- 是否错误加入 `/s3` 路径前缀。
- gateway 是否保留原始 Host 和查询字符串。
- API/Worker 是否误用外部端点访问 MinIO。

### `/readyz` 返回 503

检查：

- PostgreSQL 容器 healthcheck。
- `DRIVE_DATABASE_URL` 是否使用 `postgres:5432`。
- API 是否使用受控 QueuePool，Celery Worker 是否覆盖为 `DRIVE_DATABASE_POOL_MODE=null`。
- migration 服务是否成功。
- API 日志中的连接池和 SQL 探针错误。

### Office/PDF 预览显示 unsupported

在 `worker-preview` 内检查：

```powershell
docker compose -f compose.windows.yml --env-file .env.windows exec worker-preview soffice --version
docker compose -f compose.windows.yml --env-file .env.windows exec worker-preview pdftoppm -v
```

同时检查临时目录、内存限制、任务超时和 `preview_failures_total`。

### OpenSearch 在 Docker Desktop 中频繁重启

检查 WSL2 内存、磁盘空间、OpenSearch heap 和容器日志。不要通过发布 OpenSearch 宿主端口规避内部诊断流程。
