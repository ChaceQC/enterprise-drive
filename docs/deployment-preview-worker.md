# 预览与内容处理 Worker 部署说明

本文说明 Windows 11 + Docker Desktop 正式环境中 `preview` 与 `search` 内容处理队列的部署边界。两个 Worker 共用包含 Pillow、Poppler `pdftoppm`、LibreOffice `soffice` 和 Tesseract 的内容处理镜像，但使用独立进程、队列和 tmpfs，必须与 API、审计和权限 Worker 分离。

## 基本原则

- Windows 11 正式部署使用 Docker Desktop 的 WSL2 后端和 Linux containers；根 `compose.windows.yml` 是唯一正式编排入口。
- Nginx gateway 在 Compose 内运行，并且是唯一发布宿主端口的服务；Preview Worker、API、Redis、数据库、OpenSearch 和 SeaweedFS 都只加入内部网络。
- `backend/docker-compose.yml` 只用于本地依赖开发，不作为生产编排清单。
- `preview` Worker 只消费 `preview` 队列；`search` Worker 只消费 `search` 队列，OCR/旧格式转换不会进入 `audit`、`permission` 或 `maintenance` 队列。
- 内容处理镜像需要安装 LibreOffice、Poppler 和 Tesseract，并在构建时确认 `soffice`、`pdftoppm`、`tesseract` 以及 `eng`、`chi_sim` 语言包可用。
- 临时目录必须放在可限额、可清理的分区或容器 `emptyDir`，不要和系统根分区混用。

## 必要工具

工具安装在 Preview Worker 的 Linux 容器镜像中，Dockerfile 构建阶段应使用发行版包管理器安装并立即验证：

```bash
sudo apt-get update
sudo apt-get install -y libreoffice poppler-utils tesseract-ocr tesseract-ocr-eng tesseract-ocr-chi-sim fonts-noto-cjk
soffice --version
pdftoppm -v
tesseract --version
tesseract --list-langs
```

Windows 宿主机只需要 Docker Desktop，不要求额外安装 LibreOffice、Poppler 或 Tesseract。工具版本通过 PowerShell 在容器内检查：

```powershell
docker compose --env-file .env.windows -f compose.windows.yml exec worker-preview soffice --version
docker compose --env-file .env.windows -f compose.windows.yml exec worker-preview pdftoppm -v
docker compose --env-file .env.windows -f compose.windows.yml exec worker-search tesseract --version
docker compose --env-file .env.windows -f compose.windows.yml exec worker-search tesseract --list-langs
```

镜像内缺少工具时，Office/PDF 预览或 OCR/旧格式抽取会按配置标记为 `unsupported`/`skipped` 并记录明确原因。

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
DRIVE_PREVIEW_ARTIFACT_RETENTION_DAYS=30
DRIVE_PREVIEW_CLEANUP_INTERVAL_SECONDS=86400
DRIVE_SEARCH_COMPLEX_EXTRACT_MAX_BYTES=20971520
DRIVE_SEARCH_EXTRACT_MAX_CHARS=1000000
DRIVE_SEARCH_OCR_ENABLED=true
DRIVE_SEARCH_OCR_LANGUAGES=eng+chi_sim
DRIVE_SEARCH_OCR_MAX_PAGES=20
DRIVE_SEARCH_OCR_PDF_DPI=144
DRIVE_SEARCH_OCR_MAX_PIXELS=100000000
DRIVE_SEARCH_OCR_MAX_RENDERED_BYTES=104857600
DRIVE_SEARCH_OCR_COMMAND_TIMEOUT_SECONDS=60
```

`DRIVE_PREVIEW_COMMAND_TIMEOUT_SECONDS` 限制预览外部命令；OCR 配置共同限制源文件、页数、像素、渲染体量、正文长度和命令时间。`DRIVE_PREVIEW_ARTIFACT_RETENTION_DAYS` 与周期任务 `preview.cleanup_artifacts` 控制旧版本和孤儿预览产物保留期。

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

`worker-search` 同样使用 `enterprise-drive-preview:VERSION` 内容处理镜像，但只消费 `search` 队列；默认并发为 `2`、`--max-tasks-per-child=20`，并使用 `SEARCH_TMPFS_SIZE` 控制的独立 `/tmp/enterprise-drive` tmpfs。两个 Worker 的临时目录不能互相复用。

资源基线：

- CPU 上限建议 `2.0`，并发默认 `1`。
- 默认内存上限为 `3 GiB`。
- 默认临时目录上限为 `1 GiB`，可通过 `PREVIEW_TMPFS_SIZE` 调整；不得复用 PostgreSQL、SeaweedFS 或 OpenSearch 数据卷。
- 两个内容处理 Worker 均使用 `--max-tasks-per-child=20`，用于回收 LibreOffice/Poppler/Tesseract 长时间运行产生的内存碎片。
- Preview Worker 只消费 `preview` 队列；`audit`、`permission`、`search`、`maintenance` 使用其他 Worker。
- 外部命令超时、Celery 软/硬超时和速率限制必须同时启用。

Docker Desktop 设置中应为整个项目预留至少 4 个 CPU、8 GiB 内存和足够磁盘；实际值根据 OpenSearch、预览并发和文件体量调整。临时目录和预览产物清理由任务生命周期与维护任务共同保证。

## 未来可选部署

Kubernetes Deployment、Linux systemd 服务可在后续迁移到其他宿主平台时补充。它们不是当前 Windows 11 正式部署路径，也不得替代根 `compose.windows.yml` 的交付和验证。

## 监控与告警

`worker-preview` 在 Compose 内部 `9100` 暴露 Prometheus 文本格式指标，不发布宿主端口。API `/metrics` 不跨容器聚合 Preview Worker；监控系统必须把 `worker-preview:9100` 作为独立 scrape target。当前包括：

```text
worker_tasks_total{task="preview.dispatch_outbox",queue="preview",status="..."}
worker_task_duration_seconds{task="preview.dispatch_outbox",queue="preview"}
preview_failures_total{status="failed|unsupported",reason="..."}
preview_artifact_cleanup_total{status="stale_scanned|stale_cleaned|orphan_scanned|orphan_cleaned|planned|failed"}
```

容器内检查：

```powershell
docker compose --env-file .env.windows -f compose.windows.yml `
    exec worker-preview `
    python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:9100/metrics', timeout=3).read().decode())"
```

建议至少配置以下告警：

- `preview_failures_total` 在 10 分钟内持续增长。
- `preview_artifact_cleanup_total{status="failed"}` 在维护窗口内持续增长。
- `preview` 队列积压超过阈值。
- Worker 内存接近限制或频繁 OOM。
- 临时磁盘使用率超过 80%。
- `office_renderer_missing`、`pdf_renderer_missing` 或 `ocr_tool_unavailable` 出现，说明节点缺少系统工具、语言包或 PATH 配置错误。

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
docker compose --env-file .env.windows -f compose.windows.yml exec worker-search tesseract --version
docker compose --env-file .env.windows -f compose.windows.yml exec worker-search tesseract --list-langs
```

如果当前环境暂时不能执行 Docker Desktop 实测，需要在 `PROJECT_PROGRESS.md` 记录验证边界，并保证缺失工具场景已有测试覆盖；最终发布前必须在实际 Preview Worker 容器内完成工具版本、转码、资源限制和任务重试验证。
