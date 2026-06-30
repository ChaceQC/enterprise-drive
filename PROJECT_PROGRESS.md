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

### 进行中

- Sprint 1 工程底座的下一阶段：数据库基础模型、认证和管理员 seed。

### 阻塞与风险

- `pytest` 存在 FastAPI / Starlette TestClient 上游弃用警告，当前不影响测试通过；后续可关注 httpx2 兼容路径。

### 下一步

- 补充 SQLAlchemy 基础模型、Alembic 初始迁移、本地账号认证、JWT refresh token 轮换和管理员 seed。

### 验证

- 已检查 GitHub CLI 登录状态。
- 已检查目标仓库名 `ChaceQC/enterprise-drive` 当前不存在。
- 已运行 `uv sync --all-extras --dev`。
- 已运行 `uv sync --frozen --all-extras --dev`。
- 已运行 `uv run ruff format --check .`。
- 已运行 `uv run ruff check .`。
- 已运行 `uv run mypy app`。
- 已运行 `uv run pytest`，结果为 4 passed，存在 1 条上游弃用警告。
