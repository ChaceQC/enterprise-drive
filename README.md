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

当前已进入 Sprint 4 权限系统，已新增 `space_members` 基础表，创建空间时会自动写入当前用户的 `owner` 角色成员关系。空间列表、文件树、上传初始化、multipart complete 和下载已通过 `PermissionService` 做空间级成员角色检查：`viewer` 可列表和下载，`editor` 可上传与修改，`owner/admin` 可执行全部空间级动作。空间成员管理 API 已接入，支持 owner/admin 添加、调整和移除成员，权限变更会递增空间权限版本并写入审计。节点 ACL 已支持 `user`、`department`、`group` 三类主体，基于 org 事实表展开用户部门和用户组，支持 allow/deny、继承开关和 deny 优先，并已覆盖文件列表、创建文件夹、上传初始化、multipart complete 和下载入口；文件列表响应会通过批量权限评估返回每个子节点的常用动作权限，避免列表页逐项查询。空间成员和节点 ACL 变更都会写入 `permission.changed` outbox event，`permission.invalidate_cache` 会消费该事件并删除匹配的 Redis 权限缓存 key；部门/用户组 ACL 变更当前保守失效租户内节点权限缓存。搜索 ACL 已新增 token builder 和 `search.acl_rebuild_requested` outbox event；秒传、multipart complete、重命名、移动、删除、恢复和彻底删除会写入 `search.index_requested`，上传完成还会写入 `search.extract_requested`。`search.dispatch_outbox` 会从 PostgreSQL 重新构建文件索引文档写入 OpenSearch，不再活跃或已彻底删除的文件会删除索引文档，并在 ACL 变更后按 space 或 node 子树保守重建索引 token；文本抽取入口当前只处理安全的小型 UTF-8 文本类文件，把正文写入 `file_versions.search_text` 并刷新索引 `content` 字段，解码失败标记为 `failed`，对象存储读取失败交给 outbox 重试。预览基础链路已接入 `preview.render_requested` outbox event 和 `preview` 队列，当前使用成熟开源库 Pillow 将图片生成私有 WebP 预览产物，通过 Poppler `pdftoppm` 将 PDF 首页渲染为图片后复用同一 WebP 产物链路，并通过 LibreOffice headless 将 Office 文档先转换为 PDF 再复用 PDF/图片链路；`preview.dispatch_outbox` 已配置 Celery 软/硬超时、速率限制和结构化失败日志；`GET /api/v1/files/{node_id}/preview` 会通过 `preview` 权限校验后返回短期私有预览 URL。`GET /api/v1/search` 已接入查询层 `acl_tokens` allow 过滤、`deny_acl_tokens` 排除过滤、签名 cursor 分页、HTML 编码的 `<mark>` 高亮片段、`search.query` 限流和 `read_meta` 二次权限校验。最终对象的 DB 驱动清理已由 `file.cleanup_unreferenced_blobs` 承担；对象存储中没有 DB 元数据的孤儿对象扫描仍作为后续治理任务处理。

分享模块已建立基础数据模型、迁移、服务层和基础 HTTP API：支持内部分享、外链分享、提取码哈希、过期时间、访问/下载次数上限、撤销状态、分享项、内部接收人和访问日志表。创建分享会逐个校验节点级 `share` 权限，外链只返回一次 256-bit 级随机 `raw_token`，数据库只保存全局唯一 token hash 和提取码 hash；`POST /api/v1/shares`、`GET /api/v1/shares/{share_id}`、`POST /api/v1/shares/{share_id}/revoke` 已接入 Cookie Session、CSRF、创建者边界、审计与 outbox。`POST /api/v1/public/shares/access` 已接入 `tenant_slug`、外链 token、提取码、状态、过期、访问次数校验，以及 IP 总量和 `token + IP` 维度限流，会在带租户边界的查询后原子增加 `view_count` 并写入 `share_access_logs`。`POST /api/v1/public/shares/download` 已接入外链下载：请求体使用 `tenant_slug`、`raw_token`、`node_id` 和可选 `passcode`，校验分享状态、提取码、下载权限、分享项范围、文件当前版本和下载次数限制，通过数据库条件 update 原子增加 `download_count`，返回短期私有对象下载 URL，并写入 `share_access_logs` 和 `share.external.downloaded` 审计；当前外链下载仍采用预签名 URL，Range/后端代理策略后续按高密级或水印场景补齐。

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
