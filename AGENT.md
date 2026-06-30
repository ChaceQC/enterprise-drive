# AGENT.md

本文件是本企业网盘项目的开发协作约束。后续进行代码实现、重构、测试、部署配置和文档维护时，都应优先遵守本文件，并以《企业网盘开发者技术计划书.md》作为架构和里程碑基线。

## 1. 基本要求

- 文件读写和终端输入输出统一使用 UTF-8。
- 开发环境默认为 Windows 11。
- 生产部署环境默认为 Linux，应用和依赖服务可使用 Docker / Kubernetes，但 Nginx 默认使用宿主机安装和管理，不放入 Docker Compose 或应用容器。
- 技术基线：Python 3.12+、uv、FastAPI、SQLAlchemy 2.x、PostgreSQL 16+、Redis、S3 兼容对象存储、OpenSearch、Celery。
- 面向用户的界面文案、说明文字、代码注释、README 和项目文档默认使用中文；确需保留英文时，仅限命令、变量名、协议名、第三方产品名、API 字段和行业通用术语。
- 文件路径、目录名、对象存储 key、代码导入路径和真实存储文件名统一使用英文、数字、短横线或下划线；中文文件名只作为展示名、标题、备注等单独字段保存和显示。
- 本项目一期采用模块化单体，不要提前拆成微服务。
- 代码实现必须服务于《企业网盘开发者技术计划书.md》的架构设计、数据模型、接口契约、安全策略和开发里程碑。
- 一期目标是可试点上线的企业网盘后端，不要为了演示效果牺牲权限、审计、上传下载一致性和部署安全。
- 本地开发服务避免使用常见端口；如无项目内配置，API 默认避免使用 `3000`、`5173`、`8000` 等常见开发端口，端口应放入环境变量或配置文件。
- 后端依赖和命令必须通过 uv 管理，禁止直接使用系统 Python 或全局 Python 启动项目。
- 开发、验证或部署过程中发现缺少必要工具或依赖时，应自行安装或补齐，例如 uv、Python 3.12、Docker、GitHub CLI、后端 Python 包和前端包；确因权限、网络或平台限制无法安装时，必须写入 `PROJECT_PROGRESS.md` 并在最终说明中说明原因。
- 运行后端应在 `backend` 目录内使用 `uv run ...`；如果项目尚未创建 `backend` 目录，应先按计划书建立工程结构。
- 端口、域名、数据库连接、Redis、对象存储、OpenSearch、CORS、Trusted Host、上传策略、API 地址等环境相关配置必须放在独立配置文件或环境变量中，不得硬编码在业务代码或启动脚本里。
- 公网部署是默认目标，宿主机 Nginx 负责暴露 `80/443` 并反向代理到内部服务；不能把 PostgreSQL、Redis、OpenSearch、MinIO 管理端、FastAPI 调试端口、私有上传目录直接暴露到公网。
- 不要把临时方案伪装成最终方案；临时实现必须在进度记录中标明原因、影响范围和后续处理。
- 实现过程中必须实时更新受影响文档，至少包括 `README.md`、`PROJECT_PLAN.md`、`PROJECT_PROGRESS.md`、`AGENT.md` 和相关子目录 README；项目计划以《企业网盘开发者技术计划书.md》为准，可在 `PROJECT_PLAN.md` 中维护执行版摘要。

## 2. 版本规则

- 项目版本号采用 `X.Y.Z` 形式。
- Git tag 和发布名称采用 `vX.Y.Z` 形式。
- 非正式版一律使用 `v0.y.z`，例如 `v0.1.0`。
- 正式稳定发布从 `v1.0.0` 开始。
- 破坏性变更提升 `X`，向后兼容的新功能提升 `Y`，修复、文档、重构提升 `Z`。
- 修改数据库结构、API 契约、对象存储 key 规则、权限策略、部署方式或安全策略时，必须同步记录版本影响。
- Worker 任务 payload、OpenAPI 契约和数据库 migration 应至少兼容一个发布窗口，避免滚动发布期间旧版本无法消费或调用。

## 3. Git 与 GitHub

- 项目必须使用 Git 与 GitHub 管理。
- 默认主分支使用 `main`。
- 日常开发默认在 `dev` 分支进行。
- 一个完整功能完成、验证通过并提交推送后，再从 `dev` 合并到 `main`。
- 不要等到累计大量代码后再提交；应按“完成一个可验证小步就 commit 并 push”的节奏推进。
- GitHub remote 默认命名为 `origin`。
- 初始仓库优先创建为私有仓库，确认可公开后再调整可见性。
- 每次完成可验证改动后必须 commit。
- 每次 commit 后必须 push 到 GitHub。
- 提交前必须检查 `git status`，避免混入无关改动。
- 提交前必须先检查本次改动是否影响 `README.md`、`PROJECT_PLAN.md`、`PROJECT_PROGRESS.md`、`AGENT.md`、《企业网盘开发者技术计划书.md》或子目录 README；受影响文档未同步时，不得先提交代码。
- 必须维护 `.gitignore`，禁止提交 `.env`、密钥、证书私钥、依赖目录、构建产物、上传文件、对象存储数据目录、数据库数据目录、OpenSearch 数据目录、日志和备份文件。
- 应提交依赖锁文件，例如后端 `uv.lock`、前端 `package-lock.json` 或其他锁文件。
- commit message 后续统一使用中文说明。
- 可以保留 `docs:`、`feat:`、`fix:`、`refactor:`、`test:`、`chore:` 等英文类型前缀，但冒号后的说明必须为中文。
- 若无法创建 GitHub 仓库、commit 或 push，必须写入 `PROJECT_PROGRESS.md`，并在最终说明中说明原因。

## 4. 项目进度记录

每次实现、重构、测试、部署调整时，都要更新 `PROJECT_PROGRESS.md`。

必须记录：

- 当前日期。
- 已完成事项。
- 正在进行的事项。
- 阻塞问题或风险。
- 下一步计划。
- 涉及的主要文件或模块。
- 已执行的验证方式，例如测试、构建、迁移检查、接口联调、对象存储联调。
- 每完成一个可验证任务后，必须在“下一步”中写清楚紧接着要推进的下一个具体任务；不能只写“继续完善”“后续优化”等模糊表述。

推荐格式：

```markdown
## 2026-06-30

### 已完成

- 完成上传初始化接口。

### 进行中

- 接入 multipart complete 幂等逻辑。

### 阻塞与风险

- 待确认生产对象存储供应商和 bucket 生命周期策略。

### 下一步

- 补充 upload session 状态机测试。

### 验证

- 已运行 `uv run pytest app/modules/upload/tests`。
```

## 5. 架构边界

后端采用模块化单体，推荐结构应贴合计划书：

- `backend/app/main.py`：FastAPI 应用入口。
- `backend/app/api`：全局依赖、错误处理、中间件、版本路由。
- `backend/app/core`：配置、日志、安全、分页、幂等、时间工具。
- `backend/app/db`：SQLAlchemy 基础设施、会话、事务边界。
- `backend/app/modules`：业务模块。
- `backend/app/infrastructure`：对象存储、缓存、队列、搜索、预览等外部适配。
- `backend/app/workers`：Celery 任务。
- `backend/migrations`：Alembic migration。
- `backend/scripts`：seed、重建索引、存储校准等运维脚本。

模块分层必须保持：

```text
router -> service -> domain/policy -> repository -> db/infrastructure
```

- `router` 只负责参数解析、依赖注入、HTTP 状态码和响应模型。
- `service` 负责编排事务、调用权限策略、容量账本、对象存储和领域事件。
- `policy` 只负责规则判断，不直接访问 HTTP request，不直接写数据库。
- `repository` 负责 SQL 查询和数据持久化，不包含业务流程。
- `infrastructure` 负责外部系统适配，例如 S3、Redis、OpenSearch、LibreOffice、FFmpeg。
- 模块之间通过 service 接口调用，禁止跨模块直接访问对方 repository。
- 领域事件统一走 outbox 或任务队列，避免业务代码到处直接投递消息。

禁止事项：

- 禁止在 router 中写复杂 SQL。
- 禁止在 repository 中读取当前登录用户。
- 禁止跨模块直接 import 对方 repository。
- 禁止把 Redis 缓存当作权限、容量、上传状态或审计的唯一事实来源。
- 禁止在数据库事务里执行长时间对象存储上传、文档转码、文本抽取或外部网络调用。

## 6. 模块交付清单

每个模块必须交付代码、迁移、测试和文档，不允许只交付接口空壳。

- `auth`：用户登录、密码哈希、JWT、refresh token 轮换、管理员 seed。
- `org`：用户、部门、用户组、成员关系。
- `space`：空间、空间成员、空间角色、空间配额。
- `file`：node、file_blob、file_version、文件夹、移动、重命名、回收站、版本。
- `upload`：upload_session、upload_part、秒传、分片上传、断点续传、幂等 complete、abort。
- `permission`：ACL、空间角色、继承、拒绝优先、权限缓存、批量权限评估。
- `share`：内部分享、外链分享、提取码、过期、次数限制、撤销。
- `preview`：预览任务、转码适配、派生物写入。
- `search`：索引构建、权限过滤、索引重建、删除同步。
- `audit`：audit_log、outbox、dispatcher、失败重试。
- `quota`：quota_account、quota_ledger、并发扣减、回滚、校准任务。
- `admin`：管理接口、审计查询、统计、分页、筛选、导出。

## 7. 命名与代码风格

- 数据库模型使用单数类名、复数表名，例如 `Node` -> `nodes`。
- Pydantic schema 按用途后缀，例如 `FileListResponse`、`CreateFolderRequest`、`UploadInitResponse`。
- Service 方法使用业务动词，例如 `create_folder`、`init_upload`、`complete_upload`、`grant_permission`。
- Repository 方法使用数据语义，例如 `get_by_id_for_update`、`list_children`、`insert_version`。
- 权限动作使用固定字符串枚举，不在代码里散落魔法字符串。
- 审计 action 使用点分命名，例如 `file.upload.completed`、`share.external.accessed`。
- 所有返回时间使用 ISO 8601 UTC。
- 用户可见错误不泄露内部对象存储 key、SQL 错误、栈信息和文件真实存在性。

## 8. uv 与依赖管理

常用命令以计划书为准：

```bash
uv python install 3.12
uv sync --all-extras --dev
uv run fastapi dev app/main.py
uv run uvicorn app.main:app --host 0.0.0.0 --port ${APP_PORT}
uv run celery -A app.infrastructure.queue.celery_app worker -Q preview,search,audit -l info
uv run alembic upgrade head
uv run pytest
uv run ruff check .
uv run ruff format .
uv run mypy app
```

- CI 必须使用 `uv sync --frozen --all-extras --dev`。
- 修改 `pyproject.toml` 时必须同步更新并提交 `uv.lock`。
- 新增依赖前先确认是否已有标准库、项目工具或现有依赖可满足。
- 生产镜像构建必须固定 `uv.lock`，不能在构建时漂移依赖版本。
- 如果本机无法完成 Linux 或 Docker 验证，必须在 `PROJECT_PROGRESS.md` 和最终说明中写明验证边界。

## 9. 数据库与迁移

- 所有核心业务表必须保留 `tenant_id`，即使一期是单企业部署。
- 所有多租户表查询必须带 `tenant_id` 条件，禁止跨租户扫描。
- 文件树 `nodes` 必须有同目录唯一索引，保证并发创建同名文件时由数据库兜底。
- `audit_logs` 建议按月分区，生产必须提前创建未来 3 到 6 个月分区。
- 大表 migration 禁止一次性加非空列并填充默认值，应分三步：加 nullable 列、后台回填、加 not null 约束。
- 删除字段必须至少跨两个版本：先停止写入和读取，再删除字段。
- JSONB 字段只能放低频扩展属性，高频筛选字段必须列化并建索引。
- Alembic migration 必须可重复执行到最新版本，并纳入测试或 CI 检查。
- 修改表结构、索引、约束或迁移策略时，必须同步更新计划、进度和相关 README。

## 10. 对象存储与文件内容

- 原始文件对象 key 与文件名、目录名无关，必须按内容或稳定 ID 组织。
- 推荐 key 规则：
  - `objects/{tenant_id}/{hash_prefix}/{content_hash}`
  - `uploads/{tenant_id}/{upload_session_id}/{part_no}`
  - `previews/{tenant_id}/{file_id}/{version_id}/preview.pdf`
  - `thumbnails/{tenant_id}/{file_id}/{version_id}/{size}.webp`
  - `exports/{tenant_id}/{export_id}/audit.csv`
- 对象存储 bucket 必须私有，禁止公共读。
- 临时上传对象必须设置生命周期，避免失败上传长期占用容量。
- 文件名来自元数据 `node.name`，不能来自对象存储 key。
- S3 multipart ETag 不是文件 MD5，不能把它当内容完整性哈希。
- 对象存储适配必须通过 `StorageAdapter` 或等价协议隔离，业务模块不得直接绑定具体 SDK。
- boto3 是同步 SDK；在 async endpoint 中不得直接阻塞 event loop，应使用线程池包装或评估异步 SDK。

## 11. 上传下载规则

- 上传链路必须支持初始化、查询状态、分片签名、完成、取消、过期清理。
- `complete_upload` 必须幂等；同一 upload session 重复 complete 只能创建一个文件版本。
- 上传状态机终态包括 `completed`、`aborted`、`expired`，终态不能再上传分片。
- `completing` 状态重复调用 complete，应返回当前处理状态或已有结果，不能重复创建版本。
- 对象存储 multipart upload 不应放在数据库事务内部长时间执行。
- 容量扣减以最终创建版本为准，不以临时分片对象为准；临时容量可单独限制。
- 完成上传后必须写入 blob、version、node、quota ledger、audit log 和 outbox event。
- 初始化上传时检查文件名、扩展名、大小、租户策略、权限和容量。
- 完成后以服务端嗅探 MIME 为准，客户端 MIME 只作参考。
- 文件 hash 不匹配时标记上传失败并写审计，不创建文件版本。
- 同一用户并发上传会话数必须限流。
- 下载默认可使用短期预签名 URL，高密级文件和外链下载可切换后端代理。
- 大文件下载必须支持 HTTP Range。
- 下载前必须检查文件状态、权限、策略、分享状态和次数限制。
- 权限拒绝也要写审计日志，但不要在错误信息里泄露文件是否存在。

## 12. 权限系统

- 权限判断必须服务端可信，前端按钮状态只能改善体验，不能作为安全依据。
- 权限来源包括系统角色、空间角色、目录 ACL、继承权限、文件策略和上下文策略。
- 权限冲突原则：显式 deny 优先于 allow；文件密级和安全策略优先于普通角色授权。
- 超级管理员操作也必须审计，不能绕过关键安全策略。
- 权限动作必须使用固定枚举：`list`、`preview`、`read_meta`、`download`、`upload`、`update`、`delete`、`restore`、`share`、`grant`、`manage`。
- 文件列表接口使用批量权限评估，避免 N+1 查询。
- 下载、删除、分享、授权、管理等高危动作必须单独调用权限引擎确认。
- 权限缓存 key 必须包含租户、用户、节点、动作和权限版本，权限变更后必须失效。
- Redis 权限缓存只是加速，不是事实来源。
- 按 ID 查询文件的接口应统一返回“文件不存在或无权访问”，不要区分 404 和 403 泄露存在性。
- 搜索结果必须二次权限校验，尤其是权限刚变更但索引未更新时。
- 外链访问不能复用内部用户权限逻辑，必须使用 external subject。

## 13. 审计、Outbox 与异步任务

- 所有关键操作必须审计，包括登录、刷新令牌、上传、下载、删除、恢复、分享、授权、权限拒绝、管理操作。
- 审计日志必须包含 tenant_id、actor、action、resource、result、request_id、ip、user_agent、created_at 等关键字段。
- 审计日志不得输出密码、Token、Cookie、数据库连接串、对象存储签名 URL、提取码明文和密钥。
- 业务事务内必须插入 outbox event，再由 dispatcher 投递到 Celery、日志平台或搜索任务。
- 不能出现“数据库写成功但消息没发出去”导致搜索、预览、审计永远缺失的情况。
- Celery 队列按职责拆分：`audit`、`permission`、`preview`、`search`、`maintenance`。
- 任务参数只传 ID，不传大对象内容。
- 任务执行前必须从数据库重新加载最新状态。
- 任务必须幂等，重复执行不会产生重复副作用。
- 失败使用指数退避，超过最大重试进入 dead-letter 状态。
- 任务日志必须包含 task_id、tenant_id、resource_id、request_id。

## 14. 搜索与预览

- 搜索索引以 PostgreSQL 为事实来源，OpenSearch 只保存可重建索引。
- 搜索不能先返回所有结果再在应用层过滤，必须在查询层加入 tenant 和权限过滤。
- 索引中的 `acl_tokens` 变更必须由权限变更事件触发重建。
- 应用层仍需对搜索结果做二次权限校验。
- 文件上传完成、删除、恢复、权限变更后必须通过 outbox 触发索引同步。
- 预览和转码必须放在 Worker 中执行，不能阻塞 API 请求。
- 压缩包预览必须限制展开数量、总大小、递归深度和路径，避免资源耗尽和路径穿越。
- Office、图片、音视频等预览产物必须写入私有对象存储，并经过权限控制访问。

## 15. API 契约

- API 前缀统一为 `/api/v1`。
- 列表接口统一使用 cursor pagination，不使用深 offset。
- cursor 必须是不透明字符串，并签名防篡改。
- 创建、完成上传、批量操作支持 `Idempotency-Key`。
- 错误响应统一包含 `code`、`message`、`request_id`、`details`。
- 错误码和枚举值变更必须同步更新文档、OpenAPI、前端类型和契约测试。
- 批量接口应返回每个对象的结果，不应一个失败导致全部无响应。
- 前后端接口变更必须通过契约测试，CI 应比较 OpenAPI diff，发现 breaking change 时阻断合并。

## 16. 认证与安全

- 一期支持本地账号，预留 OIDC / LDAP。
- 密码哈希使用 Argon2id。
- access token 短期有效，refresh token 长期有效且服务端保存 token family 和轮换状态。
- 每次刷新都签发新 refresh token，旧 token 立即作废。
- 检测到旧 refresh token 被重复使用，必须吊销整个 token family。
- 管理员重置密码后必须强制用户下次登录修改。
- 文件名最大 255 字符，禁止 `/`、`\`、控制字符、NUL、路径穿越片段。
- Unicode 文件名必须 normalize，避免肉眼相同但二进制不同导致绕过重名检查。
- 所有 SQL 使用 SQLAlchemy 参数化，禁止字符串拼接 SQL。
- 外部 URL 预览或远程拉取默认不做，避免 SSRF。
- 登录失败、初始化上传、分片签名、下载、外链访问和搜索必须有限流策略。
- CORS、Trusted Host、Cookie、CSRF、限流必须按公网部署设计。
- 生产环境只允许宿主机 Nginx 暴露 `80/443`；Nginx 不放入 Docker，应用容器、数据库、Redis、OpenSearch、对象存储等服务只监听内网或宿主机本地反代端口。

## 17. 容量与配额

- 不要只在 `spaces.used_bytes` 或类似快照字段上直接加减。
- 容量必须通过 `quota_ledger` 保留可审计流水。
- `quota_accounts.used_bytes` 是当前快照，`quota_ledger` 是追溯依据。
- 高并发上传完成时，使用行锁或原子 update 防止超配额。
- 删除到回收站是否释放容量由策略决定；彻底删除后必须释放容量或等待 blob 引用计数清理。
- 秒传、覆盖上传、版本回滚、彻底删除、blob 引用计数变化都必须考虑容量影响。

## 18. 单文件体量

代码文件应保持克制：

- 普通源码文件建议不超过 300 行。
- 复杂 service、policy、repository 文件超过 400 行时必须评估拆分。
- 单个函数建议不超过 60 行。
- 一个文件只承担一个主要职责。
- 同类逻辑复制 3 次以上，应抽取公共函数、类、hook、组件或策略。

允许较长的文件：

- 数据库迁移文件。
- 生成文件。
- 文档和计划书。
- 明确需要集中声明的数据表或配置清单。

## 19. 重构规则

出现以下情况时，优先考虑重构：

- 文件职责混乱，包含路由、业务、数据库、外部 SDK、安全逻辑等多类职责。
- 新增功能需要修改多个无关模块。
- 单元测试难写，需要大量 mock 内部实现。
- 复制粘贴明显增加。
- 权限、容量、审计、限流、幂等、文件访问等横切逻辑散落。

重构要求：

- 先记录重构原因和影响范围。
- 尽量保持外部行为不变。
- 重构后补充或保留测试。
- 更新 `PROJECT_PROGRESS.md`。

## 20. 测试与验证

实现完成后，根据变更范围执行验证：

- 后端格式：`uv run ruff format --check .`。
- 后端 lint：`uv run ruff check .`。
- 后端类型：`uv run mypy app`。
- 后端测试：`uv run pytest` 或相关模块测试。
- 数据库：检查 Alembic migration 可执行，必要时从空库升级到 head。
- 集成：使用 testcontainers 或 Docker Compose 拉起 PostgreSQL、Redis、MinIO、OpenSearch。
- 上传下载：验证秒传、multipart、断点续传、幂等 complete、Range 下载。
- 权限：验证继承、拒绝优先、空间角色、目录 ACL、越权下载失败。
- 审计：验证成功和失败操作都写入 audit log，outbox 投递失败可重试。
- 部署：检查 Dockerfile、Docker Compose、Kubernetes、宿主机 Nginx 反向代理配置和环境变量示例；不得生成把 Nginx 放入 Docker Compose 的默认部署方案。
- 安全：检查公网端口、后台入口、文件访问路径、对象存储 bucket、敏感日志。

如果某项验证无法执行，必须在最终说明和 `PROJECT_PROGRESS.md` 中记录原因。

进行浏览器联调、接口联调或端到端验证时，如果启动了本项目的 API、Worker、前端或预览服务，验证完成后必须关闭本次启动的服务，并确认相关端口不再由本项目进程监听。

## 21. CI/CD 与部署

CI 基线：

```text
checkout
  -> setup uv
  -> uv sync --frozen --all-extras --dev
  -> ruff check
  -> ruff format --check
  -> mypy app
  -> pytest
  -> build docker image
  -> dependency vulnerability scan
```

Dockerfile 要求：

- 使用多阶段构建。
- 构建阶段运行 `uv sync --frozen`。
- 运行镜像使用非 root 用户。
- 不把 `.env`、测试文件、缓存目录复制到生产镜像。
- 健康检查使用 `/healthz` 和 `/readyz`。

宿主机 Nginx 要求：

- 生产默认使用宿主机安装的 Nginx 做 TLS 终止和反向代理。
- Docker Compose 不包含 Nginx 服务；Compose 只编排 API、Worker 和依赖服务。
- Nginx 配置文件、站点启用方式、证书路径和反代 upstream 应在部署文档中说明。
- API 容器端口只绑定到宿主机本地地址或内网地址，禁止直接公网暴露。
- WebSocket、Range 下载、上传大小限制、超时、真实客户端 IP 头和安全响应头必须在宿主机 Nginx 中配置。

Kubernetes 至少拆分：

- `api-deployment`：FastAPI。
- `worker-preview-deployment`：重 CPU / 内存转码任务。
- `worker-search-deployment`：文本抽取和索引。
- `worker-audit-deployment`：审计投递。
- `cronjob-maintenance`：过期外链、回收站、容量校准。
- `migration-job`：发布时执行 Alembic migration。

发布顺序：

- 合并代码前运行 ruff、mypy、pytest、OpenAPI diff。
- 构建镜像时固定 `uv.lock`，生成 SBOM，可选漏洞扫描。
- 执行 migration job，只允许向前兼容 migration。
- 部署 API，readiness 通过后接流量。
- 部署 Worker，按队列逐类发布，避免任务中断扩大。
- 观察错误率、延迟、队列积压、数据库慢查询和对象存储异常。
- 发布完成后标记版本、归档 OpenAPI、记录 migration 版本。

回滚原则：

- 应用可快速回滚镜像。
- 数据库 migration 原则上只做向前兼容，避免依赖回滚 DDL。
- 如果必须执行破坏性迁移，必须先做影子字段和双写验证。
- Worker 任务 payload 必须兼容至少一个旧版本。

## 22. 文档同步

以下变更必须同步更新文档：

- 项目总览、启动方式、目录结构和当前阶段变化。
- 架构边界变化。
- 数据表、索引、迁移和分区策略变化。
- API 契约、错误码、枚举值和 OpenAPI 变化。
- 上传下载、对象存储 key、预览、搜索策略变化。
- 权限、认证、分享、安全策略变化。
- 容量账本和配额策略变化。
- 部署方式、CI/CD、环境变量和运维脚本变化。
- 影响开发流程的规范变化。

## 23. Definition of Done

一个功能完成必须满足：

- 代码符合模块分层和命名约定。
- 数据库迁移、模型和 repository 行为一致。
- API 契约、错误码和文档已同步。
- 权限、审计、容量、幂等和安全边界已按功能影响范围处理。
- 相关单元测试、集成测试或手工验证已完成。
- `PROJECT_PROGRESS.md` 已记录完成事项、风险、下一步和验证方式。
- 可运行、可回滚、可排查；没有把临时方案伪装成最终方案。
