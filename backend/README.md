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
- 管理员 seed 脚本。

## 认证接口

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `GET /api/v1/auth/me`

默认管理员由 `.env` 中的 `DRIVE_ADMIN_*` 配置控制。首次本地启动后运行 `uv run python -m scripts.seed_admin` 创建管理员，并在首次登录后尽快修改默认密码。
