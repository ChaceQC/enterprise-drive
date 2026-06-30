# 后端工程

本目录承载企业网盘后端，使用 Python 3.12+、uv、FastAPI、SQLAlchemy、PostgreSQL、Redis、S3 兼容对象存储、OpenSearch 和 Celery。

## 本地准备

```bash
uv python install 3.12
uv sync --all-extras --dev
copy .env.example .env
docker compose up -d postgres redis minio opensearch
uv run alembic upgrade head
uv run fastapi dev app/main.py --host 127.0.0.1 --port 18080
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
