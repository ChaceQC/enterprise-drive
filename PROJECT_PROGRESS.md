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
- 补充 Celery app 基础配置和 `audit.dispatch_outbox` 任务。
- 实现 outbox dispatcher，支持 pending/failed 到期事件领取、发送成功标记、失败指数退避、超过最大重试进入 dead。
- 补充 outbox dispatcher 状态流转测试。
- 补充 `spaces`、`nodes`、`file_blobs`、`file_versions` SQLAlchemy 模型和 Alembic 迁移。
- 为 `nodes` 增加普通同目录同名唯一索引和空间根目录唯一索引，避免 PostgreSQL 中 `parent_id = null` 导致根节点唯一性失效。
- 实现签名 cursor pagination 工具。
- 实现 `/api/v1/spaces` 空间创建与列表接口，创建空间时同步创建根目录节点。
- 实现 `/api/v1/files/folders` 文件夹创建接口和 `/api/v1/files` 目录子节点列表接口。
- 文件夹名称执行 Unicode NFC 归一化，禁止路径分隔符、NUL、控制字符和路径穿越片段。
- 空间创建和文件夹创建写入审计日志与 outbox event。
- 补充空间和文件树 API 测试，覆盖创建空间、重复空间标识、创建文件夹、重复文件夹名、非法文件夹名和非拥有者访问边界。
- 同步更新 README、后端 README、执行计划和完整技术计划书中的空间/文件树 API、索引与当前阶段说明。
- 实现文件树节点重命名、移动、删除到回收站和恢复接口。
- 重命名、移动、删除和恢复均写入审计日志与 outbox event。
- 禁止根目录重命名、移动和删除，禁止目录移动到自身或自身子目录。
- 删除目录时同步标记当前子树进入回收站；恢复目录时仅恢复同一批删除的子树，避免误恢复更早单独删除的节点。
- 将文件树服务拆分为 `audit`、`tree`、`validators` 辅助模块，避免 `FileService` 职责膨胀。
- 将测试公共夹具抽到 `tests/helpers.py`，并拆分空间/基础文件树测试与文件操作测试。
- 补充 S3/MinIO 对象存储适配器，业务层通过 `StorageAdapter` 协议隔离 boto3 SDK，并用 `asyncio.to_thread` 避免阻塞 async endpoint。
- 补充 `upload_sessions`、`upload_parts` SQLAlchemy 模型和 Alembic 迁移。
- 补充上传相关配置：S3 access key、region、上传会话 TTL、分片大小和分片预签名有效期。
- 实现 `/api/v1/uploads/init` 上传初始化接口，未命中秒传时创建 provider multipart upload 和数据库上传会话。
- 实现 `/api/v1/uploads/{session_id}` 上传状态查询接口。
- 实现 `/api/v1/uploads/{session_id}/parts/{part_no}/presign` 分片上传预签名接口，首次签名时将会话推进为 `uploading`。
- 实现秒传分支：命中同租户、同 hash、同大小 blob 时直接创建文件节点和首个版本，更新 `node.current_version_id` 并递增 `file_blobs.ref_count`。
- 上传初始化和秒传均写入审计日志与 outbox event。
- 测试客户端默认覆盖上传存储依赖为 `InMemoryStorageAdapter`，避免单元测试依赖真实对象存储。
- 同步更新 README、后端 README、执行计划和完整技术计划书中的上传接口、环境变量、当前限制和下一步说明。
- 扩展 `StorageAdapter`，补充 multipart complete 能力；S3 适配器在合并后通过 `head_object` 获取对象大小，测试适配器记录 completed/aborted 状态。
- 实现 `/api/v1/uploads/{session_id}/complete`，完成 multipart 上传后记录分片、写入 `file_blobs`、`nodes`、`file_versions`，更新 `upload_sessions.completed_*`，并支持已完成会话幂等返回同一结果。
- 实现 `/api/v1/uploads/{session_id}/abort`，未完成会话可标记为 `aborted` 并取消对象存储 multipart upload，重复 abort 幂等返回。
- complete、abort 和失败分支均写入审计日志与 outbox event。
- 补充上传 complete/abort 测试，覆盖完整上传、幂等 complete、缺片拒绝和取消后的终态限制。

### 进行中

- Sprint 3 下载预签名 URL、容量账本、hash 校验和上传清理任务设计与实现。

### 阻塞与风险

- 当前空间和文件树接口暂以“当前租户 + 空间拥有者”作为访问边界，空间成员、目录 ACL、继承权限和拒绝优先策略尚未接入；该边界已在 README 和后端 README 标为临时实现，后续需要由权限模块替换。
- 当前目录删除和恢复为同步遍历当前子树，适合 Sprint 2 骨架和普通目录验证；大目录后续需要改为后台任务或引入 `deleted_root_id` 等冗余状态，避免长事务。
- `conflict_policy` 当前实现为 fail-only，同名冲突返回 `NODE_NAME_EXISTS`；`keep_both` 和 `replace` 后续按上传/版本策略补充。
- 当前上传接口已完成 init、status、part presign、complete 和 abort；下载预签名 URL、过期会话清理、上传限流和容量账本尚未接入。
- 当前上传权限仍沿用“当前租户 + 空间拥有者”临时边界，后续需要由 Sprint 4 权限模块替换。
- 当前对象存储上传完成后暂以 `upload_sessions.storage_key` 作为 blob 的 `storage_key`；最终 `objects/{tenant_id}/{hash_prefix}/{content_hash}` key 规整、完成后 hash 校验和生命周期清理策略需在后续步骤落地。

### 下一步

- 实现下载预签名 URL：基于 `nodes.current_version_id` 查找 blob，生成短期私有对象下载地址，并写入下载审计；随后补容量账本、服务端 hash 校验、最终对象 key 规整和过期上传清理。

### 验证

- 已检查 GitHub CLI 登录状态。
- 已检查目标仓库名 `ChaceQC/enterprise-drive` 当前不存在。
- 已运行 `uv sync --all-extras --dev`。
- 已运行 `uv sync --frozen --all-extras --dev`。
- 已运行 `uv run ruff format --check .`。
- 已运行 `uv run ruff check .`。
- 已运行 `uv run mypy app`。
- 已运行 `uv run pytest`，结果为 14 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认认证、审计和 outbox 迁移可生成 PostgreSQL SQL。
- 已启动 Docker Desktop，并运行 `docker compose up -d postgres redis minio opensearch`。
- 已运行 `uv run alembic upgrade head`，真实 PostgreSQL migration 通过。
- 已运行 `uv run python -m scripts.seed_admin`，管理员 seed 通过。
- 已启动本地 API `uv run uvicorn app.main:app --host 127.0.0.1 --port 18080`。
- 已验证 `/healthz`、`/readyz`、`/api/v1/auth/login`、`/api/v1/auth/me`、`/api/v1/auth/refresh`。
- 验证完成后已关闭本次启动的 API 和 Docker Compose 服务，并确认 `18080`、`15432`、`16379`、`19000`、`19001`、`19200`、`19600` 不再监听。
- 已运行 `uv run ruff format .`，格式化本次新增 Python 文件。
- 已运行 `uv run ruff check .`。
- 已运行 `uv run mypy app`。
- 已运行 `uv run pytest`，结果为 20 passed。
- 已运行 `uv run pytest tests/test_space_file.py`，结果为 6 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认空间和文件树迁移可生成 PostgreSQL SQL。
- 已启动 Docker Compose 依赖服务 `postgres`、`redis`、`minio`、`opensearch` 并等待健康。
- 已运行 `uv run alembic upgrade head`，真实 PostgreSQL migration 升级到 `20260630_0003` 通过。
- 已运行 `uv run python -m scripts.seed_admin`，管理员 seed 通过。
- 已启动本地 API `uv run uvicorn app.main:app --host 127.0.0.1 --port 18080`。
- 已真实验证 `/api/v1/auth/login`、`POST /api/v1/spaces`、`POST /api/v1/files/folders`、`GET /api/v1/files`。
- 验证完成后已关闭本次启动的 API 和 Docker Compose 服务，并确认 `18080`、`15432`、`16379`、`19000`、`19001`、`19200`、`19600` 不再监听。
- 已运行 `uv run ruff format .`。
- 已运行 `uv run ruff check .`。
- 已运行 `uv run mypy app`。
- 已运行 `uv run pytest tests/test_space_file.py tests/test_file_operations.py`，结果为 12 passed。
- 已运行 `uv run pytest tests/test_upload.py`，结果为 3 passed。
- 已运行 `uv run ruff format .`，格式化上传接口相关文件。
- 已运行 `uv run ruff format --check .`。
- 已运行 `uv run ruff check .`。
- 已运行 `uv run mypy app`。
- 已再次运行 `uv run pytest tests/test_upload.py`，结果为 3 passed。
- 已运行 `uv sync --frozen --all-extras --dev`。
- 已运行 `uv run ruff format --check .`。
- 已运行 `uv run ruff check .`。
- 已运行 `uv run mypy app`。
- 已运行 `uv run pytest`，结果为 26 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认当前迁移可生成 PostgreSQL SQL。
- 已启动 Docker Compose 依赖服务 `postgres`、`redis`、`minio`、`opensearch` 并等待健康。
- 已运行 `uv run alembic upgrade head`，真实 PostgreSQL migration 通过。
- 已运行 `uv run python -m scripts.seed_admin`，管理员 seed 通过。
- 已启动本地 API `uv run uvicorn app.main:app --host 127.0.0.1 --port 18080`。
- 已真实验证 `/api/v1/auth/login`、`POST /api/v1/spaces`、`POST /api/v1/files/folders`、`PATCH /api/v1/files/{node_id}`、`POST /api/v1/files/{node_id}/move`、`DELETE /api/v1/files/{node_id}`、`POST /api/v1/files/{node_id}/restore`、`GET /api/v1/files`。
- 验证完成后已关闭本次启动的 API 和 Docker Compose 服务，并确认 `18080`、`15432`、`16379`、`19000`、`19001`、`19200`、`19600` 不再监听。
- 已运行 `uv sync --frozen --all-extras --dev`。
- 已运行 `uv run ruff format --check .`，结果为 72 files already formatted。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run mypy app`，结果为 no issues found in 62 source files。
- 已运行 `uv run pytest`，结果为 29 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认上传迁移 `20260630_0004` 可生成 PostgreSQL SQL。
- 已确认启动前 `18080`、`15432`、`16379`、`19000`、`19001`、`19200`、`19600` 未监听。
- 已启动 Docker Compose 依赖服务 `postgres`、`redis`、`minio`、`opensearch` 并等待健康。
- 已运行 `uv run alembic upgrade head`，真实 PostgreSQL migration 升级到 `20260630_0004` 通过。
- 已运行 `uv run python -m scripts.seed_admin`，管理员 seed 通过。
- 已启动本地 API `uv run uvicorn app.main:app --host 127.0.0.1 --port 18080`。
- 已真实验证 `/healthz`、`/api/v1/auth/login`、`POST /api/v1/spaces`、`POST /api/v1/uploads/init`、`GET /api/v1/uploads/{session_id}`、`POST /api/v1/uploads/{session_id}/parts/{part_no}/presign`；multipart 初始化返回 2 个分片，分片签名后状态由 `initiated` 变为 `uploading`，MinIO 预签名 URL 包含 upload id。
- 验证完成后已关闭本次启动的 API 和 Docker Compose 服务，并确认 `18080`、`15432`、`16379`、`19000`、`19001`、`19200`、`19600` 不再监听。
- 已运行 `uv run ruff format .`，格式化 lifecycle 和上传测试。
- 已运行 `uv run pytest tests/test_upload.py`，结果为 6 passed。
- 已运行 `uv run ruff format --check .`。
- 已运行 `uv run ruff check .`。
- 已运行 `uv run mypy app`，结果为 no issues found in 63 source files。
- 已运行 `uv sync --frozen --all-extras --dev`。
- 已运行 `uv run ruff format --check .`，结果为 77 files already formatted。
- 已运行 `uv run ruff check .`，结果为 All checks passed。
- 已运行 `uv run mypy app`，结果为 no issues found in 63 source files。
- 已运行 `uv run pytest`，结果为 32 passed。
- 已运行 `uv run alembic upgrade head --sql`，确认当前迁移仍可生成 PostgreSQL SQL。
- 已确认启动前 `18080`、`15432`、`16379`、`19000`、`19001`、`19200`、`19600` 未监听。
- 已启动 Docker Compose 依赖服务 `postgres`、`redis`、`minio`、`opensearch` 并等待健康。
- 已运行 `uv run alembic upgrade head`，真实 PostgreSQL migration 通过。
- 已运行 `uv run python -m scripts.seed_admin`，管理员 seed 通过。
- 已启动本地 API `uv run uvicorn app.main:app --host 127.0.0.1 --port 18080`。
- 初次使用 PowerShell `Invoke-WebRequest` PUT 预签名 URL 时暴露 MinIO 签名兼容问题，已通过 S3 client 显式 `s3v4` 和 path-style 配置修复；随后 PowerShell 对 8MB byte array PUT 出现客户端空引用，改用 Python/httpx 执行真实联调。
- 已使用 Python/httpx 真实验证 `/healthz`、`/api/v1/auth/login`、`POST /api/v1/spaces`、`POST /api/v1/uploads/init`、`POST /api/v1/uploads/{session_id}/parts/{part_no}/presign`、直接 PUT 两个分片到 MinIO 预签名 URL、`POST /api/v1/uploads/{session_id}/complete`、`GET /api/v1/uploads/{session_id}` 和 `POST /api/v1/uploads/{session_id}/abort`；两个分片 PUT 均为 200，complete 后状态为 `completed`，已上传分片为 `[1, 2]`，abort 返回 `aborted`。
- 验证完成后已关闭本次启动的 API 和 Docker Compose 服务，并确认 `18080`、`15432`、`16379`、`19000`、`19001`、`19200`、`19600` 不再监听。
- 已再次运行 `uv run ruff format --check .`，结果为 77 files already formatted。
- 已再次运行 `uv run ruff check .`，结果为 All checks passed。
- 已再次运行 `uv run mypy app`，结果为 no issues found in 63 source files。
- 已再次运行 `uv run pytest`，结果为 32 passed。
- 已再次运行 `uv run alembic upgrade head --sql`，确认当前迁移仍可生成 PostgreSQL SQL。
