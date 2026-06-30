# 后端工程

本目录承载企业网盘后端，使用 Python 3.12+、uv、FastAPI、SQLAlchemy、PostgreSQL、Redis、S3 兼容对象存储、OpenSearch 和 Celery。

## 本地准备

```bash
uv python install 3.12
uv sync --all-extras --dev
copy .env.example .env
docker compose up -d postgres redis minio opensearch
uv run alembic upgrade head
uv run python -m scripts.seed_admin
uv run fastapi dev app/main.py --host 127.0.0.1 --port 18080
uv run celery -A app.infrastructure.queue.celery_app worker -Q audit -l info
```

生产环境的 Nginx 使用宿主机安装和管理，不放入 Docker Compose；本目录的 Compose 只用于本地依赖服务。

## 常用验证

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest
```

## 当前能力

- FastAPI 应用入口。
- 配置加载，统一使用 `DRIVE_` 环境变量前缀。
- JSON 结构化日志。
- `X-Request-ID` 中间件。
- 统一错误响应。
- `/healthz` 和 `/readyz` 健康检查。
- `/api/v1/ping` 基础 API 连通性检查。
- `tenants`、`users`、`refresh_tokens` 基础表和 Alembic 初始迁移。
- 本地账号登录、JWT access token、refresh token 轮换。
- 旧 refresh token 复用检测与 token family 吊销。
- `audit_logs`、`outbox_events` 基础表和迁移。
- 登录、刷新令牌和 refresh token 复用检测的认证审计事件。
- Celery app 基础配置和 `audit.dispatch_outbox` 任务。
- outbox dispatcher，支持成功发送、失败重试和 dead 状态。
- `spaces`、`nodes`、`file_blobs`、`file_versions` 基础表和迁移。
- 空间创建时同步创建空间根目录节点。
- 文件夹创建、目录子节点列表和签名 cursor pagination。
- 文件树节点重命名、移动、删除到回收站和恢复。
- 空间创建、文件夹创建、重命名、移动、删除和恢复审计事件。
- 管理员 seed 脚本。

## 认证接口

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `GET /api/v1/auth/me`

默认管理员由 `.env` 中的 `DRIVE_ADMIN_*` 配置控制。首次本地启动后运行 `uv run python -m scripts.seed_admin` 创建管理员，并在首次登录后尽快修改默认密码。

## 空间和文件树接口

- `POST /api/v1/spaces`
- `GET /api/v1/spaces`
- `POST /api/v1/files/folders`
- `GET /api/v1/files?space_id=...&parent_id=...`
- `PATCH /api/v1/files/{node_id}`
- `POST /api/v1/files/{node_id}/move`
- `DELETE /api/v1/files/{node_id}`
- `POST /api/v1/files/{node_id}/restore`

当前空间和文件树接口使用临时访问边界：只允许当前租户下的空间拥有者访问。空间成员、目录 ACL、继承权限和拒绝优先策略将在 Sprint 4 权限系统中接入。

文件夹名称会进行 Unicode NFC 归一化并去除首尾空白，禁止 `/`、`\`、NUL、控制字符和路径穿越片段。同一目录下未删除节点的名称由数据库唯一索引兜底，根目录由 `tenant_id + space_id` 唯一索引兜底。

根目录不允许重命名、移动或删除。当前目录删除和恢复会同步遍历当前子树，适合 Sprint 2 骨架和普通目录验证；大目录后续需要改为后台任务或引入 `deleted_root_id` 等冗余状态来避免长事务。
