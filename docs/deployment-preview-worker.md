# 预览 Worker 部署说明

本文说明 `preview` 队列的生产部署边界。预览 Worker 会运行 Pillow、Poppler `pdftoppm` 和 LibreOffice `soffice` 等外部工具，必须与 API Worker 分离部署，并设置 CPU、内存、临时磁盘和队列速率限制。

## 基本原则

- 生产 Nginx 使用宿主机安装和管理，只暴露 `80/443`，反向代理到 API 内部端口；不要把 Nginx 放入 Docker Compose 或应用容器。
- `backend/docker-compose.yml` 只用于本地依赖服务，不作为生产编排清单；生产 API、Worker、数据库、Redis、OpenSearch、对象存储需要独立部署或用 Kubernetes/系统服务管理。
- `preview` Worker 只消费 `preview` 队列，避免 LibreOffice/Poppler 转码拖慢 `audit`、`permission`、`search` 和 `maintenance` 队列。
- Worker 节点需要安装 LibreOffice 和 Poppler，并在启动前确认 `soffice` 和 `pdftoppm` 可执行。
- 临时目录必须放在可限额、可清理的分区或容器 `emptyDir`，不要和系统根分区混用。

## 必要工具

Ubuntu/Debian 示例：

```bash
sudo apt-get update
sudo apt-get install -y libreoffice poppler-utils fonts-noto-cjk
soffice --version
pdftoppm -v
```

Windows 开发机可安装 LibreOffice 和 Poppler，并把 `soffice`、`pdftoppm` 所在目录加入 `PATH`。本机缺少工具时，Office/PDF 预览会按配置标记为 `unsupported` 并记录明确原因。

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

## systemd 示例

适用于非 Kubernetes 单机或小规模部署。示例只展示 Worker，API 和 Nginx 应独立服务化。

```ini
[Unit]
Description=Enterprise Drive preview worker
After=network.target redis.service

[Service]
User=drive
Group=drive
WorkingDirectory=/opt/enterprise-drive/backend
EnvironmentFile=/etc/enterprise-drive/backend.env
Environment=TMPDIR=/var/lib/enterprise-drive/preview-tmp
ExecStart=/usr/local/bin/uv run celery -A app.infrastructure.queue.celery_app worker -Q preview -l info --concurrency=1 --max-tasks-per-child=20
Restart=on-failure
RestartSec=5s
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/enterprise-drive/preview-tmp
MemoryMax=2G
CPUQuota=200%
TasksMax=256
TimeoutStopSec=90

[Install]
WantedBy=multi-user.target
```

建议为 `/var/lib/enterprise-drive/preview-tmp` 单独挂载或设置磁盘配额，例如 4 到 8 GiB。部署脚本应定期清理陈旧临时目录；正常任务会使用临时目录并在进程内释放。

## Kubernetes 示例

预览 Worker 应单独 Deployment，不和 API 混跑。

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: worker-preview
spec:
  replicas: 1
  selector:
    matchLabels:
      app: worker-preview
  template:
    metadata:
      labels:
        app: worker-preview
    spec:
      containers:
        - name: worker
          image: enterprise-drive-backend:latest
          command:
            - uv
            - run
            - celery
            - -A
            - app.infrastructure.queue.celery_app
            - worker
            - -Q
            - preview
            - -l
            - info
            - --concurrency=1
            - --max-tasks-per-child=20
          envFrom:
            - secretRef:
                name: enterprise-drive-backend-env
          env:
            - name: TMPDIR
              value: /tmp/preview
          resources:
            requests:
              cpu: "500m"
              memory: "1Gi"
              ephemeral-storage: "2Gi"
            limits:
              cpu: "2"
              memory: "2Gi"
              ephemeral-storage: "8Gi"
          volumeMounts:
            - name: preview-tmp
              mountPath: /tmp/preview
      volumes:
        - name: preview-tmp
          emptyDir:
            sizeLimit: 8Gi
```

容器镜像必须包含 LibreOffice、Poppler 和常用字体；如果这些工具由宿主机提供，则不要把该 Pod 调度到缺少工具的节点。

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

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest
uv run alembic upgrade head --sql
soffice --version
pdftoppm -v
```

如果当前环境无法安装 LibreOffice 或 Poppler，需要在 `PROJECT_PROGRESS.md` 记录验证边界，并保证缺失工具场景已有测试覆盖。
