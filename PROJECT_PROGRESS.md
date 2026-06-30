# PROJECT_PROGRESS.md

## 2026-06-30

### 已完成

- 建立项目协作约束 `AGENT.md`。
- 明确生产部署时 Nginx 使用宿主机安装和管理，不放入 Docker。
- 建立项目 README、执行版项目计划和 Git 忽略规则。
- 创建 GitHub 公开仓库 `ChaceQC/enterprise-drive` 并推送初始提交。
- 创建日常开发分支 `dev`。
- 建立 `backend` 后端工程底座：uv 项目、FastAPI 应用入口、配置加载、结构化日志、`X-Request-ID` 中间件、统一错误响应、健康检查和 `/api/v1/ping`。
- 补充 Alembic 基础目录、SQLAlchemy 基类、本地依赖 Docker Compose、后端 README 和 GitHub Actions 后端 CI。
- 根据协作约束补充“缺少必要工具或依赖时自行安装或补齐”的规则。
- 补充 `tenants`、`users`、`refresh_tokens` SQLAlchemy 模型和 Alembic 初始迁移。
- 实现本地账号登录、JWT access token、refresh token 服务端哈希存储和 refresh token family 轮换。
- 实现旧 refresh token 复用检测，复用时吊销整个 token family。
- 实现 `/api/v1/auth/login`、`/api/v1/auth/refresh`、`/api/v1/auth/me`。
- 补充管理员 seed 脚本 `scripts/seed_admin.py`。
- 补充认证服务和认证 API 测试。
- 补充 `audit_logs`、`outbox_events` SQLAlchemy 模型和 Alembic 迁移。
- 实现审计写入服务，事务内同步写入 audit log 和 outbox event。
- 在登录成功、登录失败、刷新令牌成功、刷新令牌过期、用户失效和 refresh token 复用检测中写入认证审计事件。
- 补充认证审计和 outbox 测试。

### 进行中

- Sprint 1 工程底座的下一阶段：outbox dispatcher 和 Celery 基础队列。

### 阻塞与风险

- 暂无。

### 下一步

- 补充 outbox dispatcher、Celery app 基础配置和 audit 队列投递测试。

### 验证

- 已检查 GitHub CLI 登录状态。
- 已检查目标仓库名 `ChaceQC/enterprise-drive` 当前不存在。
- 已运行 `uv sync --all-extras --dev`。
- 已运行 `uv sync --frozen --all-extras --dev`。
- 已运行 `uv run ruff format --check .`。
- 已运行 `uv run ruff check .`。
- 已运行 `uv run mypy app`。
- 已运行 `uv run pytest`，结果为 10 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认认证、审计和 outbox 迁移可生成 PostgreSQL SQL。
- 已启动 Docker Desktop，并运行 `docker compose up -d postgres redis minio opensearch`。
- 已运行 `uv run alembic upgrade head`，真实 PostgreSQL migration 通过。
- 已运行 `uv run python -m scripts.seed_admin`，管理员 seed 通过。
- 已启动本地 API `uv run uvicorn app.main:app --host 127.0.0.1 --port 18080`。
- 已验证 `/healthz`、`/readyz`、`/api/v1/auth/login`、`/api/v1/auth/me`、`/api/v1/auth/refresh`。
- 验证完成后已关闭本次启动的 API 和 Docker Compose 服务，并确认 `18080`、`15432`、`16379`、`19000`、`19001`、`19200`、`19600` 不再监听。
