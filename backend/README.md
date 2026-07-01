# 后端工程

本目录承载企业网盘后端，使用 Python 3.12+、uv、FastAPI、SQLAlchemy、PostgreSQL、Redis、S3 兼容对象存储、OpenSearch 和 Celery。

## 本地准备

若本机缺少 `uv`、Python 3.12、Docker、GitHub CLI 或后端依赖包等必要工具，可按命令提示自行安装或补齐；确因权限、网络或平台限制无法安装时，需记录到项目进度。

```bash
uv python install 3.12
uv sync --all-extras --dev
copy .env.example .env
docker compose up -d postgres redis minio opensearch
uv run alembic upgrade head
uv run python -m scripts.seed_admin
uv run fastapi dev app/main.py --host 127.0.0.1 --port 18080
uv run celery -A app.infrastructure.queue.celery_app worker -Q audit,permission,search,maintenance -l info
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
- `tenants`、`users`、`auth_sessions` 基础表和 Alembic 初始迁移。
- `departments`、`department_members`、`user_groups`、`user_group_members` 组织基础表和迁移。
- 本地账号登录、BFF + HttpOnly Cookie Session、CSRF 校验和会话轮换。
- 旧 session 复用检测与 session family 吊销。
- `audit_logs`、`outbox_events` 基础表和迁移。
- 登录、会话轮换、登出和 session 复用检测的认证审计事件。
- Celery app 基础配置和 `audit.dispatch_outbox`、`permission.invalidate_cache`、`search.dispatch_outbox` 任务。
- outbox dispatcher，支持按事件类型 claim、成功发送、失败重试和 dead 状态。
- `spaces`、`nodes`、`file_blobs`、`file_versions` 基础表和迁移。
- 空间创建时同步创建空间根目录节点。
- `space_members` 基础表和迁移，空间创建时同步写入创建者的 `owner` 角色成员关系。
- 空间成员管理 API，支持 owner/admin 添加、查看、调整和移除成员，并保护最后一个 owner。
- `acl_entries` 基础表和迁移，支持 `user`、`department`、`group` 三类节点 ACL 主体、allow/deny、继承开关和 deny 优先。
- 文件夹创建、目录子节点列表和签名 cursor pagination。
- 文件树节点重命名、移动、删除到回收站、恢复和彻底删除。
- 空间创建、文件夹创建、重命名、移动、删除、恢复和彻底删除审计事件。
- `upload_sessions`、`upload_parts` 基础表和迁移。
- `quota_accounts`、`quota_ledger` 基础表和迁移。
- 空间创建时同步初始化默认空间容量账户。
- MinIO Python SDK 对象存储适配器，业务层通过 `StorageAdapter` 协议隔离具体 SDK。
- 上传初始化、上传状态查询、分片预签名 URL、multipart complete 和 abort 接口。
- 秒传分支：命中同租户同 hash、同大小 blob 时直接创建文件节点和版本，并增加 blob 引用计数。
- multipart complete 成功合并后服务端校验 `sha256`，通过后将新对象归档到 `objects/{tenant_id}/{hash_prefix}/{content_hash}`，再写入 `file_blobs`、`nodes`、`file_versions`、`upload_parts` 和上传会话完成结果。
- 秒传和 multipart complete 创建文件版本时原子增加空间容量快照，并写入 `quota_ledger` 容量流水。
- 删除到回收站保留空间容量占用；彻底删除回收站节点时释放对应文件版本容量，并写入 `file_purged` 负向容量流水。
- 上传初始化、秒传、complete、abort 和 hash 不匹配等失败审计事件。
- `upload.expire_sessions` 维护任务，按租户清理过期上传会话并写入 `upload.expired` 审计事件。
- Redis Lua 原子固定窗口基础限流，覆盖上传初始化、分片签名、下载预签名和搜索查询。
- `quota.reconcile_space_usage` 维护任务，支持空间容量只读报告和修复模式。
- `file.cleanup_unreferenced_blobs` 维护任务，清理 ref_count 为 0 且无版本引用的最终对象和 blob 元数据。
- `permission.invalidate_cache` 任务，消费 `permission.changed` outbox event 并失效 Redis 权限缓存 key；审计 dispatcher 只消费 `audit.*`，避免抢占权限事件。
- 搜索 ACL token builder、`search.acl_rebuild_requested` outbox event、`search.index_requested` 文件索引事件和 `GET /api/v1/search` 查询接口；`search.dispatch_outbox` 会从 PostgreSQL 重新加载文件、版本、blob、空间成员和节点 ACL 事实后写入 OpenSearch，不再活跃或已彻底删除的文件会删除索引文档，并在 ACL 变更后按 space 或 node 子树保守重建索引 token；查询接口使用 `acl_tokens` allow 过滤、`deny_acl_tokens` 排除过滤和 `read_meta` 二次权限校验。
- 文件下载预签名 URL 接口，按当前文件版本生成短期私有对象下载地址。
- 下载成功和拒绝均写入 `file.downloaded` 审计事件与 outbox event。
- 管理员 seed 脚本。

## 认证接口

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/session/rotate`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`

登录成功后，后端写入 `drive_session` HttpOnly Cookie 和可由前端读取的 `drive_csrf` Cookie；所有 `POST`、`PUT`、`PATCH`、`DELETE` 请求都需要把 `drive_csrf` 的值通过 `X-CSRF-Token` 请求头回传。接口不返回 JWT，也不支持 `Authorization: Bearer` 或旧 `/auth/refresh` 兼容路径。

默认管理员由 `.env` 中的 `DRIVE_ADMIN_*` 配置控制。首次本地启动后运行 `uv run python -m scripts.seed_admin` 创建管理员，并在首次登录后尽快修改默认密码。

## 空间和文件树接口

- `POST /api/v1/spaces`
- `GET /api/v1/spaces`
- `GET /api/v1/spaces/{space_id}/members`
- `POST /api/v1/spaces/{space_id}/members`
- `PATCH /api/v1/spaces/{space_id}/members/{user_id}`
- `DELETE /api/v1/spaces/{space_id}/members/{user_id}`
- `GET /api/v1/files/{node_id}/acl`
- `POST /api/v1/files/{node_id}/acl`
- `PATCH /api/v1/files/{node_id}/acl/{entry_id}`
- `DELETE /api/v1/files/{node_id}/acl/{entry_id}`
- `POST /api/v1/files/folders`
- `GET /api/v1/files?space_id=...&parent_id=...`
- `PATCH /api/v1/files/{node_id}`
- `POST /api/v1/files/{node_id}/move`
- `DELETE /api/v1/files/{node_id}`
- `DELETE /api/v1/files/{node_id}/purge`
- `POST /api/v1/files/{node_id}/restore`
- `GET /api/v1/search?q=...&limit=...`

当前空间和文件树接口已使用 `PermissionService` 的空间级成员角色和节点 ACL 检查：空间列表按 `space_members` 成员关系返回；成员管理需要 `manage`/`grant`，文件列表需要 `list`，创建文件夹和上传需要 `upload`，重命名和移动需要 `update`，删除和彻底删除需要 `delete`，恢复需要 `restore`。节点 ACL 创建请求使用 `subject_type` 和 `subject_id`，`subject_type` 支持 `user`、`department`、`group`；权限判断会通过 org 模块展开当前用户所属活跃部门和用户组，ACL 显式 deny 仍优先于 allow 和空间角色。文件列表会复用已校验的父路径，为当前页子节点批量评估 `list`、`read_meta`、`preview`、`download`、`upload`、`update`、`delete`、`restore`、`share`、`grant`、`manage` 常用动作，并在每个节点的 `permissions` 字段返回结果；高危操作仍在对应接口二次调用权限引擎确认。成员变更会递增 `spaces.permission_version` 并写入 `permission.space_member.*` 审计事件；节点 ACL 变更会递增 `nodes.permission_version` 并写入 `permission.node_acl.*` 审计事件；两类权限变更都会写入 `permission.changed` outbox event，payload 包含 scope、resource_id、permission_version、reason、主体信息和必要时的 affected_user_id。`permission.invalidate_cache` 会消费该事件并删除匹配的 Redis 权限缓存 key；部门/用户组 ACL 变更当前保守失效租户内节点权限缓存。缓存只用于加速，不作为权限事实来源。权限变更还会写入独立的 `search.acl_rebuild_requested` outbox event，由 `search.dispatch_outbox` 按 space 或 node 子树保守重建 OpenSearch 索引 token；文件重命名、移动、删除、恢复和彻底删除会写入 `search.index_requested`，由搜索 worker 重新加载 PostgreSQL 事实后更新或删除文件索引。搜索查询接口会先根据当前用户的空间成员角色、用户主体、部门主体和用户组主体构建查询 token，并在 OpenSearch 查询层同时加入租户、未删除、`acl_tokens` allow 和 `deny_acl_tokens` 排除过滤；返回前再按 PostgreSQL 节点路径调用 `PermissionService.can_access_node(..., action=read_meta)` 二次校验，避免 ACL 变更后索引尚未刷新时泄露文件名和元数据。搜索查询已接入 `search.query` 基础限流，按 `tenant + user + search + IP` 维度计数；触发限流时返回 HTTP 429 和 `RATE_LIMITED`。

文件夹名称会进行 Unicode NFC 归一化并去除首尾空白，禁止 `/`、`\`、NUL、控制字符和路径穿越片段。同一目录下未删除节点的名称由数据库唯一索引兜底，根目录由 `tenant_id + space_id` 唯一索引兜底。

根目录不允许重命名、移动、删除或彻底删除。删除到回收站会同步标记当前活跃子树，不释放容量；恢复只恢复同一批删除的子树，避免误恢复更早单独删除的节点。彻底删除只允许作用于已在回收站的节点，会删除该节点下全部已删除后代的节点元数据和文件版本，扣减相关 blob 引用计数，按版本大小合计释放空间容量并写入 `file.purged` 审计。当前目录删除、恢复和彻底删除仍是同步遍历，适合 Sprint 2/3 骨架和普通目录验证；大目录后续需要改为后台任务或引入 `deleted_root_id` 等冗余状态来避免长事务。

## 上传接口

- `POST /api/v1/uploads/init`
- `GET /api/v1/uploads/{session_id}`
- `POST /api/v1/uploads/{session_id}/parts/{part_no}/presign`
- `POST /api/v1/uploads/{session_id}/complete`
- `POST /api/v1/uploads/{session_id}/abort`

上传初始化请求包含 `space_id`、`parent_id`、`file_name`、`size_bytes`、`content_hash`、`hash_algo`、`mime_type` 和 `conflict_policy`。当前 `hash_algo` 仅支持 `sha256`，不支持的算法返回 `UPLOAD_HASH_ALGO_UNSUPPORTED`；当前 `conflict_policy` 仅支持 `fail`，同目录同名返回 `NODE_NAME_EXISTS`。

当 `file_blobs` 已存在同租户、同 hash 算法、同内容 hash、同大小且状态为 `active` 的对象时，初始化接口返回 `mode=instant`，并直接创建文件节点和首个版本。若同 hash blob 正在 `deleting`，接口返回 `BLOB_DELETING`，客户端应稍后重试。当未命中可复用 blob 时，接口创建对象存储 multipart upload 和数据库上传会话，返回 `mode=multipart`、`session_id`、`part_size_bytes`、`total_parts` 和 `expires_at`。

完成 multipart 上传时，客户端提交全部分片的 `part_no`、`etag` 和可选 `size_bytes`。服务端先将会话推进到 `completing`，再调用对象存储合并分片；合并后先检查对象大小，再计算服务端 `sha256` 并与初始化时的 `content_hash` 比对。二者都匹配后，若同租户同 hash、同大小 active blob 已存在，会原子增加引用计数、复用已有 blob 并清理本次 `uploads/...` 临时对象；若不存在，会先复制到 `objects/{tenant_id}/{hash_prefix}/{content_hash}`，再写入 blob、文件节点、版本、分片记录、容量流水和上传完成审计，提交后清理临时对象。若同 hash blob 正在 `deleting`，complete 返回 `BLOB_DELETING` 并标记上传失败，避免复用或新建被垃圾回收占用唯一约束的 blob。hash 不匹配返回 `UPLOAD_HASH_MISMATCH`，上传会话标记为 `failed`，写入 `upload.failed` 审计，不创建文件版本和容量流水。重复调用已完成的 complete 会返回同一完成结果。abort 会将未完成会话标记为 `aborted`，并调用对象存储取消 multipart upload。

过期上传由 Celery 任务 `upload.expire_sessions` 扫描处理，可传入 `tenant_id`、`limit` 和 `request_id`。任务会按租户查找已过期的 `initiated`、`uploading`、`completing` 会话，先标记为 `expired`，再最佳努力调用对象存储取消 multipart upload，并仅删除 `uploads/...` 临时对象，避免误删最终 `objects/...` 内容。对象存储清理失败不会回滚会话终态，会写入 `upload.expired` 审计 metadata 和任务统计中的 `storage_errors`。

上传初始化和分片签名已接入基础限流。上传初始化按 `tenant + user` 维度计数；分片签名按 `tenant + user + upload session` 维度计数。触发限流时返回 HTTP 429，错误码为 `RATE_LIMITED`，错误详情包含 `action`、`limit`、`window_seconds` 和 `retry_after_seconds`。

对象存储和上传策略由以下环境变量控制：

- `DRIVE_S3_ENDPOINT_URL`
- `DRIVE_S3_BUCKET`
- `DRIVE_S3_ACCESS_KEY_ID`
- `DRIVE_S3_SECRET_ACCESS_KEY`
- `DRIVE_S3_REGION`
- `DRIVE_UPLOAD_SESSION_TTL_MINUTES`
- `DRIVE_UPLOAD_PART_SIZE_BYTES`
- `DRIVE_UPLOAD_PRESIGN_EXPIRES_SECONDS`
- `DRIVE_DOWNLOAD_PRESIGN_EXPIRES_SECONDS`
- `DRIVE_DEFAULT_SPACE_QUOTA_BYTES`
- `DRIVE_RATE_LIMIT_ENABLED`
- `DRIVE_UPLOAD_INIT_RATE_LIMIT_COUNT`
- `DRIVE_UPLOAD_INIT_RATE_LIMIT_WINDOW_SECONDS`
- `DRIVE_UPLOAD_PART_PRESIGN_RATE_LIMIT_COUNT`
- `DRIVE_UPLOAD_PART_PRESIGN_RATE_LIMIT_WINDOW_SECONDS`
- `DRIVE_DOWNLOAD_PRESIGN_RATE_LIMIT_COUNT`
- `DRIVE_DOWNLOAD_PRESIGN_RATE_LIMIT_WINDOW_SECONDS`
- `DRIVE_SEARCH_QUERY_RATE_LIMIT_COUNT`
- `DRIVE_SEARCH_QUERY_RATE_LIMIT_WINDOW_SECONDS`

当前上传接口已通过 `PermissionService` 校验父目录节点级 `upload` 权限；初始化和 multipart complete 都会重新检查，避免会话创建后权限收紧仍可完成上传。容量初版按空间维度实现：空间创建时建立默认容量账户，上传初始化会快速检查空间剩余容量，秒传和 multipart complete 创建文件版本时通过原子 update 增加 `quota_accounts.used_bytes`，并写入 `quota_ledger`。删除到回收站不释放容量；彻底删除回收站节点时通过原子 update 扣减 `quota_accounts.used_bytes`，并写入 `reason=file_purged`、`ref_type=node` 的负向容量流水。容量校准任务 `quota.reconcile_space_usage` 使用 PostgreSQL 中的文件版本记录作为事实来源，默认按 `limit` 批大小和 cursor 扫完整个租户，只报告空间容量快照和账本漂移；传入 `repair=true` 时会修复缺失的空间容量账户，已有账户修复前会锁定账户行并重新聚合实际用量和账本合计，再校准 `quota_accounts.used_bytes`，仅按最新差额写入 `reason=quota_reconciled` 账本流水和 `quota.reconciled` 系统审计。彻底删除接口不在用户请求事务中同步删除最终对象；`file.cleanup_unreferenced_blobs` 会扫描 active、`ref_count=0` 且无 `file_versions` 引用的 blob，先标记为 `deleting`，再删除对象存储内容和 DB 元数据。对象存储删除失败会恢复为 `active` 并计入 `storage_errors`；对象存储中没有 DB 元数据的孤儿对象扫描仍需后续治理任务补齐。用户/租户维度配额将在后续步骤补齐。

维护任务可通过 Celery 任务调用：

- `quota.reconcile_space_usage(tenant_id=None, limit=100, repair=False, request_id=None, scan_all=True, max_items=1000)`
- `file.cleanup_unreferenced_blobs(tenant_id=None, limit=100, request_id=None)`
- `permission.invalidate_cache(batch_size=None)`

## 下载接口

- `GET /api/v1/files/{node_id}/download`

下载接口基于 `nodes.current_version_id` 查询当前版本和 blob，返回 `download_url`、`expires_at`、`file_name`、`version_id`、`size_bytes`、`mime_type` 和额外 `headers`。S3/MinIO 适配器会使用 `ResponseContentDisposition` 设置下载文件名，并同时提供 ASCII `filename` 和 UTF-8 `filename*`。

下载预签名已接入基础限流，按 `tenant + user + node + IP` 维度计数。触发限流时返回 HTTP 429，错误码为 `RATE_LIMITED`。

当前下载接口已通过 `PermissionService` 校验节点级 `download` 权限：非空间成员、空间角色不足或节点 ACL deny 均返回统一的 `NODE_NOT_FOUND`，目录节点返回 `NODE_NOT_FILE`，缺失当前版本返回 `FILE_VERSION_NOT_FOUND`。下载成功与拒绝都会写入 `file.downloaded` 审计事件；后续会把搜索 ACL 更新接入同一权限事实。
