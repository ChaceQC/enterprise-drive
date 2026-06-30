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

- 本地账号登录、管理员 seed、BFF + HttpOnly Cookie Session、CSRF 防护。
- 空间、文件树、文件版本、回收站、基础容量账本。
- S3 兼容对象存储上传下载，支持 multipart upload。
- 目录权限、空间角色、拒绝优先、权限缓存和高危动作二次校验。
- 内部分享、外链分享、提取码、过期、次数限制、撤销。
- 预览 Worker、搜索索引 Worker、审计 outbox dispatcher。
- Docker Compose 本地开发环境、Alembic migration、CI 质量门禁。

## 当前状态

当前仓库已完成 Sprint 2 空间和文件树阶段，并开始 Sprint 3 上传下载链路。已建立 `backend` 后端工程、uv 依赖锁定、FastAPI 应用入口、配置加载、结构化日志、`X-Request-ID` 中间件、统一错误响应、健康检查、本地依赖 Compose 和后端 CI。认证基础能力已落地：租户、用户、`auth_sessions` 表，管理员 seed，本地账号登录、服务端 opaque session、HttpOnly Cookie、CSRF 校验、会话轮换和登出。基础审计、outbox 和 Celery audit 队列 dispatcher 已接入。空间和文件树已具备 `spaces`、`nodes`、`file_blobs`、`file_versions` 元数据表，支持创建空间、创建文件夹、按游标列出目录节点、重命名、移动、删除到回收站和恢复。

Sprint 3 已落地上传会话基础：`upload_sessions`、`upload_parts` 迁移，`quota_accounts`、`quota_ledger` 容量账本迁移，MinIO Python SDK 对象存储适配器，`POST /api/v1/uploads/init` 初始化上传，`GET /api/v1/uploads/{session_id}` 查询状态，`POST /api/v1/uploads/{session_id}/parts/{part_no}/presign` 获取分片上传预签名 URL，`POST /api/v1/uploads/{session_id}/complete` 完成 multipart 上传并创建文件节点、blob 和首个版本，`POST /api/v1/uploads/{session_id}/abort` 取消未完成上传，`GET /api/v1/files/{node_id}/download` 生成短期私有对象下载预签名 URL，`DELETE /api/v1/files/{node_id}/purge` 彻底删除回收站节点。初始化时若命中同租户同 hash、同大小的 `file_blobs`，会走秒传分支并创建文件节点和版本，同时增加 blob 引用计数并写入审计与 outbox；若同 hash blob 正在清理，会返回 `BLOB_DELETING` 让客户端稍后重试。multipart complete 在对象存储合并后会服务端计算 `sha256` 并与 `content_hash` 比对，大小和 hash 都匹配后才将新对象归档到 `objects/{tenant_id}/{hash_prefix}/{content_hash}`，再写入 blob、版本和容量流水；hash 不匹配会标记上传失败并写入 `upload.failed` 审计。过期上传清理任务 `upload.expire_sessions` 已接入 Celery `maintenance` 队列，会按租户扫描过期的 `initiated`、`uploading`、`completing` 会话，标记为 `expired`，最佳努力中止 multipart upload、删除 `uploads/...` 临时对象，并写入 `upload.expired` 审计。上传初始化、分片签名和下载预签名已接入 Redis Lua 原子固定窗口基础限流，触发后返回 `RATE_LIMITED`。空间创建会初始化默认容量账户，秒传和 multipart complete 创建文件版本时会原子增加空间容量快照并写入容量流水；删除到回收站不释放容量，彻底删除会删除节点元数据和版本记录、扣减 blob 引用计数，并写入 `file_purged` 负向容量流水。容量校准任务 `quota.reconcile_space_usage` 已接入 `maintenance` 队列，默认按 `limit` 批大小和 cursor 扫完整个租户，支持只读报告和修复模式，会以 PostgreSQL 文件版本表为事实来源校准空间容量快照与账本差异，并在修复时写入系统审计。Blob 垃圾回收任务 `file.cleanup_unreferenced_blobs` 已接入 `maintenance` 队列，会扫描 `file_blobs.ref_count=0` 且无 `file_versions` 引用的 active blob，先标记为 `deleting`，再删除对象存储内容和 blob 元数据，成功或失败均写入系统审计。下载接口会返回下载地址、过期时间、文件名、当前版本、大小和 MIME，并记录成功与拒绝审计。

当前已进入 Sprint 4 权限系统，已新增 `space_members` 基础表，创建空间时会自动写入当前用户的 `owner` 角色成员关系。空间列表、文件树、上传初始化、multipart complete 和下载已通过 `PermissionService` 做空间级成员角色检查：`viewer` 可列表和下载，`editor` 可上传与修改，`owner/admin` 可执行全部空间级动作。空间成员管理 API 已接入，支持 owner/admin 添加、调整和移除成员，权限变更会递增空间权限版本并写入审计。用户维度节点 ACL 基础能力已接入，支持 allow/deny、继承开关和 deny 优先，并已覆盖文件列表、创建文件夹、上传初始化、multipart complete 和下载入口；文件列表响应会通过批量权限评估返回每个子节点的常用动作权限，避免列表页逐项查询。空间成员和节点 ACL 变更都会写入 `permission.changed` outbox event，为后续权限缓存失效和搜索 ACL 重建提供输入。部门/用户组主体、权限缓存消费 worker 和搜索 ACL 更新仍在后续步骤接入。最终对象的 DB 驱动清理已由 `file.cleanup_unreferenced_blobs` 承担；对象存储中没有 DB 元数据的孤儿对象扫描仍作为后续治理任务处理。

本地后端验证：

若本机缺少 `uv`、Python 3.12、Docker、GitHub CLI 或后端依赖包等必要工具，可按命令提示自行安装或补齐；确因权限、网络或平台限制无法安装时，需要记录到 `PROJECT_PROGRESS.md`。

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
