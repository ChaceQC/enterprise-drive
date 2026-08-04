# AGENT.md

本文件是本企业网盘项目的开发协作约束。后续进行代码实现、重构、测试、部署配置和文档维护时，都应优先遵守本文件，并以《企业网盘开发者技术计划书.md》作为架构和里程碑基线。

## 1. 基本要求

- 文件读写和终端输入输出统一使用 UTF-8。
- 开发和正式部署宿主机统一以 Windows 11 为基线。
- 正式部署使用 Docker Desktop 的 WSL2 后端和 Linux containers，仓库根目录 `compose.windows.yml` 是唯一正式编排入口；`backend/docker-compose.yml` 仅保留为本地依赖开发清单。
- `deploy/windows/manage.ps1 up` 默认只能使用已经存在的本地镜像，必须带 `--no-build --pull never`；镜像拉取和项目镜像构建要作为独立、显式、可观察的步骤执行，只有用户明确执行 `up -Build` 时才允许构建，禁止把构建、下载、全栈启动和备份恢复测试串成一个黑盒命令。
- 正式部署的 Nginx gateway 运行在 `compose.windows.yml` 中，并且是唯一允许发布宿主端口的服务；默认本机入口由 gateway 发布 API `18080` 和 S3 外部端点 `19000`。公网模式使用 `manage.ps1 -Tls`、ACME HTTP-01 bootstrap、Certbot 证书卷和 TLS Nginx 模板映射 `80/443`；启用前必须配置真实 DNS、受信证书邮箱、HTTPS 外部端点、CORS、Trusted Hosts 和 Secure Cookie，并完成双域名实测。API、Worker、PostgreSQL、Redis、OpenSearch、MinIO API/Console 等内部服务只加入 Compose 网络。
- 可选监控统一使用根 Compose 的 `monitoring` profile；Prometheus、Alertmanager、Grafana 不发布宿主端口，Grafana 只能由 gateway `/grafana/` 代理。正式 `up -Monitoring` 必须拒绝示例 Grafana 密码、仓库内示例 webhook 和 localhost webhook。
- 后端技术基线：Python 3.12+、uv、FastAPI、SQLAlchemy 2.x、PostgreSQL 16+、Redis、S3 兼容对象存储、OpenSearch、Celery。
- 二期桌面客户端技术基线：Rust stable、Cargo workspace、Tauri 2；Windows 11 优先交付，再评估 macOS 和 Linux。同步引擎、传输队列、本地索引、文件系统监听、凭据存储和更新签名校验必须由 Rust 实现，界面层不得成为同步状态的事实来源。
- Web 用户端与管理后台技术基线：TypeScript、React、Vite、npm 锁文件、OpenAPI 生成 client 和 Playwright；默认目录为 `frontend/`。浏览器认证继续使用 BFF Cookie Session 和 CSRF，禁止把 session、JWT、refresh token 或等价 bearer 凭据写入 Web Storage。
- 面向用户的界面文案、说明文字、代码注释、README 和项目文档默认使用中文；确需保留英文时，仅限命令、变量名、协议名、第三方产品名、API 字段和行业通用术语。
- 文件路径、目录名、对象存储 key、代码导入路径和真实存储文件名统一使用英文、数字、短横线或下划线；中文文件名只作为展示名、标题、备注等单独字段保存和显示。
- 本项目一期采用模块化单体，不要提前拆成微服务。
- 代码实现必须服务于《企业网盘开发者技术计划书.md》的架构设计、数据模型、接口契约、安全策略和开发里程碑。
- 一期目标是可试点上线的企业网盘后端，不要为了演示效果牺牲权限、审计、上传下载一致性和部署安全。
- Rust 桌面客户端在一期后端与 Sprint 6 上线治理闭环后进入实现，默认目录为 `desktop/`。桌面端开工前必须先固定设备会话、增量变更游标、删除 tombstone、版本前置条件和冲突处理等后端契约，不得通过高频全量扫描模拟同步协议。
- 项目正式文件传输契约使用 `Drive Transfer Protocol v1`（线协议标识 `DTP/1`）：控制面使用版本化 HTTPS API，数据面使用短期预签名 HTTPS 直达 MinIO/S3，上传复用秒传、multipart、断点状态、幂等 complete/abort 和服务端 SHA-256，下载使用短期签名与 HTTP Range；禁止自研 TCP/UDP、TLS、QUIC、私有加密或可靠传输层。协议规范以 `docs/drive-transfer-protocol-v1.md` 为准。
- Windows 备份、校验和恢复使用的临时 Docker 容器必须统一设置 CPU、memory、memory-swap 和 PID 上限，默认使用低压缩等级并禁止隐式拉取镜像；真实集成测试必须先执行本地镜像 preflight，默认只启动恢复后的数据服务，完整 target 全栈恢复只能通过显式开关执行。
- Windows 备份轮换只处理目录名、manifest ID 和 checksum 均通过的托管备份，必须同时保留配置的最少份数和保留期内备份；周期恢复演练使用随机隔离 Compose project，结束后必须确认 target 容器/卷为零，并把成功或失败 JSON 写到仓库外 restricted ACL 目录。
- Web 页面必须使用生成的 TypeScript API client、服务端权限枚举和统一错误码；前端路由守卫、按钮隐藏、浏览器缓存和本地状态只用于体验，不得复制权限、容量、分享、版本或生命周期业务规则。
- 本地开发服务避免使用常见端口；如无项目内配置，API 默认避免使用 `3000`、`5173`、`8000` 等常见开发端口，端口应放入环境变量或配置文件。
- 后端依赖和命令必须通过 uv 管理，禁止直接使用系统 Python 或全局 Python 启动项目。
- Web 依赖通过项目内 npm 与 `package-lock.json` 管理，桌面端依赖通过 Cargo 与 `Cargo.lock` 管理；禁止依赖未记录的全局前端或 Rust 包。
- 开发、验证或部署过程中发现缺少必要工具或依赖时，应自行安装或补齐，例如 uv、Python 3.12、Docker Desktop、WSL2、Docker Compose v2、GitHub CLI、后端 Python 包和前端包；确因权限、网络或平台限制无法安装时，必须写入 `PROJECT_PROGRESS.md` 并在最终说明中说明原因。
- 功能实现优先复用成熟库、标准工具、开放协议、框架能力或可信开源实现；只有在现有方案不能满足本项目的安全、审计、一致性、性能、授权协议或运维要求时，才允许自研实现。
- 不要默认引入或直接依赖云厂商专有 SDK；对象存储、搜索、消息、身份认证等外部能力应优先使用开放协议、兼容接口、标准客户端或可替换的开源适配器。确需临时使用某个 SDK 时，必须封装在 infrastructure 适配层，并在文档中写明替换计划。
- 引入第三方库或开源代码前必须评估许可证、维护活跃度、安全记录、依赖体量，以及与 Python 3.12/FastAPI 异步生态、Node/React/Vite 工具链或 Rust stable/Tauri/Cargo 生态的兼容性。
- 不要为了“少装依赖”而手写复杂通用能力，例如权限表达式引擎、限流算法、任务调度、文件类型识别、文档解析、预览转码、搜索查询 DSL、加密签名、审计投递、分页协议或对象存储客户端；能用稳定库和开源实现时优先使用。
- 对实验性功能，应在保证鲁棒性、可扩展性和可维护性的前提下保持最小可行实现：接口边界清晰、状态可追踪、失败可回滚或可重试、测试覆盖关键分支，不提前堆砌复杂抽象。
- 如果暂时采用轻量自研实现，必须在 `PROJECT_PROGRESS.md` 或相关 README 中标明原因、适用范围、已知限制和替换为成熟库或开源方案的触发条件。
- 运行后端应在 `backend` 目录内使用 `uv run ...`；如果项目尚未创建 `backend` 目录，应先按计划书建立工程结构。
- 端口、域名、数据库连接、Redis、对象存储、OpenSearch、CORS、Trusted Host、上传策略、API 地址等环境相关配置必须放在独立配置文件或环境变量中，不得硬编码在业务代码或启动脚本里。
- 公网部署是目标形态。当前代码同时保留 gateway 本机 HTTP `18080/19000` 基线，并提供 ACME bootstrap、证书持久卷、TLS server block、HTTP 到 HTTPS 跳转、`80/443` Host 分流和续期热重载命令；真实公网环境仍必须完成受信证书签发、续期任务注册和 API/存储双域名 HTTPS 验收。不能为 PostgreSQL、Redis、OpenSearch、MinIO API/Console、FastAPI 调试端口或私有上传目录配置宿主端口映射。
- 不要把临时方案伪装成最终方案；临时实现必须在进度记录中标明原因、影响范围和后续处理。
- 实现过程中必须实时更新受影响文档，至少包括 `README.md`、`PROJECT_PLAN.md`、`PROJECT_PROGRESS.md`、`AGENT.md`、`docs/deployment-windows-docker.md` 和相关子目录 README；项目计划以《企业网盘开发者技术计划书.md》为准，可在 `PROJECT_PLAN.md` 中维护执行版摘要。

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
- 正式 tag/Release 必须满足对应版本的生产证书、依赖/镜像风险和恢复门禁；当前 MinIO blocker 未解除前不得创建 `v0.4.0` tag 或 GitHub Release。
- 提交前必须检查 `git status`，避免混入无关改动。
- 提交前必须先检查本次改动是否影响 `README.md`、`PROJECT_PLAN.md`、`PROJECT_PROGRESS.md`、`AGENT.md`、《企业网盘开发者技术计划书.md》或子目录 README；受影响文档未同步时，不得先提交代码。
- 必须维护 `.gitignore`，禁止提交 `.env`、密钥、证书私钥、依赖目录、构建产物、上传文件、对象存储数据目录、数据库数据目录、OpenSearch 数据目录、日志和备份文件。
- 应提交依赖锁文件，例如后端 `uv.lock`、前端 `package-lock.json`、桌面端 `Cargo.lock` 或其他锁文件。
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

- `auth`：用户登录、密码哈希、服务端 opaque session、HttpOnly Cookie、CSRF、管理员 seed、登录失败防护、密码与会话管理、OIDC。
- `org`：用户、部门、用户组、成员关系。
- `space`：空间、空间成员、空间角色、空间配额。
- `file`：node、file_blob、file_version、文件夹、移动、重命名、回收站、版本列表/下载/回滚、批量操作。
- `upload`：upload_session、upload_part、秒传、分片上传、断点续传、幂等 complete、abort。
- `permission`：ACL、空间角色、继承、拒绝优先、权限缓存、批量权限评估。
- `share`：内部分享、外链分享、分享给我的、接收人访问、通知、提取码、过期、次数限制、撤销。
- `preview`：预览任务、转码适配、派生物写入、最后访问时间和产物生命周期。
- `search`：索引构建、权限过滤、索引重建、删除同步、OCR 和复杂格式抽取。
- `audit`：audit_log、outbox、dispatcher、失败重试。
- `quota`：quota_account、quota_ledger、并发扣减、回滚、校准任务。
- `admin`：用户、组织、空间、配额、身份源、审计、统计、维护、分页、筛选、导出。
- `frontend`：登录、文件、批量操作、上传、搜索、预览、回收站、版本、分享、通知、账号安全、身份源、生命周期治理和管理后台页面，OpenAPI client、E2E、构建与 gateway 发布。

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
- Windows 11 正式部署改动必须完成 Docker Desktop/WSL2/Linux containers 下的构建、启动、健康检查和停止验证；当前机器若暂时不具备 Docker Desktop 实测条件，必须在 `PROJECT_PROGRESS.md` 和最终说明中写明验证边界，并由最终集成步骤补齐。

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
- 默认对象存储适配使用非云厂商专有的开源 S3 兼容客户端，例如 MinIO Python SDK；业务模块只能依赖 `StorageAdapter` 协议，不得直接 import 具体 SDK。
- 若对象存储 SDK 缺少公开 multipart API，只允许在 `infrastructure` 适配层集中封装必要的客户端细节，并在审计或进度文档中记录适用范围、风险和替换触发条件。

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

- 所有关键操作必须审计，包括登录、会话轮换、登出、上传、下载、删除、恢复、分享、授权、权限拒绝、管理操作。
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
- API 与 Worker 的 JSON 日志必须自动补齐 `service`、`env`、`request_id`、`task_id`、`trace_id` 和 `span_id`；业务日志按上下文继续补 `tenant_id`、`user_id`、`action`、`resource_type`、`resource_id`、`status` 和 `latency_ms`，不得记录 Cookie、Token、预签名 URL、连接串或密钥。
- Prometheus HTTP 标签必须使用路由模板，不得使用原始 URL、文件名、对象 key、用户 ID、租户 ID、request_id、task_id、token 或其他无界值；业务 `reason`、`action`、`status` 标签只能来自固定枚举。
- 正式 API 使用多 Uvicorn worker 时，必须启用 Prometheus multiprocess 目录，并且只允许容器启动入口清理该目录；不得由任一 worker 在运行中清空其他进程指标。
- API 与 Celery Worker 属于不同容器和进程边界：API `/metrics` 负责 API、上传下载、权限、Outbox 和搜索延迟指标，各 Worker 在 Compose 内部 `9100` 暴露自己的 task/preview/维护指标；不得用同进程单测或把 Worker Counter 注册到 API registry 来伪装跨容器聚合。
- OpenTelemetry tracing 默认生成可关联的 W3C trace context；外部导出通过配置选择 `none`、`console` 或 OTLP/HTTP，endpoint、header 和认证信息只能来自环境配置。新增可观测性能力必须至少验证 request_id/trace 日志关联、API 多进程指标和真实 Celery task 指标。

## 14. 搜索与预览

- 搜索索引以 PostgreSQL 为事实来源，OpenSearch 只保存可重建索引。
- 搜索不能先返回所有结果再在应用层过滤，必须在查询层加入 tenant 和权限过滤。
- 索引中的 `acl_tokens` 变更必须由权限变更事件触发重建。
- 应用层仍需对搜索结果做二次权限校验。
- 文件上传完成、删除、恢复、权限变更后必须通过 outbox 触发索引同步。
- 预览和转码必须放在 Worker 中执行，不能阻塞 API 请求。
- OCR、PDF 渲染和 Office 转换必须使用隔离队列、外部命令超时、源文件/页数/像素/输出体量边界和独立临时目录；内容处理 Worker 应定期回收子进程，不能与 API、审计或权限队列混跑。
- 压缩包预览必须限制展开数量、总大小、递归深度和路径，避免资源耗尽和路径穿越。
- Office、图片、音视频等预览产物必须写入私有对象存储，并经过权限控制访问。
- 预览产物必须记录最后访问时间；旧版本和孤儿产物清理必须经过保留期、受控 key 前缀、审计、指标和可重入维护任务保护。

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
- 浏览器端认证采用 BFF + HttpOnly Cookie Session，不向浏览器返回或保存 JWT，不保留 Bearer token 兼容入口。
- 会话令牌使用服务端生成的 opaque random token，仅以哈希形式保存到 `auth_sessions`，原始令牌只写入 `HttpOnly`、`SameSite` Cookie。
- 所有 `POST`、`PUT`、`PATCH`、`DELETE` 等有副作用请求必须校验 `X-CSRF-Token`，CSRF token 可放在非 HttpOnly Cookie 中供前端读取并回传。
- 会话轮换必须签发新的 session token 和 CSRF token，旧 session 立即标记为 replaced；检测到旧 session 被复用时，必须吊销整个 session family。
- 新项目尚未上线，不为旧 JWT、refresh token、`Authorization: Bearer` 或 `/auth/refresh` 路径做兼容保留；相关命名、迁移、文档和测试应直接改为当前会话模型。
- 后续接入第三方身份认证时，优先使用 OIDC/OAuth 2.1 + PKCE 和成熟开源库，在 BFF 层完成 code flow 并继续向浏览器签发本项目服务端 session cookie。
- 管理员重置密码后必须强制用户下次登录修改。
- 文件名最大 255 字符，禁止 `/`、`\`、控制字符、NUL、路径穿越片段。
- Unicode 文件名必须 normalize，避免肉眼相同但二进制不同导致绕过重名检查。
- 所有 SQL 使用 SQLAlchemy 参数化，禁止字符串拼接 SQL。
- 外部 URL 预览或远程拉取默认不做，避免 SSRF。
- 登录失败、初始化上传、分片签名、下载、外链访问和搜索必须有限流策略。
- CORS、Trusted Host、Cookie、CSRF、限流必须按公网部署设计。
- `Settings` 必须在 `DRIVE_ENVIRONMENT=production` 时自行拒绝 debug、关闭限流、示例或过短 secret、无强密码连接 URL、Wildcard Trusted Hosts、带凭据/路径的公共端点，以及非回环 HTTP CORS/S3 端点或未启用 Secure Cookie 的公网配置；该应用内门禁不能只依赖宿主 `manage.ps1`。
- 公网 TLS 管理入口必须拒绝回环或非 IPv4 bind、示例密钥、过短或 `${...}` 间接插值的关键 secret/连接 URL、数据库/Redis URL 与独立密码不一致、Wildcard Trusted Hosts、HTTP API CORS origin、与 API CORS 不一致或非 HTTPS 的 MinIO CORS、带凭据/非 443 的 S3 外部端点和示例 Certbot 邮箱，不能仅因证书配置存在就允许绑定 `0.0.0.0:80/443`。
- 正式环境只允许 Compose 内的 Nginx gateway 发布宿主端口；默认本机为 HTTP `18080/19000`，公网模式通过已实现的 TLS 配置映射 `80/443`，但必须先完成真实 DNS、证书和 Host 分流验证。应用容器、数据库、Redis、OpenSearch、MinIO API/Console 等服务只监听 Compose 内部网络。

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
- 部署：检查 Dockerfile、根 `compose.windows.yml`、Nginx gateway、`.env.windows.example`、`deploy/windows/manage.ps1`、named volumes、自动化备份/校验/隔离恢复、回滚说明和 Windows Docker Desktop 启停流程；必须确认只有 gateway 发布宿主端口。
- 安全：检查公网端口、后台入口、文件访问路径、对象存储 bucket、敏感日志；Nginx gateway 或请求体策略变化还必须执行 `scripts/smoke_gateway_security_docker.py`，以真实原始 HTTP 验证冲突 CL/TE、重复 Content-Length、API body limit 和 storage 流式边界。该 smoke 必须先显式准备镜像，运行阶段使用 `--pull never` 和 CPU/memory/PID 上限。

如果某项验证无法执行，必须在最终说明和 `PROJECT_PROGRESS.md` 中记录原因。

进行浏览器联调、接口联调或端到端验证时，如果启动了本项目的 API、Worker、前端或预览服务，验证完成后必须关闭本次启动的服务，并确认相关端口不再由本项目进程监听。

## 21. CI/CD 与部署

CI 基线：

```text
checkout
  -> changes（按变更路径选择 backend / desktop / installer / windows / MinIO / Rust policy；
              CI workflow/router 或文档变更只保留 changes 轻量校验）
  -> backend：
       setup uv -> uv sync --frozen --all-extras --dev
       -> ruff check -> ruff format --check
       -> bandit（中危/高危代码模式）
       -> pip-audit（已锁定 Python 依赖）
       -> mypy app
       -> PostgreSQL/MinIO -> Alembic -> pytest
       -> Compose/TLS/监控/Nginx 校验 -> Docker smoke/image build
  -> desktop：
       cargo fmt -> cargo test -> cargo clippy --no-deps
       Rust crate 源码/测试只进入 desktop；Tauri UI/配置/签名只进入 installer；
       Tauri Rust 入口同时进入两者；普通库源码不因 push 自动构建安装包
       -> 共享 Cargo registry/git cache
       -> 一次锁定 workspace cargo fetch，后续安装包构建使用 offline
       -> 一次 release 构建 sign-update/verify-update
       -> push 或安装包相关变更时构建 Tauri/NSIS 并验证签名更新工件
  -> windows：
       PowerShell 5.1 parser + TLS/backup-restore/governance guard checks
  -> MinIO：
       immutable image policy -> 一次 SBOM/Grype runner 扫描 Server + Client
  -> Rust policy：
       cargo-deny advisories/licenses/bans/sources
```

- `push` 与 `pull_request` 使用同一并发组，新提交会取消同分支旧运行，避免重复消耗 runner。
- MinIO/Rust 依赖供应链门禁还会在每周定时任务执行；`workflow_dispatch` 运行完整 scope。
- 变更路由器本身位于 `.github/scripts/ci_scope.py`，必须有回归测试；只修改文档、CI workflow/router 或桌面 README 时只保留路由 job，不启动耗时门禁。

Dockerfile 要求：

- 使用多阶段构建。
- 构建阶段运行 `uv sync --frozen` 并固定 `uv.lock`。
- API 与各类 Worker 复用同一后端基础镜像，通过 Compose command 区分进程。
- 运行镜像使用非 root 用户。
- 不把 `.env`、测试文件、缓存目录、运行数据和备份复制到生产镜像。
- API 健康检查使用 `/healthz` 和 `/readyz`；`/readyz` 必须执行真实 PostgreSQL 探针，数据库不可用时返回非 2xx。公网 Trusted Hosts 模式下，容器回环 healthcheck 必须显式携带 API 域名 Host。
- Preview Worker 镜像必须包含 LibreOffice、Poppler 和常用中文字体，并限制 CPU、内存、临时磁盘、并发数和子进程生命周期。

Windows Docker Compose 要求：

- 仓库根目录 `compose.windows.yml` 是 Windows 11 正式部署的唯一编排入口；`backend/docker-compose.yml` 只用于开发机单独拉起依赖。
- 正式编排至少包含 `gateway`、`api`、一次性 `migration`、一次性 `seed`、一次性 `minio-init`、按职责隔离的 Celery Worker、运行 Celery beat 的 `beat` 服务、PostgreSQL、Redis、MinIO 和 OpenSearch。
- `gateway` 是唯一发布宿主端口的服务；默认本机发布 HTTP `18080/19000`，公网模式由 `manage.ps1 -Tls` 切换为 `80/443` 并使用 ACME bootstrap/TLS 模板，bind 必须是 `0.0.0.0` 或其他非回环 IPv4 地址。其他常驻服务禁止配置 `ports`，Certbot 只通过 gateway 共享的 webroot 完成 HTTP-01，服务间通过 Compose 网络和服务名访问。
- `.env.windows.example` 是正式环境变量模板，真实 `.env.windows` 不得提交。数据库、Redis、OpenSearch、Celery broker/result backend 使用内部服务 DNS。
- API 使用可配置的 SQLAlchemy QueuePool；Celery Worker 因同步任务入口会通过 `asyncio.run()` 建立独立事件循环，必须在 Compose 中使用 `DRIVE_DATABASE_POOL_MODE=null`，禁止跨任务事件循环复用 asyncpg 连接池。
- S3 必须区分容器内访问端点和浏览器可访问的外部端点：内部端点用于 API/Worker 访问 `http://minio:9000`；默认外部端点为 gateway 提供的 `http://localhost:19000`，公网 TLS 模式使用 `https://storage.example.com` 等独立 Host。外部端点不得使用 `/s3` 等 base path，也不能把内部服务名返回给浏览器；公网模式的 `MINIO_CORS_ALLOWED_ORIGIN` 必须与 `DRIVE_CORS_ORIGINS` 精确一致且只包含 HTTPS origin，禁止通配符和遗留 origin。
- PostgreSQL、Redis、MinIO 和 OpenSearch 使用 named volumes；备份输出使用明确的 Windows 宿主目录或专用备份卷。Celery beat 当前把可重建 schedule 文件放在容器临时目录，不能把它当作任务事实来源。
- `deploy/windows/manage.ps1` 是宿主机管理入口，提供 `config`、`up`、`down`、`status`、`logs`、`backup`、`backup-verify`、`restore`、备份轮换/计划任务、隔离恢复演练/计划任务、`tls-init`、`tls-renew`、`tls-certificates`、TLS 续期计划任务和 `tls-validate-public`；生命周期命令可用 `-Monitoring` 启用监控 profile。构建使用 `up -Build`，公网操作使用 `-Tls`，删除卷必须显式使用 `down -Volumes`，并同步删除 TLS 续期、备份轮换和恢复演练计划任务。`tls-init` 必须保留已有 gateway 容器，用同一 service 的临时 one-off bootstrap 容器完成签发；签发失败时恢复原 gateway，不得把已有公网入口停在 bootstrap 或 stopped 状态。`tls-renew` 和计划任务注册必须确认 `DRIVE_TLS_CERT_NAME` 对应的 Certbot renewal lineage 存在，手工挂载或自签名证书不得伪装成可自动续期证书。`tls-validate-public` 必须拒绝非公网 DNS 结果，验证 HTTP `308`、HTTPS readiness、系统信任链和证书剩余天数，并保存记录。
- `backup` 的输出根目录必须是仓库外的绝对专用目录，不得是卷根、仓库目录或仓库祖先；既有非空目录必须已经使用本项目 restricted ACL，脚本不得直接重写任意宽范围目录 ACL。正式备份默认要求 `Cert:\CurrentUser\My` 中的 Windows CMS 文档加密证书。脚本从 Compose JSON 读取真实 project、network、service image 和 physical volume name，记录 15 个无 profile 默认服务的实际容器 image ID，静默 gateway、API、beat、Worker 及相关依赖写入面，使用 PostgreSQL custom-format `pg_dump`，并归档停止状态的 MinIO、Redis、OpenSearch 和 TLS 证书卷；失败后必须恢复 source project 原运行、退出与健康状态，通过校验的 `.partial-*` staging 才能原子发布为正式备份目录。
- `backup` 和 `restore` 必须持有与 `up`、`down`、TLS 写操作相同的 project 级 Windows named mutex，并按每个 source/target physical volume name 获取独立 mutex，避免不同 Compose project 通过同一物理卷并发维护。备份根目录、staging/正式备份、`-ForceRestore` rollback archive 和恢复后的 CMS 明文文件必须自动应用受保护的 restricted ACL，只允许当前用户、SYSTEM 和 Administrators 完全控制，并关闭继承。
- `backup-verify` 必须校验 `manifest.sha256`、全部工件大小和 SHA-256、PostgreSQL dump 列表、路径边界、15 个默认服务的 image reference/实际 image ID，以及当前 `compose.windows.yml` 的精确 SHA-256、Git commit、项目版本、S3 bucket、OpenSearch index 和 `DRIVE_TLS_CERT_NAME` lineage 名称。卷 tar 在用于恢复前必须先放入无网络、只读根文件系统、只读备份挂载、drop all capabilities 和 `no-new-privileges` 的临时容器/临时卷中预解包扫描，拒绝绝对路径、父目录穿越、硬链接、特殊文件、悬空链接和指向临时卷外的符号链接。
- `restore` 必须使用与 source 不同的 Compose project，并拒绝运行中的 target、source/target physical volume 重叠、错误卷标签和 foreign container attachment；默认还要拒绝已有容器和非空目标卷。`-ForceRestore` 只允许清理已停止的目标容器或非空卷，不得绕过同 project、运行状态、路径、校验和镜像门禁；清空任何原非空卷前必须先创建 restricted rollback archive，恢复失败时还原原非空卷、清空原空卷、删除本轮新卷并停止 target 服务，回滚异常时保留并报告 rollback archive 路径。恢复一旦提交，后续 rollback archive 清理失败只能报告维护错误并保留归档，不得反向清空或回滚已经恢复的数据。`-NoStartAfterRestore` 用于恢复后保持服务停止。
- `-RestoreEnvironmentOutput` 必须是仓库和备份目录外的绝对、尚不存在文件路径，父目录必须预先存在且不得经过 reparse point；CMS 明文只能保存在内存中，并在本次恢复模式的数据、Alembic revision 和镜像门禁全部成功后，通过同目录受限 ACL 临时文件原子发布。未使用 `-NoStartAfterRestore` 时还必须先通过完整服务健康与实际容器 image ID 对账；发布竞态中若目标路径被其他进程创建，脚本必须保留该 foreign file，不得在失败清理中删除。
- Windows CMS 只加密 `.env.windows`。PostgreSQL dump、MinIO/Redis/OpenSearch 原始卷归档和包含私钥的 TLS 证书卷归档依赖 BitLocker、自动 restricted NTFS ACL 和加密外部介质，不属于完整包级应用层加密；CMS 私钥必须单独导出并保存在受保护介质中。
- `manifest.sha256` 和各工件 SHA-256 只用于完整性校验，不认证备份制作者身份；来源认证必须通过受保护签名、受控传输和保管链完成。
- Redis/OpenSearch 使用停止后的原始卷归档，恢复只支持相同 image reference、相同 image ID、单节点同拓扑；跨版本或拓扑变化必须改用对应产品支持的迁移或快照机制。
- `-ForceRestore` rollback archive 是失败时的尽力恢复机制；发生卷驱动、磁盘或 Docker 故障时仍可能需要人工处理，脚本必须保留受限 ACL 归档并报告绝对路径。
- 当前固定 MinIO Server/Client 镜像仍有 16/9 个 Critical 唯一 ID 基线，其中两个 MinIO 自身 Critical 在固定社区镜像中没有 patched version；CI 阻断允许集之外的新 Critical 并不消除现有风险。正式发布前必须采用受支持修复镜像或完成可审计补丁镜像、SBOM/Grype 重扫、真实 MinIO 和备份恢复兼容验证，风险登记以 `docs/minio-security-risk.md` 为准。
- 周期维护任务由独立 `beat` 容器运行 Celery beat，至少覆盖过期上传、无引用 blob、孤儿最终对象和容量校准；调度不得与 API 进程混跑。
- Nginx gateway 必须处理 WebSocket、Range、上传大小限制、超时、真实客户端 IP、安全响应头，以及 API 与外部 S3 端点的分流；公网模板还必须保持证书只读挂载、TLS 1.2/1.3、HTTP 到 HTTPS 跳转、ACME challenge 路径、未知 Host 拒绝和 HSTS。正式发布前必须完成受信证书与双域名 HTTPS 实测。

发布顺序：

- 合并代码前运行 ruff、mypy、pytest、OpenAPI diff、Compose config 校验和镜像构建。
- 更新前创建 PostgreSQL、MinIO 对象和关键配置/证书备份，并记录当前镜像 tag、migration 版本和环境模板版本。
- 执行一次性 migration 服务，只允许向前兼容 migration。
- 启动 API，等待 `/readyz` 真实数据库探针通过后再让 gateway 接流量。
- 启动 Worker 和 `beat`，按队列逐类检查，避免任务中断扩大。
- 观察错误率、延迟、队列积压、数据库慢查询、对象存储异常、容器重启次数和 Windows 宿主磁盘空间。
- 发布完成后标记版本、归档 OpenAPI、记录 migration 与 Compose 配置版本。

回滚原则：

- 应用通过上一个可用镜像 tag 和上一版 `compose.windows.yml` 快速回滚。
- named volumes 默认保留，停止或回滚时不得默认执行 `docker compose down -v`。
- 数据库 migration 原则上只做向前兼容，避免依赖回滚 DDL；恢复数据库备份必须经过明确维护窗口。
- 如果必须执行破坏性迁移，必须先做影子字段和双写验证。
- Worker 任务 payload 必须兼容至少一个旧版本。
- Kubernetes、systemd 只作为未来迁移或其他平台的可选方案，不是当前默认部署路径。

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
- Windows 11 Docker 部署相关改动已通过 Compose config、镜像构建、容器健康检查、真实 `/readyz` 数据库探针、Worker 工具检查和停止回收验证；备份恢复相关改动还必须通过 manifest/工件校验、CMS 正负例、source 状态恢复、target 失败隔离和不同 Compose project 的真实恢复演练。
- `PROJECT_PROGRESS.md` 已记录完成事项、风险、下一步和验证方式。
- 可运行、可回滚、可排查；没有把临时方案伪装成最终方案。
