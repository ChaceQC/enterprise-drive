# Windows 11 Docker 正式部署说明

> 适用项目版本：`v0.8.0`
>
> 当前代码基线：Windows 本机 HTTP `18080/19000`、公网 ACME/TLS `80/443`、可选 monitoring profile、备份轮换、隔离恢复、账号安全、OIDC/PKCE 和 LDAP 同步均已落地；真实受信证书、企业 OIDC provider 和 LDAPS 目录验收仍需要生产 DNS/网络环境。

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
| `gateway` | Nginx 入口、Web/API/存储分流、Range、安全响应头、ACME challenge、TLS 与 HTTP 跳转 | 唯一允许发布端口 |
| `web` | React/Vite 用户端与管理后台静态资源，容器内监听 `8080`，健康入口 `/web-healthz` | 不发布 |
| `certbot` | `tls-tools` profile 下的一次性证书签发、检查和续期工具 | 不发布 |
| `api` | FastAPI API | 不发布 |
| `migration` | 一次性 Alembic migration | 不发布 |
| `seed` | migration 后一次性创建或校准初始管理员 | 不发布 |
| `worker-preview` | 图片、PDF、Office 预览 | 不发布 |
| `worker-search` | 文本/OCR/旧格式抽取、索引写入 | 不发布 |
| `worker-audit` | 审计 outbox | 不发布 |
| `worker-permission` | 权限缓存失效 | 不发布 |
| `worker-maintenance` | 生命周期、治理与异步 LDAP 同步任务 | 不发布 |
| `beat` | 独立运行 Celery beat，负责周期任务调度 | 不发布 |
| `postgres` | PostgreSQL 事实库 | 不发布 |
| `redis` | 缓存、限流、Celery broker/result backend | 不发布 |
| `minio` | 私有 S3 兼容对象存储 | 不发布 |
| `minio-init` | 一次性创建私有 bucket 并确认匿名访问关闭 | 不发布 |
| `opensearch` | 可重建搜索索引 | 不发布 |
| `prometheus` | `monitoring` profile 指标抓取、规则计算与时序数据 | 不发布 |
| `alertmanager` | `monitoring` profile 告警聚合与企业 webhook 路由 | 不发布 |
| `grafana` | `monitoring` profile 看板；仅经 gateway `/grafana/` 访问 | 不发布 |

默认本机入口：

- Web/API：`http://localhost:18080`
- S3 外部预签名端点：`http://localhost:19000`

两个入口都由同一个 `gateway` 容器发布。Web、MinIO、API 等内部服务本身不配置宿主端口。

5 个 Celery Worker 会在各自容器内监听 `9100` 指标端口，但该端口只通过 Compose `expose` 提供给内部监控网络，不发布到 Windows 宿主。API `/metrics` 聚合 API Uvicorn worker；Worker task/preview/维护指标必须按 `worker-audit`、`worker-permission`、`worker-search`、`worker-maintenance` 和 `worker-preview` 分别抓取。

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
        +-- web
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
- Grafana 独立管理员密码、`/grafana/` root URL 和 Alertmanager webhook URL 文件。
- 仓库外治理记录根目录、备份保留天数和最少份数。
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
DRIVE_SERVICE_NAME=enterprise-drive-api
DRIVE_TRACING_ENABLED=true
DRIVE_TRACING_SAMPLE_RATIO=0.1
DRIVE_TRACING_EXPORTER=none
DRIVE_TRACING_OTLP_ENDPOINT=
DRIVE_TRACING_OTLP_HEADERS={}
DRIVE_TRACING_EXPORT_TIMEOUT_SECONDS=10.0
DRIVE_METRICS_DATABASE_REFRESH_ENABLED=true
DRIVE_METRICS_DATABASE_REFRESH_TIMEOUT_SECONDS=1.0
DRIVE_RATE_LIMIT_ENABLED=true
DRIVE_LOGIN_IP_RATE_LIMIT_COUNT=30
DRIVE_LOGIN_ACCOUNT_RATE_LIMIT_COUNT=10
DRIVE_LOGIN_RATE_LIMIT_WINDOW_SECONDS=60
DRIVE_LOGIN_FAILURE_LOCK_THRESHOLD=5
DRIVE_LOGIN_FAILURE_WINDOW_SECONDS=900
DRIVE_LOGIN_LOCK_SECONDS=900
DRIVE_LOGIN_DELAY_BASE_SECONDS=0.25
DRIVE_LOGIN_DELAY_MAX_SECONDS=4.0
DRIVE_LOGIN_CAPTCHA_AFTER_FAILURES=3
DRIVE_PASSWORD_MIN_LENGTH=12
DRIVE_PASSWORD_REQUIRE_UPPERCASE=true
DRIVE_PASSWORD_REQUIRE_LOWERCASE=true
DRIVE_PASSWORD_REQUIRE_DIGIT=true
DRIVE_PASSWORD_REQUIRE_SPECIAL=true
DRIVE_OIDC_STATE_TTL_SECONDS=600
DRIVE_IDENTITY_ALLOWED_REDIRECT_PATHS=["/","/account","/auth/oidc/callback","/admin/identity"]
DRIVE_IDENTITY_HTTP_TIMEOUT_SECONDS=10.0
DRIVE_LDAP_SYNC_PAGE_SIZE=500
OIDC_CLIENT_SECRET=
LDAP_BIND_PASSWORD=
DRIVE_OPENSEARCH_URL=http://opensearch:9200
DRIVE_S3_ENDPOINT_URL=http://minio:9000
DRIVE_S3_PUBLIC_ENDPOINT_URL=http://localhost:19000
GRAFANA_ROOT_URL=http://localhost:18080/grafana/
ALERTMANAGER_WEBHOOK_URL_FILE=D:\enterprise-drive-secrets\alertmanager-webhook-url
DRIVE_BACKUP_RETENTION_DAYS=35
DRIVE_BACKUP_RETENTION_COUNT=8
DRIVE_GOVERNANCE_RECORD_ROOT=D:\enterprise-drive-governance
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
GRAFANA_ROOT_URL=https://drive.example.com/grafana/
```

`manage.ps1 -Tls` 会用 `DRIVE_TLS_GATEWAY_BIND`、`DRIVE_TLS_HTTP_PORT`、`DRIVE_TLS_HTTPS_PORT` 覆盖本机端口，并切换到 ACME bootstrap 或 TLS 模板。公网 bind 只接受 `0.0.0.0` 或其他非回环 IPv4 地址。`config -Tls` 负责静态配置门禁，生产服务上线后由 `tls-validate-public` 验证真实 DNS、公网地址、HTTP `308`、HTTPS readiness、证书链和剩余有效期。不要手工同时启动本机 HTTP 和公网 TLS 两套 gateway；两种模式复用同一个 Compose service 和项目 named volumes。

### S3 内外端点分离

- `DRIVE_S3_ENDPOINT_URL` 只供 API/Worker 在 Compose 网络内访问 MinIO。
- `DRIVE_S3_PUBLIC_ENDPOINT_URL` 用于生成浏览器可访问的预签名 URL。
- 默认外部端点是 `http://localhost:19000`。
- 公网 TLS 模式使用独立 Host，例如 `https://storage.example.com`。
- 外部端点不使用 `/s3` 等 base path。MinIO client 和 SigV4 会把 Host、路径、查询参数纳入签名，路径前缀重写会导致签名不匹配。
- gateway 转发存储请求时必须保留原始 Host、查询字符串、HTTP 方法和请求体。
- MinIO Console 不对宿主机发布；运维应通过容器内 CLI 或受控管理流程进行。

### 指标、日志与 tracing

- API `/metrics` 只暴露 API 进程内的 HTTP 请求数/延迟、上传、下载、权限判断、Outbox 状态和搜索索引延迟指标。HTTP 标签使用完整路由模板，避免原始 URL、路径参数、用户/租户 ID、request_id 或 token 形成高基数。
- API 默认 `DRIVE_API_WORKERS=2`，通过 `PROMETHEUS_MULTIPROC_DIR=/tmp/enterprise-drive/prometheus` 聚合。后端 runtime entrypoint 在容器每次启动前清理旧 metric `.db` 文件，然后 `exec` 原 API/migration/seed/Worker/beat 命令；在线 worker 不执行目录清理。
- Worker 是独立容器，各自内部 `9100` 端口只提供本容器的 `worker_tasks_total`、`worker_task_duration_seconds`、预览失败和维护任务指标。maintenance Worker 还暴露连续失败、告警状态、stale、最近完成时间和任务返回计数。可选 `monitoring` profile 已把 5 个 Worker 配成 5 个 scrape target，不能假设 API `/metrics` 会跨容器聚合。
- JSON 日志自动带 `service`、`env`、`request_id`、`task_id`、`trace_id`、`span_id`；HTTP 请求结束日志包含 route/method/status/latency，Celery task 结束日志包含 task/queue/status/latency。
- OpenTelemetry exporter 默认 `none`，不会向外部发送 span。生产接入 collector 时使用 `DRIVE_TRACING_EXPORTER=otlp_http`，把 `DRIVE_TRACING_OTLP_ENDPOINT` 设为完整 traces endpoint，例如 `http://otel-collector:4318/v1/traces`。`DRIVE_TRACING_OTLP_HEADERS` 必须是 JSON 对象，认证信息只放在未提交的 `.env.windows` 或受控 secret 管理中。
- `outbox_pending_total` 和 `search_index_lag_seconds` 在 API scrape 时以短超时刷新。PostgreSQL 不可用时 `/metrics` 仍返回已有进程指标，但数据库 gauge 可能短暂保留上次成功值。
- `DRIVE_RATE_LIMIT_ENABLED` 默认必须保持 `true`；根 Compose 会把该值传入 API 和 Worker。只有隔离容量基准可以临时设为 `false`，并应通过 `PERF_RATE_LIMIT_MODE` 写入性能报告，不能把关闭限流的测试配置直接用于生产。
- 登录同时按来源 IP 和规范化账号标识限流；账号 key 只保存哈希，不保存原始用户名。默认分别为每分钟 `30` 和 `10` 次，正式环境可收紧但不能关闭，并与 PostgreSQL 失败窗口、阶梯延迟和临时锁定共同生效。
- Sprint 11 已实现阶梯延迟、失败时间窗口、临时锁定、管理员解锁和验证码阈值。默认连续 5 次失败后锁定 900 秒，失败窗口为 900 秒，延迟从 0.25 秒指数增长并在 4 秒封顶；正式环境调整阈值时必须同时评估 Redis 限流、Argon2id CPU、客服解锁流程和告警噪声。
- `/metrics` 暴露低基数 `auth_security_events_total`、`identity_provider_operations_total` 和 `ldap_sync_runs_total`。Prometheus/Alertmanager 规则必须使用固定 event/provider/operation/outcome 值，禁止把 username、tenant、provider slug、external ID、DN、state、token 或错误原文作为 label。
- `DRIVE_ENVIRONMENT=production` 会触发应用内 `Settings` fail-fast 校验，覆盖 API、Worker、beat、migration 和 seed。即使绕过 `manage.ps1`，示例/过短 secret、无强密码数据库或 Redis/Celery URL、关闭限流、Wildcard Trusted Hosts、带凭据或路径的公共端点，以及非回环 HTTP CORS/S3 或未启用 Secure Cookie 的公网配置也会阻断进程启动。默认本机 HTTP 模式只有在全部公共 Host 均为 localhost/回环地址时才允许。

### 身份与账号安全

- `DRIVE_LOGIN_FAILURE_*`、`DRIVE_LOGIN_LOCK_SECONDS`、`DRIVE_LOGIN_DELAY_*` 和 `DRIVE_LOGIN_CAPTCHA_AFTER_FAILURES` 会透传到 API；验证码 verifier 是可插拔适配器，当前默认关闭，接入真实 provider 时应通过项目基础设施层完成，不在 Compose 文件中硬编码第三方密钥。
- `DRIVE_PASSWORD_*` 是用户改密、管理员创建/重置和前端策略提示的同一服务端事实。管理员 seed 默认要求首次改密；弱化策略前必须完成安全评审，不能只修改前端 `minLength`。
- OIDC provider/LDAP Source 行只保存 `env:VARIABLE_NAME` 引用。示例 `env:OIDC_CLIENT_SECRET` 由 API 容器中的 `OIDC_CLIENT_SECRET` 解析；`env:LDAP_BIND_PASSWORD` 同时由 API 连接测试和 maintenance Worker 同步任务解析，因此两个容器都必须注入同一受控值。
- `.env.windows` 中的身份 secret 不得提交 Git。空字符串、变量缺失和未知引用格式都按 `IDENTITY_SECRET_UNAVAILABLE`/`IDENTITY_SECRET_REF_INVALID` 处理；管理响应只返回 `client_secret_configured` 或 `bind_password_configured`。
- OIDC issuer、authorization/token/JWKS/end-session endpoint 对非回环地址必须使用 HTTPS；生产回调 URL 由 gateway API 域名生成，provider 侧登记应为 `https://drive.example.com/api/v1/auth/oidc/{provider_slug}/callback`。`DRIVE_IDENTITY_ALLOWED_REDIRECT_PATHS` 只允许站内路径，禁止完整外部 URL。
- LDAP 生产连接优先使用 `ldaps://` 并验证目录证书链。同步由 `worker-maintenance` 的 `identity.sync_ldap` 执行；扩容 maintenance Worker 前必须保证同一 Source 的 run 锁和目录侧连接上限，不能用并发 Worker 绕过 run 状态机。
- dry-run 不更新用户、部门、组、绑定或 cursor；首次接入必须先执行 dry-run，检查冲突和变更统计，再执行 full。目录读取失败、分页不完整或凭据不可用时不得把“未返回对象”解释为离职。
- 用户改密、管理员重置、停用和 LDAP 离职会吊销浏览器与桌面设备会话。运维排障时应同时检查 `auth_sessions`、`device_sessions`、身份审计和 LDAP run，不应手工恢复旧 token。
- 详细数据模型、接口、错误码、测试和真实 provider 验收清单见 `docs/identity-security.md`。

### 可选 monitoring profile

监控 profile 不属于 16 个默认业务服务，也不进入业务备份 manifest。启用前必须：

1. 把 `GRAFANA_ADMIN_PASSWORD` 改成至少 16 字符的独立非示例密码。
2. 把示例 webhook 文件复制到仓库外或 `.gitignore` 覆盖的 secret 路径，内容为单行可达 HTTP(S) URL。
3. 本机模式使用 `GRAFANA_ROOT_URL=http://localhost:18080/grafana/`；公网 TLS 使用 API 域名的 `https://.../grafana/`。

```powershell
.\deploy\windows\manage.ps1 config -Monitoring -EnvFile .env.windows -Quiet
.\deploy\windows\manage.ps1 up -Monitoring -EnvFile .env.windows
```

Prometheus、Alertmanager、Grafana 只加入 `backend` 内网并使用独立 named volumes。Grafana 由 gateway 代理；未启用 profile 时 gateway 仍能启动。配置、规则、看板和排障详见 `docs/maintenance-monitoring.md`。

## 5. PowerShell 管理入口

宿主机操作统一通过：

```powershell
.\deploy\windows\manage.ps1 <command>
```

当前管理脚本提供以下能力：

| 命令 | 目标 |
| --- | --- |
| `config [-Quiet]` | 使用示例或实际环境文件校验 Compose 渲染结果 |
| `up [-Build]` | 启动服务；默认 `--no-build --pull never`，只有显式 `-Build` 才构建项目镜像，migration、MinIO 初始化和 seed 由 Compose 依赖链执行 |
| `config/up/down/status/logs -Monitoring` | 启用可选 Prometheus、Alertmanager、Grafana profile；`up` 会校验非示例 Grafana 密码和 webhook 文件 |
| `config -Tls [-Quiet]` | 校验公网域名格式、HTTPS S3 URL、Secure Cookie、API/MinIO CORS、Trusted Hosts 和 TLS Compose 渲染 |
| `up -Tls [-Build]` | 使用已有证书启动或更新公网 TLS gateway |
| `status` | 查看全部容器与健康状态 |
| `logs [-Service NAME] [-Tail N]` | 查看全部或指定服务日志 |
| `backup -BackupDirectory PATH -ConfigEncryptionCertificateThumbprint THUMBPRINT` | 静默 source 写入面并创建 PostgreSQL、MinIO、Redis、OpenSearch、TLS 和 CMS 环境文件备份 |
| `backup-verify -BackupPath PATH` | 校验 manifest、工件、PostgreSQL dump、隔离 tar 预扫描、精确代码/configuration lineage 及 16 个默认服务 image reference/actual image ID |
| `restore -BackupPath PATH` | 把已校验备份恢复到不同且已停止的 Compose project，支持受限 ACL ForceRestore rollback |
| `backup-retention -BackupDirectory PATH [-ApplyRetention]` | 校验托管备份后按保留天数与最少份数预览或执行轮换，并写 JSON 记录 |
| `backup-retention-register/unregister` | 注册或幂等删除每日备份轮换 Windows 计划任务 |
| `restore-drill -BackupDirectory PATH` | 选择最新托管备份，恢复到随机隔离 Compose project，验证清理并写 JSON 记录；也可用 `-BackupPath` 指定 |
| `restore-drill-register/unregister` | 注册或幂等删除每周隔离恢复演练 Windows 计划任务 |
| `tls-init -Tls [-TlsEmail EMAIL] [-TlsStaging]` | 用 ACME webroot bootstrap 首次签发双域名证书并切换到 TLS gateway |
| `tls-renew -Tls [-ForceRenewal]` | 执行 Certbot 续期，随后校验并热重载 Nginx |
| `tls-certificates -Tls` | 查看 Certbot 管理的证书和到期时间 |
| `tls-register-renewal -Tls [-TlsRenewalAt HH:mm]` | 确认 Certbot renewal lineage 后，为当前 Windows 用户注册每日续期计划任务 |
| `tls-unregister-renewal [-TlsRenewalTaskName NAME]` | 幂等删除续期计划任务，不依赖环境文件或 Docker CLI |
| `tls-validate-public` | 验证双域名仅解析到公网地址、HTTP 精确 `308`、HTTPS readiness、受信证书链和至少 14 天有效期，并写 JSON 记录 |
| `down` | 停止服务并保留 named volumes |
| `down -Volumes` | 显式销毁业务/TLS/监控 named volumes，并删除 TLS 续期、备份轮换和恢复演练计划任务；仅限确认备份后的环境清理 |

脚本默认 `down` 不删除 volumes；`-Volumes` 是显式破坏性开关，并会删除 PostgreSQL、MinIO、OpenSearch、Redis、TLS/Certbot 和监控 volumes，以及三类对应计划任务。`.env.windows`、证书私钥、webhook 文件或备份内容不得写入 Git。普通 `up`、TLS 辅助 `run` 和内部恢复启动路径都禁止隐式拉取镜像；第三方镜像拉取、runtime/preview 构建、服务启动和备份恢复测试必须拆成独立步骤，便于看到具体耗时并避免一次命令同时占满 CPU、内存和磁盘。

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

`config -Tls` 只执行静态配置校验；它会拒绝回环/非 IPv4 gateway bind、`change-me` 示例密钥、过短 secret、关键 secret/连接 URL 中的 `${...}` 间接插值、数据库或 Redis URL 与独立密码不一致、含通配符的 Trusted Hosts、HTTP API CORS origin、与 API CORS 不完全一致或包含非 HTTPS 项的 MinIO CORS、带凭据/非 443 端口的 S3 URL 和不安全的证书名。URL 中的密码包含保留字符时仍须百分号编码，脚本会解码后与 `POSTGRES_PASSWORD`、`REDIS_PASSWORD` 比较。`tls-init` 还会拒绝 `example.com`、`.invalid`、`.test` 等示例邮箱域名。DNS 与公网可达性由上线后的 `tls-validate-public` 完成。

可选先使用 ACME staging 验证 challenge 链路。staging 会使用独立的 `<DRIVE_TLS_CERT_NAME>-staging` 证书名，把 HSTS `max-age` 强制为 0，且浏览器不会信任该证书：

```powershell
.\deploy\windows\manage.ps1 tls-init -Tls -TlsStaging -EnvFile .env.windows
```

生产签发：

```powershell
.\deploy\windows\manage.ps1 tls-init -Tls -EnvFile .env.windows
.\deploy\windows\manage.ps1 up -Tls -Build -EnvFile .env.windows
.\deploy\windows\manage.ps1 tls-certificates -Tls -EnvFile .env.windows
.\deploy\windows\manage.ps1 tls-validate-public -EnvFile .env.windows
```

`tls-validate-public` 会拒绝回环、私网、CGNAT、benchmark、documentation、multicast 和 reserved 地址；两个域名任一解析结果含非公网地址即失败。它还要求 API 和 S3 HTTP 地址精确返回同 Host 的 `308`，HTTPS `/readyz` 与 MinIO live probe 返回 200，TLS 握手通过系统信任链/主机名校验且证书至少还有 14 天有效期。成功或失败记录写到 `DRIVE_GOVERNANCE_RECORD_ROOT\tls-validations`，也可通过 `-TlsValidationDirectory` 覆盖。

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
- `file.cleanup_expired_trash`
- `share.expire_shares`
- `preview.cleanup_artifacts`
- `file.process_tree_operations`
- `file.cleanup_unreferenced_blobs`
- `file.cleanup_orphaned_objects`
- `quota.reconcile_space_usage`
- 后续接入的其他生命周期治理任务

Beat 使用 UTC。当前 schedule 文件位于容器临时目录，可由静态配置重建；任务事实和执行结果仍以数据库、审计和任务自身状态为准。每个维护任务必须幂等，不能仅依赖 beat 单实例保证。

Celery signal 统一记录上述八个周期维护任务的连续失败状态，Redis key 为 `maintenance_health:{task_name}`。达到配置阈值时 Worker 写结构化错误日志并设置 Prometheus alert Gauge；主进程定时刷新 stale 和时间戳指标。规则文件位于 `deploy/monitoring/maintenance-alerts.yml`，详细指标、配置和排障流程见 `docs/maintenance-monitoring.md`。Redis 只保存监控状态，不替代 PostgreSQL 与审计事实。

## 8. Preview Worker

Preview Worker 镜像必须包含：

- LibreOffice `soffice`
- Poppler `pdftoppm`
- Tesseract 及 `eng`、`chi_sim` 语言包
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

Search Worker 使用同一内容处理镜像执行图片/扫描 PDF OCR 和旧 Office/ODF 转换，但只消费 `search` 队列。默认使用独立 `SEARCH_TMPFS_SIZE=1073741824`、`--concurrency=2` 和 `--max-tasks-per-child=20`；不得与 Preview Worker 共享 tmpfs 或进程。

容器内验证：

```powershell
docker compose -f compose.windows.yml --env-file .env.windows exec worker-preview soffice --version
docker compose -f compose.windows.yml --env-file .env.windows exec worker-preview pdftoppm -v
docker compose -f compose.windows.yml --env-file .env.windows exec worker-search tesseract --version
docker compose -f compose.windows.yml --env-file .env.windows exec worker-search tesseract --list-langs
```

## 9. Named Volumes 与数据边界

正式部署至少持久化：

- PostgreSQL 数据。
- Redis 数据。
- MinIO 对象。
- OpenSearch 索引。
- Certbot 证书、账户和续期状态。
- ACME webroot、Certbot work/log。
- 可选 Prometheus、Alertmanager、Grafana 数据。

原则：

- named volumes 由 Compose 管理，不写入 Git 工作区。
- 停止、重建 API/Worker/gateway 不删除数据卷。
- `docker compose down` 默认保留数据。
- 破坏性清理统一使用 `manage.ps1 down -Volumes`；启用监控时同时带 `-Monitoring`。底层 `docker compose down -v` 若缺少 profile 会遗漏对应 volumes，也不会删除 Windows TLS 续期、备份轮换和恢复演练计划任务。
- OpenSearch 索引以 PostgreSQL 为事实来源，仍应保留重建索引脚本和演练流程。
- Preview 临时目录属于可清理数据，不作为原文件或唯一预览事实来源。

## 10. Gateway 安全边界

gateway 必须负责：

- 当前默认本机 HTTP `18080/19000` 入口。
- 公网模式通过 `-Tls` 使用 ACME bootstrap、证书只读挂载、TLS server block、HTTP 到 HTTPS 跳转和 `80/443` Host 分流。
- API 与存储请求分流。
- 仅在 API Host 下代理 `/grafana/`，不发布 Grafana 端口。
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
- HTTP-01 challenge 只允许 `/.well-known/acme-challenge/`；本机 API/S3 与 TLS 模板都拒绝未知 Host，本机 S3 仅额外允许 `localhost`/`127.0.0.1`。
- 续期由宿主 PowerShell 命令或同一 Windows 用户的计划任务触发，不向容器挂载 Docker socket。
- 当前机器已用自签名双域名证书在标准宿主 `80/443` 启动完整正式编排，验证 HTTP `308`、API `/healthz`/`/readyz`、HSTS、MinIO CORS、S3v4 对象往返、未知 Host 拒绝、临时 one-off bootstrap、原 gateway 恢复、大小写无关计划任务删除和全部卷/端口清理。真实受信证书、外部 DNS/网络、浏览器信任链和 Certbot renewal lineage 实际续期仍需在生产网络验收。

## 11. 自动化备份、校验、轮换与隔离恢复

`v0.4.0` 已通过 `deploy/windows/manage.ps1` 交付 `backup`、`backup-verify`、`restore`、`backup-retention` 和 `restore-drill`。脚本从 `docker compose config --format json` 获取真实 project、network、service image 和 physical volume name，不手工拼接 Compose 资源名。备份、恢复、`up`、`down` 和 TLS 写操作共用按 project 名称派生的 Windows named mutex；`backup`、`restore` 还会按每个 source/target physical volume name 获取独立 mutex，防止不同 Compose project 通过同一物理卷并发维护。

### 11.1 备份内容与一致性

`backup` 会在维护窗口按 gateway、API/beat、各类 Worker、MinIO/Redis/OpenSearch 的顺序静默写入面，并逐服务记录 source 容器 ID、原始 `running`/`exited` 状态和 health。PostgreSQL 使用 custom-format `pg_dump`；MinIO、Redis、OpenSearch 和 `tls-certificates` 使用停止状态原始卷 tar。备份完成或中途失败后，脚本都会恢复并对账 source 原运行、退出与健康状态。

所有 `pg_dump`、卷归档、tar 安全扫描、卷清理和 PostgreSQL 恢复辅助容器统一带 `--pull never`、CPU、memory、memory-swap 与 PID 限额。默认值为 `DRIVE_BACKUP_HELPER_CPU_LIMIT=0.50`、`DRIVE_BACKUP_HELPER_MEMORY_LIMIT=512m`、`DRIVE_BACKUP_HELPER_PIDS_LIMIT=128`，memory-swap 与 memory 相同，因此不额外占用 Docker swap；内存配置只接受 `64m` 至 `4g`。`DRIVE_BACKUP_GZIP_LEVEL=1` 和 `DRIVE_BACKUP_PG_DUMP_COMPRESSION_LEVEL=1` 优先降低 CPU 峰值；正式卷归档创建后不再立刻额外执行一次完整 `tar -tzf`，但发布前仍会执行完整工件校验和隔离 tar 预扫描，恢复 rollback archive 仍保留创建后立即校验。

正式备份目录只由校验通过的 `.partial-*` staging 原子发布，主要内容包括：

- `postgres/postgres.dump`
- `volumes/minio-data.tar.gz`
- `volumes/redis-data.tar.gz`
- `volumes/opensearch-data.tar.gz`
- `volumes/tls-certificates.tar.gz`
- `secrets/environment.cms`
- 归档时的 `compose.windows.yml` 与 Nginx templates
- UTF-8 `manifest.json` 与 `manifest.sha256`

manifest 记录工件大小和 SHA-256、source project、逐服务原状态、精确 Compose SHA-256、项目版本、Git commit、Alembic revision、PostgreSQL WAL LSN、CMS 证书 thumbprint，以及 `DRIVE_S3_BUCKET`、`DRIVE_OPENSEARCH_INDEX_NAME`、`DRIVE_TLS_CERT_NAME` lineage 名称。镜像清单覆盖 16 个无 profile 默认服务（`gateway`、`web`、`api`、`migration`、`seed`、`minio-init`、`beat`、5 个 Worker、PostgreSQL、Redis、MinIO、OpenSearch），每项 image ID 都来自该服务实际 Compose 容器，并在备份时确认与当前 image reference 指向的本地 image ID 一致。

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
- 要求 16 个默认服务逐项具有相同 image reference 和 image ID；归档工具也必须与 manifest 中 PostgreSQL 实际容器 image ID 一致。
- 先在 `--network none`、只读根文件系统、只读备份 bind、`--cap-drop ALL`、`no-new-privileges` 的容器中检查 tar 路径，再预解包到一次性临时 Docker volume；拒绝绝对路径、父目录穿越、硬链接、块/字符设备、FIFO、socket、悬空 symlink 和解析后越出临时卷的 symlink。
- tar 检查结束后必须删除临时卷；扫描失败或临时卷清理失败都会使校验失败。

因此，复制备份到另一台主机时，应先检出 manifest 记录的精确 Git commit，保持相同 `compose.windows.yml`、项目版本和 bucket/index/TLS lineage 配置，并准备全部 16 个服务对应的固定镜像，再执行 `backup-verify`。

仓库内真实集成脚本不会构建或拉取镜像。先执行只读 preflight：

```powershell
.\deploy\windows\tests\backup-restore.integration.ps1 -PreflightOnly
```

preflight 会渲染 Compose 并逐一检查本地镜像；缺少任一镜像时在创建证书、容器或卷之前快速退出。完整执行时固定 `COMPOSE_PARALLEL_LIMIT=1`、API/Worker 并发为 `1`，并降低测试专用 CPU/内存上限；OpenSearch 测试预算固定为 `1 CPU / 1280m` 容器内存和 `512m` JVM heap，正式 `.env.windows.example` 的 `2 CPU / 3g` 容器内存和 `1g` JVM heap 不受影响。默认恢复使用 `-NoStartAfterRestore`，随后只启动 PostgreSQL、Redis、MinIO、OpenSearch 验证恢复点。只有需要重新验收 gateway、API、全部 Worker 和 beat 时才显式执行：

```powershell
.\deploy\windows\tests\backup-restore.integration.ps1 -FullStackRestore
```

集成脚本不再重复调用一次成功的 `backup-verify`：`backup` 在发布前已经执行同一完整校验，`restore` 开始前还会再次完整校验；损坏 manifest 的拒绝用例继续保留。各阶段会分别输出镜像 preflight、source 启动、备份、source 停止、恢复和数据服务启动耗时。若任一阶段失败，脚本会在删除 source/target project 前输出 Compose 状态，并为异常数据服务、初始化任务或 API 打印 health、OOM、退出码和最近 120 行日志。

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

恢复前脚本会再次执行完整备份校验，并要求全部 16 个默认服务的 target image reference 和本地 image ID 与 manifest 一致。target 有运行中或过渡态容器时始终拒绝恢复；source/target 任一 physical volume 重叠、已有卷 Compose project/logical-volume 标签不符，或卷仍附着到 foreign container 时也会拒绝。默认还会拒绝已有容器和非空目标卷。

`-ForceRestore` 只用于显式清理已停止的 target 容器或非空卷，不会跳过同 project、运行状态、卷重叠/标签/attachment、路径、SHA-256、tar、dump、代码/configuration lineage 或镜像一致性门禁。清空任何原非空目标卷前，脚本会在 Windows 临时目录创建 restricted ACL rollback archive；正常恢复成功后删除它。恢复一旦提交，后续归档清理失败只会返回 maintenance cleanup error、保留并报告归档路径，不会再次清空或回滚已经恢复的数据。`-NoStartAfterRestore` 会在 PostgreSQL dump 恢复和 Alembic revision 校验后停止 PostgreSQL，不启动完整业务栈，适合先检查数据卷和解密配置。

`-RestoreEnvironmentOutput` 必须是仓库和备份目录外的绝对、尚不存在文件路径，父目录必须预先存在且不得经过 NTFS reparse point；它不会覆盖当前 target 的 `-EnvFile`。CMS 明文先保存在 PowerShell 内存中，只有本次恢复模式的数据卷、PostgreSQL、Alembic revision 和镜像门禁全部验证成功后，才在最后一步写入同目录 restricted ACL 临时文件并原子改名发布；未使用 `-NoStartAfterRestore` 时还会先完成完整服务健康与实际容器 image ID 对账。原子发布前失败不会创建输出；若发布竞态中目标路径被其他进程创建，脚本会保留该 foreign file，不在恢复失败清理中删除。

未使用 `-NoStartAfterRestore` 时，脚本会启动完整 target Compose project 并等待健康，再逐项核对 16 个默认服务实际容器 image ID。恢复中途失败后，脚本会执行 Compose down、删除本轮新建卷、把原本为空的既有卷清回空状态，并从 rollback archive 还原 `-ForceRestore` 前的原非空卷；卷回滚失败时会保留并报告受限 ACL rollback archive 绝对路径。target 不会以半恢复状态继续对外提供服务。

### 11.5 备份轮换与周期恢复演练

轮换先完整读取托管备份目录名、`manifest.json`、`manifest.sha256` 和 manifest 内 backup ID；目录名与 manifest 不一致、checksum 损坏、reparse point 或 ACL 不合格时立即失败。默认保留最近 8 份，并保留所有 35 天内的备份；只有同时超出最少份数和保留天数的目录才进入删除候选。

预览与执行：

```powershell
.\deploy\windows\manage.ps1 backup-retention `
    -EnvFile .env.windows `
    -BackupDirectory "D:\enterprise-drive-backups"

.\deploy\windows\manage.ps1 backup-retention `
    -EnvFile .env.windows `
    -BackupDirectory "D:\enterprise-drive-backups" `
    -ApplyRetention
```

可通过 `-RetentionDays`、`-RetentionCount` 覆盖 `.env.windows` 的默认值。每次执行都会在备份根的 `.governance` 子目录写 restricted ACL JSON，记录扫描、保留、候选和实际删除路径。

隔离演练默认选择与当前 Compose project 匹配的最新托管备份：

```powershell
.\deploy\windows\manage.ps1 restore-drill `
    -EnvFile .env.windows `
    -BackupDirectory "D:\enterprise-drive-backups"
```

也可传入 `-BackupPath` 指定一个备份；两者必须且只能提供一个。演练使用随机 `enterprise-drive-restore-drill-*` target project，调用同一完整恢复门禁并保持 target 停止，随后执行 Compose down、删除 target volumes，并确认没有残留 target 容器/卷。成功或失败都写入 `DRIVE_GOVERNANCE_RECORD_ROOT\restore-drills`；异常会在错误消息中返回记录路径。

注册计划任务：

```powershell
.\deploy\windows\manage.ps1 backup-retention-register `
    -EnvFile .env.windows `
    -BackupDirectory "D:\enterprise-drive-backups" `
    -BackupRetentionAt 02:13

.\deploy\windows\manage.ps1 restore-drill-register `
    -EnvFile .env.windows `
    -BackupDirectory "D:\enterprise-drive-backups" `
    -RestoreDrillAt 04:21 `
    -RestoreDrillDayOfWeek Sunday
```

删除：

```powershell
.\deploy\windows\manage.ps1 backup-retention-unregister
.\deploy\windows\manage.ps1 restore-drill-unregister
```

计划任务使用当前 Windows 用户和当前 PowerShell executable；执行恢复演练时 Docker Desktop Linux engine 必须可用。仓库移动、环境文件/备份目录变化或运行用户变化后，应删除并重新注册。

### 11.6 安全与兼容边界

- Windows CMS 只加密 `.env.windows`。PostgreSQL dump、MinIO/Redis/OpenSearch 原始卷 tar 和包含 TLS 私钥的证书卷 tar 不具备完整包级应用层加密，必须依赖备份宿主 BitLocker、脚本自动应用的 restricted NTFS ACL 和加密外部介质。
- `manifest.sha256` 和工件 SHA-256 只校验完整性，不认证备份制作者身份。需要认证来源时，应另外使用受保护签名、受控传输和可审计保管链。
- Redis/OpenSearch 使用停止状态原始卷归档，只支持相同 image reference、相同 image ID、单节点同拓扑。跨版本或拓扑变化应使用 Redis/OpenSearch 支持的迁移、导出或快照机制。
- `-ForceRestore` rollback archive 是失败时的尽力恢复机制；底层卷驱动、磁盘或 Docker 故障仍可能需要人工处理，因此发现回滚异常后不得删除脚本报告的受限 ACL 归档。
- PostgreSQL 是核心事实来源；Redis 主要保存缓存、限流和队列状态，OpenSearch 索引可由 PostgreSQL 与对象存储重建，但仍应记录重建步骤和耗时。
- 当前固定 MinIO Server/Client 镜像仍有 16/9 个 Critical 唯一 ID 基线。供应链门禁只阻断允许集之外的新 Critical；正式 `v0.4.0` tag/Release 在受支持修复镜像或可审计补丁镜像完成替换与重扫前保持阻塞，详见 `docs/minio-security-risk.md`。
- 备份轮换和恢复演练已经自动化，但离线副本、容量告警、备份来源签名和完整包加密仍需后续治理。

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

CI 使用变更范围路由，不再让所有提交重复执行全部部署门禁：`compose.windows.yml` 或 `.env.windows.example` 会同时进入 backend、Windows 和 MinIO 门禁；`deploy/windows/**/*.ps1` 只进入 Windows smoke；Nginx/监控配置进入 backend 的 Compose/template/smoke 路径。Rust crate 源码/测试只进入 `rust-desktop`，Tauri UI/配置/图标/签名只进入安装包，Tauri `src-tauri` Rust 入口才同时进入两者；CI workflow/router 和文档变更只保留 changes 路由校验。安装包 job 不再使用“任意 push 都执行”的兜底条件，只有安装包相关 scope 或手工完整运行才启动。MinIO Server/Client SBOM 与 Grype 在同一 runner 中依次生成和扫描，并与 Rust 依赖策略一起保留每周一 UTC 03:17 的定时门禁。

发布检查：

- CI 的 ruff、format、mypy、pytest 通过。
- `docker compose ... config` 通过。
- 应用镜像构建通过。
- migration 一次性服务退出码为 0。
- `/readyz` 真实数据库探针通过。
- gateway 的 API 与 S3 外部端点可访问；公网模式还要检查 HTTP `308`、证书链、HSTS、双域名 Host 分流和真实预签名 PUT/GET。
- Worker 已连接预期队列。
- `beat` 只有一个有效实例。
- Preview/OCR 工具版本与 Tesseract `eng`、`chi_sim` 语言包可读取。
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
Invoke-WebRequest http://localhost:18080/metrics
```

Worker 指标从 Compose 网络内检查，不临时发布宿主端口：

```powershell
docker compose -f compose.windows.yml --env-file .env.windows `
    exec worker-maintenance `
    python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:9100/metrics', timeout=3).read().decode())"
```

隔离的真实 Docker 可观测性 smoke：

```powershell
Set-Location backend
uv run python scripts/smoke_observability_docker.py `
    --image enterprise-drive-backend:windows-local
Set-Location ..
```

该脚本使用真实 PostgreSQL、Redis、2-worker API 和 maintenance Worker，验证多进程聚合、Outbox/Search gauge、真实 Celery task 和 request/task/trace 日志，并自动清理临时容器和网络。

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

### 图片或扫描 PDF OCR 未生成正文

在 `worker-search` 内检查：

```powershell
docker compose -f compose.windows.yml --env-file .env.windows exec worker-search tesseract --version
docker compose -f compose.windows.yml --env-file .env.windows exec worker-search tesseract --list-langs
docker compose -f compose.windows.yml --env-file .env.windows exec worker-search pdftoppm -v
```

确认语言列表同时包含 `eng` 和 `chi_sim`，并检查 `DRIVE_SEARCH_OCR_ENABLED`、页数/像素/渲染体量、命令超时、Search Worker 独立 tmpfs 和 outbox 错误原因。

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
