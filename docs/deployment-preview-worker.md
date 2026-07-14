# 预览 Worker 部署说明

本文说明 Windows 11 + Docker Desktop 正式环境中 `preview` 队列的部署边界。预览 Worker 会运行 Pillow、Poppler `pdftoppm` 和 LibreOffice `soffice` 等外部工具，必须在根 `compose.windows.yml` 中与 API 和其他 Worker 分离，并设置 CPU、内存、临时磁盘和队列速率限制。

## 基本原则

- Windows 11 正式部署使用 Docker Desktop 的 WSL2 后端和 Linux containers；根 `compose.windows.yml` 是唯一正式编排入口。
- Nginx gateway 在 Compose 内运行，并且是唯一发布宿主端口的服务；Preview Worker、API、Redis、数据库、OpenSearch 和 MinIO 都只加入内部网络。
- `backend/docker-compose.yml` 只用于本地依赖开发，不作为生产编排清单。
- `preview` Worker 只消费 `preview` 队列，避免 LibreOffice/Poppler 转码拖慢 `audit`、`permission`、`search` 和 `maintenance` 队列。
- Worker 节点需要安装 LibreOffice 和 Poppler，并在启动前确认 `soffice` 和 `pdftoppm` 可执行。
- 临时目录必须放在可限额、可清理的分区或容器 `emptyDir`，不要和系统根分区混用。

## 必要工具

工具安装在 Preview Worker 的 Linux 容器镜像中，Dockerfile 构建阶段应使用发行版包管理器安装并立即验证：

```bash
sudo apt-get update
sudo apt-get install -y libreoffice poppler-utils fonts-noto-cjk
soffice --version
pdftoppm -v
```

Windows 宿主机只需要 Docker Desktop，不要求额外安装 LibreOffice 或 Poppler。工具版本通过 PowerShell 在容器内检查：

```powershell
docker compose --env-file .env.windows -f compose.windows.yml exec worker-preview soffice --version
docker compose --env-file .env.windows -f compose.windows.yml exec worker-preview pdftoppm -v
```

镜像内缺少工具时，Office/PDF 预览会按配置标记为 `unsupported` 并记录明确原因。

## 环境变量

预览相关关键配置：

```bash
DRIVE_PREVIEW_OFFICE_COMMAND=soffice
DRIVE_PREVIEW_OFFICE_MAX_PDF_BYTES=52428800
DRIVE_PREVIEW_PDF_COMMAND=pdftoppm
DRIVE_PREVIEW_PDF_DPI=144
DRIVE_PREVIEW_PDF_MAX_RENDERED_BYTES=52428800
DRIVE_PREVIEW_COMMAND_TIMEOUT_SECONDS=30
DRIVE_PREVIEW_TASK_SOFT_TIME_LIMIT_SECONDS=120
DRIVE_PREVIEW_TASK_TIME_LIMIT_SECONDS=150
DRIVE_PREVIEW_TASK_RATE_LIMIT=30/m
```

`DRIVE_PREVIEW_COMMAND_TIMEOUT_SECONDS` 限制单次外部命令；Celery 软/硬超时限制整个 `preview.dispatch_outbox` 任务；速率限制用于削峰，不能替代 CPU、内存和临时磁盘配额。

## Windows Docker Compose 服务

根 `compose.windows.yml` 中的 `worker-preview` 是正式配置来源。服务至少满足：

```yaml
worker-preview:
  image: enterprise-drive-preview:VERSION
  command:
    - celery
    - -A
    - app.infrastructure.queue.celery_app
    - worker
    - --queues=preview
    - --hostname=preview@%h
    - --loglevel=INFO
    - "--concurrency=${PREVIEW_WORKER_CONCURRENCY:-1}"
    - "--max-tasks-per-child=${PREVIEW_WORKER_MAX_TASKS_PER_CHILD:-20}"
  env_file:
    - .env.windows
  environment:
    TMPDIR: /tmp/enterprise-drive
  cpus: 2.0
  mem_limit: 3g
  tmpfs:
    - /tmp/enterprise-drive:size=1073741824
  restart: unless-stopped
```

这是约束示例，最终字段以根 `compose.windows.yml` 为准。Docker Compose 非 Swarm 场景应使用 `cpus`、`mem_limit` 等实际生效的服务级限制，不要只写可能被忽略的 Swarm `deploy.resources`。

资源基线：

- CPU 上限建议 `2.0`，并发默认 `1`。
- 默认内存上限为 `3 GiB`。
- 默认临时目录上限为 `1 GiB`，可通过 `PREVIEW_TMPFS_SIZE` 调整；不得复用 PostgreSQL、MinIO 或 OpenSearch 数据卷。
- `--max-tasks-per-child=20` 用于回收 LibreOffice/Poppler 长时间运行产生的内存碎片。
- Preview Worker 只消费 `preview` 队列；`audit`、`permission`、`search`、`maintenance` 使用其他 Worker。
- 外部命令超时、Celery 软/硬超时和速率限制必须同时启用。

Docker Desktop 设置中应为整个项目预留至少 4 个 CPU、8 GiB 内存和足够磁盘；实际值根据 OpenSearch、预览并发和文件体量调整。临时目录和预览产物清理由任务生命周期与维护任务共同保证。

## 未来可选部署

Kubernetes Deployment、Linux systemd 服务可在后续迁移到其他宿主平台时补充。它们不是当前 Windows 11 正式部署路径，也不得替代根 `compose.windows.yml` 的交付和验证。

## 监控与告警

`/metrics` 暴露 Prometheus 文本格式指标，当前包括：

```text
preview_failures_total{status="failed|unsupported",reason="..."}
orphan_object_cleanup_total{status="scanned|skipped|planned|cleaned|failed"}
```

建议至少配置以下告警：

- `preview_failures_total` 在 10 分钟内持续增长。
- `orphan_object_cleanup_total{status="failed"}` 在维护窗口内持续增长。
- `preview` 队列积压超过阈值。
- Worker 内存接近限制或频繁 OOM。
- 临时磁盘使用率超过 80%。
- `office_renderer_missing` 或 `pdf_renderer_missing` 出现，说明节点缺少系统工具或 PATH 配置错误。

## 发布检查

发布前检查：

```powershell
Push-Location backend
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest
uv run alembic upgrade head --sql
Pop-Location
docker compose --env-file .env.windows -f compose.windows.yml config --quiet
docker compose --env-file .env.windows -f compose.windows.yml exec worker-preview soffice --version
docker compose --env-file .env.windows -f compose.windows.yml exec worker-preview pdftoppm -v
```

如果当前环境暂时不能执行 Docker Desktop 实测，需要在 `PROJECT_PROGRESS.md` 记录验证边界，并保证缺失工具场景已有测试覆盖；最终发布前必须在实际 Preview Worker 容器内完成工具版本、转码、资源限制和任务重试验证。
