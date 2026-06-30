# 企业网盘

企业网盘后端工程，目标是实现一个可试点上线的企业级文件管理服务。项目以《企业网盘开发者技术计划书.md》为技术基线，优先保障文件元数据、对象存储、权限、审计、搜索和异步任务之间的一致性。

## 技术基线

- Python 3.12+
- uv
- FastAPI
- SQLAlchemy 2.x
- PostgreSQL 16+
- Redis
- S3 兼容对象存储
- OpenSearch
- Celery
- Docker / Kubernetes
- 宿主机 Nginx

## 一期范围

- 本地账号登录、管理员 seed、JWT 刷新令牌轮换。
- 空间、文件树、文件版本、回收站、基础容量账本。
- S3 兼容对象存储上传下载，支持 multipart upload。
- 目录权限、空间角色、拒绝优先、权限缓存和高危动作二次校验。
- 内部分享、外链分享、提取码、过期、次数限制、撤销。
- 预览 Worker、搜索索引 Worker、审计 outbox dispatcher。
- Docker Compose 本地开发环境、Alembic migration、CI 质量门禁。

## 当前状态

当前仓库处于 Sprint 1 工程底座阶段，已建立 `backend` 后端工程、uv 依赖锁定、FastAPI 应用入口、配置加载、结构化日志、`X-Request-ID` 中间件、统一错误响应、健康检查、本地依赖 Compose 和后端 CI。认证基础能力已落地：租户、用户、refresh token 表，管理员 seed，本地账号登录、访问令牌和刷新令牌轮换。

本地后端验证：

```bash
cd backend
uv sync --all-extras --dev
uv run alembic upgrade head
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest
```

## 文档

- `AGENT.md`：开发协作约束。
- `PROJECT_PLAN.md`：执行版项目计划。
- `PROJECT_PROGRESS.md`：项目进度记录。
- `企业网盘开发者技术计划书.md`：完整技术计划书。
- `backend/README.md`：后端工程启动与验证说明。

## 部署说明

生产部署默认由宿主机 Nginx 暴露 `80/443` 并反向代理到内部应用服务。Nginx 不放入 Docker Compose 或应用容器；Docker Compose 只用于编排 API、Worker 和依赖服务。
