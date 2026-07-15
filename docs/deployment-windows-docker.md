# Windows 11 Docker 正式部署说明

> 适用项目版本：`v0.4.0`
>
> 当前代码基线：Windows 本机 HTTP `18080/19000` 与公网 ACME/TLS `80/443` 双模式；真实受信证书签发和双域名 HTTPS 验收需要生产 DNS/网络环境。

## 1. 部署目标

企业网盘正式部署宿主机统一为 Windows 11，使用 Docker Desktop 的 WSL2 后端和 Linux containers。

部署源文件：

- `compose.windows.yml`：仓库根目录的正式编排清单，也是唯一正式部署入口。
- `.env.windows.example`：正式环境变量模板。
- `.env.windows`：实际环境配置，不提交 Git。
- `deploy/windows/manage.ps1`：Windows PowerShell 管理入口。
- `deploy/windows/nginx/default.conf.template`：本机 HTTP gateway。
- `deploy/windows/nginx/acme-bootstrap.conf.template`：首次证书签发期间只开放健康检查和 HTTP-01 challenge。
- `deploy/windows/nginx/tls.conf.template`：公网 TLS、HTTP 跳转和双域名 Host 分流。
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
| `gateway` | Nginx 入口、API/存储分流、Range、安全响应头、ACME challenge、TLS 与 HTTP 跳转 | 唯一允许发布端口 |
| `certbot` | `tls-tools` profile 下的一次性证书签发、检查和续期工具 | 不发布 |
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

公网 TLS 工件已经包含：

- gateway 独占宿主 `80/443`。
- ACME HTTP-01 webroot bootstrap；Certbot 本身不发布宿主端口。
- 证书、ACME webroot、Certbot work/log 独立 named volumes。
- TLS 1.2/1.3、HTTP/2、HTTP `308` 到 HTTPS 跳转。
- API/存储双域名 Host 分流、未知 Host 拒绝。
- 证书续期后的 `nginx -t` 和热重载。
- Windows 计划任务注册/删除命令。

代码侧已完成静态和本机自签名证书验证。正式公网发布仍必须让两个真实域名解析到当前 Windows 宿主，开放外部 TCP 80/443，签发受信证书，并完成真实预签名 PUT/GET、Cookie、CORS 和续期演练。

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
- 公网 HTTPS 的 API/存储域名、Certbot 邮箱、证书名、HSTS、API/MinIO CORS、Trusted Hosts、Secure Cookie 和外部 S3 HTTPS URL。

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

公网 TLS 模式把外部端点改为：

```dotenv
DRIVE_GATEWAY_BIND=0.0.0.0
DRIVE_STORAGE_GATEWAY_BIND=0.0.0.0
DRIVE_SERVER_NAME=drive.example.com
DRIVE_STORAGE_SERVER_NAME=storage.example.com
DRIVE_S3_PUBLIC_ENDPOINT_URL=https://storage.example.com
DRIVE_SESSION_COOKIE_SECURE=true
DRIVE_CORS_ORIGINS=["https://drive.example.com"]
MINIO_CORS_ALLOWED_ORIGIN=https://drive.example.com
DRIVE_TRUSTED_HOSTS=["drive.example.com","storage.example.com"]
DRIVE_TLS_GATEWAY_BIND=0.0.0.0
DRIVE_TLS_HTTP_PORT=80
DRIVE_TLS_HTTPS_PORT=443
DRIVE_TLS_CERT_NAME=enterprise-drive
DRIVE_TLS_HSTS_MAX_AGE=31536000
CERTBOT_EMAIL=ops@example.com
```

`manage.ps1 -Tls` 会用 `DRIVE_TLS_GATEWAY_BIND`、`DRIVE_TLS_HTTP_PORT`、`DRIVE_TLS_HTTPS_PORT` 覆盖本机端口，并切换到 ACME bootstrap 或 TLS 模板。公网 bind 只接受 `0.0.0.0` 或其他非回环 IPv4 地址；脚本不负责验证 DNS 解析和外部路由。不要手工同时启动本机 HTTP 和公网 TLS 两套 gateway；两种模式复用同一个 Compose service 和项目 named volumes。

### S3 内外端点分离

- `DRIVE_S3_ENDPOINT_URL` 只供 API/Worker 在 Compose 网络内访问 MinIO。
- `DRIVE_S3_PUBLIC_ENDPOINT_URL` 用于生成浏览器可访问的预签名 URL。
- 默认外部端点是 `http://localhost:19000`。
- 公网 TLS 模式使用独立 Host，例如 `https://storage.example.com`。
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
| `config -Tls [-Quiet]` | 校验公网域名格式、HTTPS S3 URL、Secure Cookie、API/MinIO CORS、Trusted Hosts 和 TLS Compose 渲染 |
| `up -Tls [-Build]` | 使用已有证书启动或更新公网 TLS gateway |
| `status` | 查看全部容器与健康状态 |
| `logs [-Service NAME] [-Tail N]` | 查看全部或指定服务日志 |
| `backup -BackupDirectory PATH -ConfigEncryptionCertificateThumbprint THUMBPRINT` | 静默 source 写入面并创建 PostgreSQL、MinIO、Redis、OpenSearch、TLS 和 CMS 环境文件备份 |
| `backup-verify -BackupPath PATH` | 校验 manifest、工件、PostgreSQL dump、隔离 tar 预扫描、精确代码/configuration lineage 及 15 个默认服务 image reference/actual image ID |
| `restore -BackupPath PATH` | 把已校验备份恢复到不同且已停止的 Compose project，支持受限 ACL ForceRestore rollback |
| `tls-init -Tls [-TlsEmail EMAIL] [-TlsStaging]` | 用 ACME webroot bootstrap 首次签发双域名证书并切换到 TLS gateway |
| `tls-renew -Tls [-ForceRenewal]` | 执行 Certbot 续期，随后校验并热重载 Nginx |
| `tls-certificates -Tls` | 查看 Certbot 管理的证书和到期时间 |
| `tls-register-renewal -Tls [-TlsRenewalAt HH:mm]` | 确认 Certbot renewal lineage 后，为当前 Windows 用户注册每日续期计划任务 |
| `tls-unregister-renewal [-TlsRenewalTaskName NAME]` | 幂等删除续期计划任务，不依赖环境文件或 Docker CLI |
| `down` | 停止服务并保留 named volumes |
| `down -Volumes` | 显式销毁全部业务/TLS named volumes，并删除同名续期计划任务；仅限确认备份后的环境清理 |

脚本默认 `down` 不删除 volumes；`-Volumes` 是显式破坏性开关，并会删除 PostgreSQL、MinIO、OpenSearch、Redis、TLS/Certbot volumes 和对应续期计划任务。`.env.windows`、证书私钥或备份内容不得写入 Git。

### 首次公网证书签发

前置条件：

1. `DRIVE_SERVER_NAME` 与 `DRIVE_STORAGE_SERVER_NAME` 是两个不同的公网 DNS 名称。
2. 两个名称都解析到当前 Windows 宿主的公网地址。
3. 路由器、云防火墙、Windows 防火墙允许外部 TCP 80/443 到 gateway。
4. 真实 `.env.windows` 已切换 HTTPS S3 URL、CORS、Trusted Hosts 和 Secure Cookie。
5. Docker Desktop Linux engine 正在运行，宿主没有其他程序占用 80/443。

公网管理入口固定要求 `DRIVE_TLS_HTTP_PORT=80`、`DRIVE_TLS_HTTPS_PORT=443`；非标准端口只用于底层 Compose/Nginx 隔离测试，不属于 `manage.ps1 -Tls` 的正式支持范围。

先做配置校验：

```powershell
.\deploy\windows\manage.ps1 config -Tls -EnvFile .env.windows -Quiet
```

公网校验只检查域名语法，DNS 解析和外部可达性必须按前置条件单独验证。校验会拒绝回环/非 IPv4 gateway bind、`change-me` 示例密钥、过短 secret、关键 secret/连接 URL 中的 `${...}` 间接插值、数据库或 Redis URL 与独立密码不一致、含通配符的 Trusted Hosts、HTTP API CORS origin、与 API CORS 不完全一致或包含非 HTTPS 项的 MinIO CORS、带凭据/非 443 端口的 S3 URL 和不安全的证书名。URL 中的密码包含保留字符时仍须百分号编码，脚本会解码后与 `POSTGRES_PASSWORD`、`REDIS_PASSWORD` 比较。`tls-init` 还会拒绝 `example.com`、`.invalid`、`.test` 等示例邮箱域名。

可选先使用 ACME staging 验证 challenge 链路。staging 会使用独立的 `<DRIVE_TLS_CERT_NAME>-staging` 证书名，把 HSTS `max-age` 强制为 0，且浏览器不会信任该证书：

```powershell
.\deploy\windows\manage.ps1 tls-init -Tls -TlsStaging -EnvFile .env.windows
```

生产签发：

```powershell
.\deploy\windows\manage.ps1 tls-init -Tls -EnvFile .env.windows
.\deploy\windows\manage.ps1 up -Tls -Build -EnvFile .env.windows
.\deploy\windows\manage.ps1 tls-certificates -Tls -EnvFile .env.windows
```

`tls-init` 会记录已有 gateway 是否正在运行并先停止但保留其容器，再用同一 `gateway` service 启动临时 one-off ACME bootstrap 容器。bootstrap 期间只有 `/gateway-healthz` 和 `/.well-known/acme-challenge/` 可用，其他请求返回 `503`；证书签发与 TLS 模板 `nginx -t` 成功后，脚本删除临时容器并强制重建正式 gateway。签发、SAN 或模板检查失败时，脚本删除临时 bootstrap 并重新启动原 gateway，避免扩域或重签失败后中断已有公网入口。`tls-init` 只保证签发所需依赖和 gateway 就绪，首次正式部署随后必须执行 `up -Tls -Build`，确保 Preview 镜像、全部 Worker 和 Celery beat 一并启动。

### 自动续期

手工验证一次续期命令、现有 Certbot lineage 检查和热重载：

```powershell
.\deploy\windows\manage.ps1 tls-renew -Tls -EnvFile .env.windows
```

普通命令在证书未进入续期窗口时不会实际签发新证书；需要验证真实签发时，只在受控演练窗口增加 `-ForceRenewal`。续期前脚本允许即将到期或已过期的现有证书进入 Certbot，但仍要求文件可读、SAN 覆盖两个配置域名，并存在 `/etc/letsencrypt/renewal/<DRIVE_TLS_CERT_NAME>.conf`。Certbot 完成后会重新要求证书至少还有 24 小时有效期，再执行 `nginx -t` 和热重载。手工复制或自签名到 `live/` 的证书没有 renewal lineage，`tls-renew` 和 `tls-register-renewal` 会明确拒绝；生产自动续期证书必须由 `tls-init` 建立。

确认普通命令路径成功后为当前 Windows 用户注册每日任务：

```powershell
.\deploy\windows\manage.ps1 tls-register-renewal `
    -Tls `
    -EnvFile .env.windows `
    -TlsRenewalAt 03:17
```

计划任务需要使用运行 Docker Desktop 的同一 Windows 用户，并要求任务执行时 Docker Desktop Linux engine 可用。修改仓库路径、环境文件路径或运行用户后，应先删除再重新注册：

```powershell
.\deploy\windows\manage.ps1 tls-unregister-renewal
```

自定义 `TlsRenewalTaskName` 只允许英文、数字、点、下划线和短横线；管理脚本按根 TaskPath 和不区分大小写的完整名称查找，禁止把计划任务通配符传给删除操作。

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
- 公网 Trusted Hosts 模式下，healthcheck 仍访问容器回环地址，但必须显式使用 `DRIVE_SERVER_NAME` 作为 Host，避免被 TrustedHost middleware 返回 400。

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
- Certbot 证书、账户和续期状态。
- ACME webroot、Certbot work/log。

原则：

- named volumes 由 Compose 管理，不写入 Git 工作区。
- 停止、重建 API/Worker/gateway 不删除数据卷。
- `docker compose down` 默认保留数据。
- 破坏性清理统一使用 `manage.ps1 down -Volumes`；底层 `docker compose down -v` 若未带 `--profile tls-tools` 会遗漏 Certbot work/log volumes，也不会删除 Windows 续期计划任务。
- OpenSearch 索引以 PostgreSQL 为事实来源，仍应保留重建索引脚本和演练流程。
- Preview 临时目录属于可清理数据，不作为原文件或唯一预览事实来源。

## 10. Gateway 安全边界

gateway 必须负责：

- 当前默认本机 HTTP `18080/19000` 入口。
- 公网模式通过 `-Tls` 使用 ACME bootstrap、证书只读挂载、TLS server block、HTTP 到 HTTPS 跳转和 `80/443` Host 分流。
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

- 代码已经覆盖本机 HTTP `18080/19000` 和公网 TLS `80/443` 两种模板。
- Certbot 证书、账户和续期配置位于 named volumes，gateway 只读挂载证书；私钥不进入仓库或镜像。
- HTTP-01 challenge 只允许 `/.well-known/acme-challenge/`，未知 Host 在 TLS 模板中直接拒绝。
- 续期由宿主 PowerShell 命令或同一 Windows 用户的计划任务触发，不向容器挂载 Docker socket。
- 当前机器已用自签名双域名证书在标准宿主 `80/443` 启动完整正式编排，验证 HTTP `308`、API `/healthz`/`/readyz`、HSTS、MinIO CORS、S3v4 对象往返、未知 Host 拒绝、临时 one-off bootstrap、原 gateway 恢复、大小写无关计划任务删除和全部卷/端口清理。真实受信证书、外部 DNS/网络、浏览器信任链和 Certbot renewal lineage 实际续期仍需在生产网络验收。

## 11. 自动化备份、校验与隔离恢复

`v0.4.0` 已通过 `deploy/windows/manage.ps1` 交付 `backup`、`backup-verify` 和 `restore`。脚本从 `docker compose config --format json` 获取真实 project、network、service image 和 physical volume name，不手工拼接 Compose 资源名。备份、恢复、`up`、`down` 和 TLS 写操作共用按 project 名称派生的 Windows named mutex；`backup`、`restore` 还会按每个 source/target physical volume name 获取独立 mutex，防止不同 Compose project 通过同一物理卷并发维护。

### 11.1 备份内容与一致性

`backup` 会在维护窗口按 gateway、API/beat、各类 Worker、MinIO/Redis/OpenSearch 的顺序静默写入面，并逐服务记录 source 容器 ID、原始 `running`/`exited` 状态和 health。PostgreSQL 使用 custom-format `pg_dump`；MinIO、Redis、OpenSearch 和 `tls-certificates` 使用停止状态原始卷 tar。备份完成或中途失败后，脚本都会恢复并对账 source 原运行、退出与健康状态。

正式备份目录只由校验通过的 `.partial-*` staging 原子发布，主要内容包括：

- `postgres/postgres.dump`
- `volumes/minio-data.tar.gz`
- `volumes/redis-data.tar.gz`
- `volumes/opensearch-data.tar.gz`
- `volumes/tls-certificates.tar.gz`
- `secrets/environment.cms`
- 归档时的 `compose.windows.yml` 与 Nginx templates
- UTF-8 `manifest.json` 与 `manifest.sha256`

manifest 记录工件大小和 SHA-256、source project、逐服务原状态、精确 Compose SHA-256、项目版本、Git commit、Alembic revision、PostgreSQL WAL LSN、CMS 证书 thumbprint，以及 `DRIVE_S3_BUCKET`、`DRIVE_OPENSEARCH_INDEX_NAME`、`DRIVE_TLS_CERT_NAME` lineage 名称。镜像清单覆盖 15 个无 profile 默认服务（`gateway`、`api`、`migration`、`seed`、`minio-init`、`beat`、5 个 Worker、PostgreSQL、Redis、MinIO、OpenSearch），每项 image ID 都来自该服务实际 Compose 容器，并在备份时确认与当前 image reference 指向的本地 image ID 一致。

备份根目录和 `.partial-*` staging 会自动关闭 ACL 继承，只允许当前 Windows 用户、SYSTEM、Administrators 完全控制；校验通过后 staging 原子改名为正式备份目录并保留该 restricted ACL。路径链中检测到 NTFS reparse point 时拒绝继续。

### 11.2 CMS 证书与私钥保管

正式备份默认要求当前 Windows 用户 `Cert:\CurrentUser\My` 中存在 CMS 文档加密证书。建议创建专用、可导出私钥的证书：

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

PFX 私钥必须与备份数据分开保存在受保护的加密介质中，并演练重新导入和 CMS 解密。丢失私钥后，`environment.cms` 将失去恢复条件。`-SkipEnvironmentBackup` 只用于隔离测试，不用于正式备份。

### 11.3 创建并校验备份

`-BackupDirectory` 必须是仓库外的绝对专用目录，不得是卷根、仓库目录或仓库祖先。若目录已经存在且非空，它必须已经应用本项目 restricted ACL；脚本会拒绝直接重写任意既有宽范围目录的 ACL：

```powershell
$backupRoot = "D:\enterprise-drive-backups"
$backupPath = [string](
    .\deploy\windows\manage.ps1 backup `
        -EnvFile .env.windows `
        -BackupDirectory $backupRoot `
        -ConfigEncryptionCertificateThumbprint $backupCertificate.Thumbprint `
        -QuiesceTimeoutSeconds 300 |
        Select-Object -Last 1
)

.\deploy\windows\manage.ps1 backup-verify `
    -EnvFile .env.windows `
    -BackupPath $backupPath
```

`backup-verify` 会执行以下门禁：

- 校验 `manifest.sha256` 格式和 `manifest.json` SHA-256。
- 校验每个工件的路径边界、唯一性、大小和 SHA-256。
- 使用 `pg_restore --list` 验证 PostgreSQL custom dump。
- 要求当前 `compose.windows.yml` SHA-256、Git commit、`backend/pyproject.toml` 项目版本、S3 bucket、OpenSearch index 和 `DRIVE_TLS_CERT_NAME` lineage 名称与 manifest 精确一致。
- 要求 15 个默认服务逐项具有相同 image reference 和 image ID；归档工具也必须与 manifest 中 PostgreSQL 实际容器 image ID 一致。
- 先在 `--network none`、只读根文件系统、只读备份 bind、`--cap-drop ALL`、`no-new-privileges` 的容器中检查 tar 路径，再预解包到一次性临时 Docker volume；拒绝绝对路径、父目录穿越、硬链接、块/字符设备、FIFO、socket、悬空 symlink 和解析后越出临时卷的 symlink。
- tar 检查结束后必须删除临时卷；扫描失败或临时卷清理失败都会使校验失败。

因此，复制备份到另一台主机时，应先检出 manifest 记录的精确 Git commit，保持相同 `compose.windows.yml`、项目版本和 bucket/index/TLS lineage 配置，并准备全部 15 个服务对应的固定镜像，再执行 `backup-verify`。

### 11.4 隔离恢复

恢复必须使用与 source 不同的 `COMPOSE_PROJECT_NAME`。建议复制环境文件并修改 project 名、API/S3 宿主端口及其他会冲突的宿主资源：

```powershell
Copy-Item .env.windows .env.restore.windows
# 编辑 .env.restore.windows：
# - 使用不同的 COMPOSE_PROJECT_NAME
# - 使用不与 source 冲突的 DRIVE_GATEWAY_PORT / DRIVE_STORAGE_GATEWAY_PORT

.\deploy\windows\manage.ps1 restore `
    -EnvFile .env.restore.windows `
    -BackupPath $backupPath `
    -RestoreEnvironmentOutput "D:\enterprise-drive-secure\restored-source.env" `
    -NoStartAfterRestore
```

恢复前脚本会再次执行完整备份校验，并要求全部 15 个默认服务的 target image reference 和本地 image ID 与 manifest 一致。target 有运行中或过渡态容器时始终拒绝恢复；source/target 任一 physical volume 重叠、已有卷 Compose project/logical-volume 标签不符，或卷仍附着到 foreign container 时也会拒绝。默认还会拒绝已有容器和非空目标卷。

`-ForceRestore` 只用于显式清理已停止的 target 容器或非空卷，不会跳过同 project、运行状态、卷重叠/标签/attachment、路径、SHA-256、tar、dump、代码/configuration lineage 或镜像一致性门禁。清空任何原非空目标卷前，脚本会在 Windows 临时目录创建 restricted ACL rollback archive；正常恢复成功后删除它。恢复一旦提交，后续归档清理失败只会返回 maintenance cleanup error、保留并报告归档路径，不会再次清空或回滚已经恢复的数据。`-NoStartAfterRestore` 会在 PostgreSQL dump 恢复和 Alembic revision 校验后停止 PostgreSQL，不启动完整业务栈，适合先检查数据卷和解密配置。

`-RestoreEnvironmentOutput` 必须是仓库和备份目录外的绝对、尚不存在文件路径，父目录必须预先存在且不得经过 NTFS reparse point；它不会覆盖当前 target 的 `-EnvFile`。CMS 明文先保存在 PowerShell 内存中，只有本次恢复模式的数据卷、PostgreSQL、Alembic revision 和镜像门禁全部验证成功后，才在最后一步写入同目录 restricted ACL 临时文件并原子改名发布；未使用 `-NoStartAfterRestore` 时还会先完成完整服务健康与实际容器 image ID 对账。原子发布前失败不会创建输出；若发布竞态中目标路径被其他进程创建，脚本会保留该 foreign file，不在恢复失败清理中删除。

未使用 `-NoStartAfterRestore` 时，脚本会启动完整 target Compose project 并等待健康，再逐项核对 15 个默认服务实际容器 image ID。恢复中途失败后，脚本会执行 Compose down、删除本轮新建卷、把原本为空的既有卷清回空状态，并从 rollback archive 还原 `-ForceRestore` 前的原非空卷；卷回滚失败时会保留并报告受限 ACL rollback archive 绝对路径。target 不会以半恢复状态继续对外提供服务。

### 11.5 安全与兼容边界

- Windows CMS 只加密 `.env.windows`。PostgreSQL dump、MinIO/Redis/OpenSearch 原始卷 tar 和包含 TLS 私钥的证书卷 tar 不具备完整包级应用层加密，必须依赖备份宿主 BitLocker、脚本自动应用的 restricted NTFS ACL 和加密外部介质。
- `manifest.sha256` 和工件 SHA-256 只校验完整性，不认证备份制作者身份。需要认证来源时，应另外使用受保护签名、受控传输和可审计保管链。
- Redis/OpenSearch 使用停止状态原始卷归档，只支持相同 image reference、相同 image ID、单节点同拓扑。跨版本或拓扑变化应使用 Redis/OpenSearch 支持的迁移、导出或快照机制。
- `-ForceRestore` rollback archive 是失败时的尽力恢复机制；底层卷驱动、磁盘或 Docker 故障仍可能需要人工处理，因此发现回滚异常后不得删除脚本报告的受限 ACL 归档。
- PostgreSQL 是核心事实来源；Redis 主要保存缓存、限流和队列状态，OpenSearch 索引可由 PostgreSQL 与对象存储重建，但仍应记录重建步骤和耗时。
- 当前固定 MinIO Server/Client 镜像仍有 19/12 个 Critical 基线。供应链门禁只阻断新增 Critical，正式上线前仍需升级到修复镜像或完成可审计的自建修复镜像替换。
- 备份目录必须设置保留期、容量告警、最小权限 ACL、离线副本和周期隔离恢复演练。

## 12. 发布与更新

推荐流程：

```powershell
.\deploy\windows\manage.ps1 config -Quiet
$backupPath = [string](
    .\deploy\windows\manage.ps1 backup `
        -EnvFile .env.windows `
        -BackupDirectory "D:\enterprise-drive-backups" `
        -ConfigEncryptionCertificateThumbprint BACKUP_CERTIFICATE_THUMBPRINT |
        Select-Object -Last 1
)
.\deploy\windows\manage.ps1 backup-verify -EnvFile .env.windows -BackupPath $backupPath
.\deploy\windows\manage.ps1 up -Build
.\deploy\windows\manage.ps1 status
```

公网 TLS 发布把上述三个命令分别加上 `-Tls`；首次签发先执行 `tls-init -Tls`，后续发布只需要 `up -Tls`。

发布检查：

- CI 的 ruff、format、mypy、pytest 通过。
- `docker compose ... config` 通过。
- 应用镜像构建通过。
- migration 一次性服务退出码为 0。
- `/readyz` 真实数据库探针通过。
- gateway 的 API 与 S3 外部端点可访问；公网模式还要检查 HTTP `308`、证书链、HSTS、双域名 Host 分流和真实预签名 PUT/GET。
- Worker 已连接预期队列。
- `beat` 只有一个有效实例。
- Preview 工具版本可读取。
- 容器无持续重启。
- Windows 宿主磁盘空间正常。
- 发布前备份已通过 `backup-verify`，并且最近一次不同 Compose project 隔离恢复演练有记录。

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
- 恢复前先在不同 Compose project 使用 `-NoStartAfterRestore` 验证 dump、数据卷、Alembic revision、CMS 解密和镜像一致性，再决定是否切换业务流量。
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

本机 HTTP 入口：

```powershell
Invoke-WebRequest http://localhost:18080/healthz
Invoke-WebRequest http://localhost:18080/readyz
```

对象存储应通过真实预签名 PUT/GET 集成测试验证 `http://localhost:19000`，不能只访问 MinIO 根路径判断成功。

公网 TLS：

```powershell
.\deploy\windows\manage.ps1 config -Tls -EnvFile .env.windows -Quiet
.\deploy\windows\manage.ps1 tls-certificates -Tls -EnvFile .env.windows
.\deploy\windows\manage.ps1 up -Tls -EnvFile .env.windows

Resolve-DnsName drive.example.com
Resolve-DnsName storage.example.com
curl.exe -sS -o NUL -w "%{http_code} %{redirect_url}`n" http://drive.example.com/healthz
Invoke-WebRequest https://drive.example.com/healthz
Invoke-WebRequest https://drive.example.com/readyz
```

HTTP 检查应返回 `308` 并跳到同 Host 的 HTTPS。随后检查响应包含预期 HSTS、安全头和受信证书链，并通过 `https://storage.example.com` 的真实预签名 PUT/GET 验证 Host、查询参数、请求体和签名未被 gateway 改写。`tls-renew -Tls -ForceRenewal` 只在受控演练窗口使用，用于验证续期和热重载；日常计划任务不要强制续期。

备份与隔离恢复：

```powershell
.\deploy\windows\manage.ps1 backup-verify `
    -EnvFile .env.windows `
    -BackupPath "D:\enterprise-drive-backups\BACKUP_ID"

.\deploy\windows\manage.ps1 restore `
    -EnvFile .env.restore.windows `
    -BackupPath "D:\enterprise-drive-backups\BACKUP_ID" `
    -RestoreEnvironmentOutput "D:\enterprise-drive-secure\restored-source.env" `
    -NoStartAfterRestore
```

隔离恢复后应检查 PostgreSQL 备份点、MinIO 对象、Redis key、OpenSearch index、Alembic revision、TLS symlink/SAN 和 CMS 环境文件；随后按需启动 target，验证 `/healthz`、`/readyz`、全部 Worker、beat、gateway 以及只有 gateway 发布宿主端口。验证结束后清理 target containers、volumes、networks、解密环境文件和临时证书。

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

公网模式使用 `manage.ps1 down -Tls`。停止后不得添加 `-Volumes` 或底层 `-v`。重新启动后还应验证 named volumes 中的数据与证书保持、migration 不重复产生副作用、Worker 和 beat 恢复正常。

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

### `tls-init` 的 HTTP-01 challenge 失败

检查：

- 两个域名是否都解析到当前公网地址。
- 外部 TCP 80 是否真正到达 gateway，而不是被路由器、云防火墙、Windows 防火墙或其他 Web 服务截获。
- `tls-init` 期间 gateway 日志是否显示 ACME challenge 请求。
- 是否错误启用了 CDN 代理、强制 HTTPS 或上游 WAF，导致 challenge 内容被改写。
- staging 与生产签发是否使用了预期证书名；staging 默认为 `<DRIVE_TLS_CERT_NAME>-staging`。

### 续期成功但 gateway 仍返回旧证书

先运行：

```powershell
.\deploy\windows\manage.ps1 tls-certificates -Tls -EnvFile .env.windows
.\deploy\windows\manage.ps1 tls-renew -Tls -EnvFile .env.windows
.\deploy\windows\manage.ps1 logs -Tls -Service gateway -Tail 100
```

`tls-renew` 要求 gateway 正在运行 TLS/ACME 模板，并确认容器 `8080/8443` 分别发布到宿主 `80/443`，以便 HTTP-01 webroot 能响应续期 challenge；脚本还会先确认 `/etc/letsencrypt/renewal/<DRIVE_TLS_CERT_NAME>.conf` 存在，再只续期该 production lineage，最后执行 `nginx -t` 和热重载。若提示 renewal lineage 缺失，使用 `tls-init` 建立 Certbot 管理状态，不能只向 `live/` 复制证书。若 gateway 未运行或仍是本机 HTTP 模板，先使用 `up -Tls` 启动并确认健康。计划任务必须由能访问 Docker Desktop Linux engine 的同一 Windows 用户运行。
