# PROJECT_PLAN.md

本文件是《企业网盘开发者技术计划书.md》的执行版摘要。完整架构、数据模型、接口契约、安全策略和里程碑以技术计划书为准。当前一期以可试点上线的后端为交付目标，后续路线已纳入 Rust 桌面客户端、Web 用户端与管理后台、核心产品闭环、企业身份、安全治理和稳定版发布。

## 1. 项目目标

一期实现一个可试点上线的企业网盘后端，重点保障：

- 文件元数据、对象存储、权限、审计、搜索和异步任务之间的数据一致性。
- 大文件、断点续传、秒传、并发上传和失败重试。
- 服务端可信权限判断，支持空间角色、目录 ACL、继承、拒绝优先和外链策略。
- 文件对象与用户路径解耦，支持移动、重命名和版本管理。
- 关键操作可审计，审计日志不因外部日志平台异常而丢失。
- uv 锁定依赖，CI 可重复构建，本地依赖服务可一键拉起。

## 2. 技术路线

- 后端：Python 3.12+、FastAPI、SQLAlchemy 2.x、Alembic、uv。
- 数据库：PostgreSQL 16+。
- 缓存与限流：Redis。
- 对象存储：S3 兼容存储，本地可用 MinIO。
- 搜索：OpenSearch。
- 异步任务：Celery。
- 部署：正式目标为 Windows 11 + Docker Desktop（WSL2/Linux containers），使用仓库根 `compose.windows.yml` 编排；Nginx gateway 位于 Compose 内并且是唯一宿主端口入口。
- 二期桌面客户端：Rust stable、Cargo workspace、Tauri 2，Windows 11 优先；同步、传输、本地索引、文件系统监听、凭据和更新校验使用 Rust 实现。
- Web 用户端与管理后台：TypeScript、React、Vite、OpenAPI 生成客户端和 Playwright；默认目录为 `frontend/`，使用 BFF Cookie Session 和 CSRF，不在浏览器存储 bearer token。

## 3. 架构原则

- 一期采用模块化单体，不提前拆微服务。
- 分层路径为 `router -> service -> domain/policy -> repository -> db/infrastructure`。
- 模块之间通过 service 接口协作，禁止跨模块直接访问 repository。
- 领域事件统一通过 outbox 或任务队列投递。
- Redis、OpenSearch、对象存储都不是核心事实来源，核心事实以 PostgreSQL 为准。
- 桌面客户端以服务端变更日志和版本号为远端事实来源，以本地 SQLite 索引和操作日志支持离线恢复；不得以本地目录扫描结果直接覆盖远端状态。
- Web 与桌面端都只消费服务端权限、错误码、枚举和 OpenAPI 契约；客户端隐藏按钮、缓存状态或本地索引不构成权限和业务事实。

## 4. 里程碑

### Sprint 1：工程底座

- uv 工程、FastAPI app、配置、日志、错误响应、request_id middleware。
- SQLAlchemy、Alembic、PostgreSQL、Redis、MinIO 本地 compose。
- 用户登录、BFF Cookie 会话、基础用户表和管理员 seed。
- CI：ruff、mypy、pytest。

### Sprint 2：空间和文件树

- space、node、file_blob、file_version model 和 migration。（已完成基础骨架）
- 空间创建、文件夹创建、文件列表。（已完成最小 API）
- 重命名、移动、删除到回收站、恢复。（已完成最小 API）
- 同目录重名策略和 cursor pagination。（已完成基础约束和签名游标）
- 基础审计日志。（已完成空间和文件树操作审计）
- 回收站分页和批量文件操作。（`BE-037` 已完成删除批次根节点签名 cursor 列表、批量删除/移动/恢复/彻底删除、逐项结果和持久化幂等重放）
- 同名冲突策略。（创建文件夹、移动、恢复及批量入口已支持 `fail`、`keep_both`、`replace`；replace 把原节点移入回收站）
- 大目录操作。（删除、恢复、彻底删除超过阈值后进入 `file_tree_operations`，由 maintenance Worker 使用 `deleted_root_id`、递归 CTE 和固定批次可恢复执行）

### Sprint 3：上传下载

- upload_session、multipart presign、complete、abort。（已完成会话初始化、状态查询、分片 presign、multipart complete 和 abort）
- 秒传、对象存储适配、容量初版、服务端 hash 校验和最终对象 key 规整。（已完成 StorageAdapter、秒传创建首版本、空间容量账本初版、multipart complete 后 `sha256` 校验和 `objects/{tenant_id}/{hash_prefix}/{content_hash}` 归档）
- 过期上传清理任务。（已完成 `upload.expire_sessions`，按租户扫描过期会话并清理临时对象）
- 基础限流。（已完成上传初始化、分片签名和下载预签名的 Redis 固定窗口限流）
- 删除容量释放。（已完成回收站节点彻底删除时释放空间容量并写入负向容量流水）
- Blob 垃圾回收和最终对象清理。（已完成 `file.cleanup_unreferenced_blobs`，按租户清理无版本引用且引用计数为 0 的最终对象）
- 孤儿最终对象扫描。（已完成 `file.cleanup_orphaned_objects`，按对象存储游标扫描受控 `objects/{tenant_id}/{hash_prefix}/{sha256}` key，默认 dry-run，显式确认后删除无 DB blob 元数据引用的孤儿最终对象，并写入审计和指标）
- 下载预签名 URL。（已完成当前版本下载签名）
- 上传下载审计。（已完成上传初始化、秒传、complete、abort、expired 和下载成功/拒绝审计）
- 企业级补强计划：当前上传/下载链路已具备主路径能力，`BE-031`/`BE-032` 的对象存储稳定性补强已完成；multipart 控制面使用 MinIO 公共预签名 API 和标准 S3 HTTP POST/DELETE，不再调用 SDK 私有方法，真实 MinIO、异常完成恢复、失败清理和同 hash PostgreSQL 并发测试已形成门禁。

### 上传下载企业级补强计划

上传/下载链路、秒传、multipart、服务端 hash 校验、容量账本和彻底删除容量释放是当前最重要的企业级主链路。现阶段已经形成基础闭环，但上线前必须继续按以下计划补强，避免把临时实现误当成企业级完成态：

- MinIO multipart create/complete/abort 已改为 `S3MultipartControlClient`：通过公共 `get_presigned_url` 生成内部短期控制 URL，再发送标准 S3 HTTP POST/DELETE 和 XML 请求，不再依赖 `_create_multipart_upload`、`_complete_multipart_upload`、`_abort_multipart_upload`。依赖范围锁定为 `minio>=7.2.20,<8`，控制请求超时与 URL 有效期可配置；升级必须通过真实 MinIO 集成门禁。
- 对象复制到最终 `objects/{tenant_id}/{hash_prefix}/{content_hash}` 成功但数据库最终化失败后，可能出现孤儿最终对象。`file.cleanup_orphaned_objects` 反向扫描任务及 `BE-031/BE-032` 的真实 MinIO 主路径验收已完成；仍需由 `BE-035` 补生产失败告警、积压/吞吐看板和周期运行治理。
- `BE-033` 已补齐空间、可选用户、可选租户和文件策略四类容量账户，上传初始化执行快速检查，版本创建通过原子条件更新和统一 ledger 扣减，彻底删除按版本流水释放全部维度。仍待 `BE-044` 提供账户/策略管理 API，并补部门额度、临时上传占用上限和多维通用校准。
- `BE-035` 已在 Celery beat 既有调度上补齐原五个维护任务的 Redis 连续失败状态、结构化阈值告警、stale/时间戳 Gauge、通用任务结果计数和 Prometheus 规则文件；本轮新增的 `file.process_tree_operations` 已接入同一健康状态。外部 Alertmanager 路由、完整看板、过期分享和预览产物治理继续后续交付。
- `BE-034` 已在短期预签名直连之外补充内部受控代理下载、单段 HTTP Range、流式对象读取和范围审计；低风险大文件继续使用预签名直连。密级标签自动强制代理、外链代理、水印和内容 DLP 仍属后续治理策略。
- 同 hash 首次上传竞争已使用数据库 savepoint 解析唯一约束竞争：并发事务只创建一个 blob，后续事务复用并原子增加引用；真实 PostgreSQL 双会话测试确认 `1` 个 blob、`ref_count=2`。complete 响应丢失时会通过对象 stat 恢复结果，hash、归档或数据库最终化失败会最佳努力 abort multipart 并删除 `uploads/...` 临时对象，最终对象孤儿继续由既有反向扫描兜底。
- 真实对象存储集成测试已在 CI 和本机真实 Docker 中覆盖标准 HTTP multipart、预签名 PUT/GET、copy、delete、list、hash 校验和孤儿最终对象扫描；单元门禁覆盖 complete 成功但响应丢失后的 stat 恢复，以及不存在 upload 的幂等 abort。

### Sprint 4：权限系统

- 空间成员和角色。（已完成 `space_members` 用户成员基础表、创建空间 owner 成员写入、空间级成员角色检查和 owner/admin 成员管理 API）
- 目录 ACL、权限继承、拒绝优先。（已完成用户、部门、用户组三类节点 ACL 主体，管理 API、继承开关、deny 优先和文件/上传/下载关键入口校验）
- 权限缓存和失效事件。（已完成文件列表批量权限评估、`permission.changed` outbox 事件写入和 Redis 缓存失效 worker）
- 部门/用户组 ACL 主体。（已完成 `departments`、`department_members`、`user_groups`、`user_group_members` 事实表、repository 和权限判断主体展开）
- 搜索 ACL 事件、文件索引写入和查询过滤。（已完成 ACL token builder、`search.acl_rebuild_requested` outbox event、上传完成、重命名、移动、删除、恢复和彻底删除后的 `search.index_requested` 事件、OpenSearch 文件索引写入/删除入口、ACL 变更后的保守范围重建，上传完成后的 `search.extract_requested` 文本/PDF/DOCX/PPTX/XLSX 抽取入口，以及 `GET /api/v1/search` 查询层 allow/deny token 过滤、签名 cursor 分页、highlight、搜索限流和应用层二次权限校验）
- 高危操作二次查库。（已完成；权限读路径当前直接以 PostgreSQL 空间成员与 ACL 为事实来源，成员/ACL 管理、上传完成、下载、分享、预览和文件写操作均在对应接口重新调用权限服务）

### Sprint 5：分享、预览、搜索

- 内部分享和外链分享。（已完成基础表、迁移、服务层、创建/详情/撤销 HTTP API、带租户边界的外链访问入口和外链下载入口）
- 提取码、过期、次数限制、撤销。（已完成提取码哈希、过期/次数字段、撤销服务、外链访问次数原子扣减、外链下载次数原子扣减、IP 总量和 `token + IP` / `token + node + IP` 维度限流）
- 预览任务和搜索索引任务。（已完成搜索索引/抽取入口、图片 WebP 预览、PDF 首页 WebP 预览和 Office 通过 LibreOffice headless 转 PDF 的基础链路）
- 权限过滤与二次校验。（已完成；搜索查询同时执行 OpenSearch allow/deny token 过滤和 PostgreSQL `read_meta` 二次校验，分享、预览与下载在签发访问地址前重新检查当前权限）

### Sprint 6：管理、治理、上线

- 管理员审计查询 API。（已完成 `GET /api/v1/admin/audit-logs`，仅系统管理员可访问，按租户隔离，支持用户、资源、动作、结果、风险、请求 ID、时间范围和签名 cursor 筛选，并审计成功与拒绝查询）
- 用户、部门、用户组、空间、配额、统计、维护和导出等完整管理 API 按 Sprint 9 的 `BE-044`、`BE-045` 继续交付。
- 生命周期治理、孤儿对象扫描和容量治理增强。（`BE-026` 已完成过期上传、无引用 blob 和回收站保留期清理；回收站任务按删除批次根节点加锁清理，释放容量、扣减 blob 引用并写入审计、搜索事件和指标；完整策略化治理继续由 `BE-047` 承担）
- 多维配额核心运行时已完成；账户/策略管理 API 和容量治理看板继续由 `BE-044`、`BE-045` 提供。维护任务定时调度、连续失败告警和清理指标已由 `BE-035` 完成核心运行时。
- 高密级下载治理：后端流式代理、单段 HTTP Range 和增强审计已完成；密级标签自动选路、外链代理、水印和 DLP 策略继续后续交付。
- Windows 11 Docker Desktop 正式部署：多阶段 Dockerfile、根 `compose.windows.yml`、Compose 内 Nginx gateway、根 `.env.windows.example` 和 `deploy/windows/manage.ps1`。（已完成本机 HTTP 基线、公网 ACME/TLS 配置、续期命令及 `backup`、`backup-verify`、`restore` 自动化；真实 DNS/受信证书验收待生产环境执行）
- API、migration、seed、MinIO 初始化、按队列隔离的 Worker、Celery beat、PostgreSQL、Redis、MinIO、OpenSearch 的完整编排；只有 gateway 发布宿主端口，默认 HTTP `18080/19000`，公网模式由 gateway 发布 `80/443` 并按 API/存储域名 Host 分流。（已完成）
- S3 容器内端点和浏览器外部端点分离；默认本机 API 为 `http://localhost:18080`、S3 外部端点为 `http://localhost:19000`，均由 gateway 发布；生产支持 API/存储独立域名的 Host 分流并保留原始 Host。（已完成）
- named volumes、真实 `/readyz` PostgreSQL 探针、Preview Worker 资源限制、定时维护任务和数据库连接池边界。（已完成）`v0.4.0` 已交付 PostgreSQL custom dump、MinIO/Redis/OpenSearch/TLS 停止状态卷归档、CMS 环境文件保护、15 个默认服务实际容器 image ID 与精确 Compose/Git/版本/configuration lineage 门禁、project/逐物理卷 mutex、restricted ACL、隔离 tar 预扫描、`-ForceRestore` rollback archive、失败恢复和不同 Compose project 真实端到端演练；后续继续建设周期恢复演练、备份介质轮换、告警和治理看板。
- Kubernetes、systemd 降为未来可选迁移方案，不作为当前交付目标。

### Sprint 7：Rust 桌面客户端基础（目标版本 `0.5.0`）

- 在 `desktop/` 建立 Cargo workspace 和 Tauri 2 桌面应用，Windows 11 作为首发平台。
- Rust crate 按职责拆分为 API client、设备会话、同步引擎、本地 SQLite 索引、传输队列、文件系统适配和系统凭据适配；界面层只消费状态和发送命令。
- 后端新增桌面设备会话、设备列表与吊销、短期会话轮换；凭据只保存于 Windows Credential Manager 等系统凭据库，不写入普通配置文件或日志。
- 后端新增按租户和用户隔离的增量变更游标、删除 tombstone、节点/版本前置条件和幂等客户端操作 ID，桌面端不通过高频全量目录轮询实现同步。
- 固定 `Drive Transfer Protocol v1` 应用层契约：控制面使用版本化 HTTPS API，数据面使用短期预签名 HTTPS 直传 MinIO/S3；协议定义分片大小、并发提示、批量签名、断点状态、分片校验、整文件 SHA-256、幂等完成、取消和错误码，不自研 TCP/UDP、TLS 或可靠传输层。
- 桌面 Alpha 首批功能包括登录、空间和目录浏览、上传/下载队列、暂停/继续/取消、任务栏托盘、同步目录选择、离线元数据浏览和错误诊断导出。
- CI 增加 `cargo fmt --check`、Clippy、Rust 单元/集成测试、依赖许可证与漏洞门禁，以及 Windows 安装包构建。

### Sprint 8：Rust 双向同步与桌面发布

- 实现远端变更拉取、本地文件系统监听、离线操作队列、进程重启恢复和网络恢复后续传。
- 下载先写同目录临时文件，完成 hash 校验后原子替换；上传复用现有 multipart、秒传和服务端 hash 校验，不绕过权限、审计、容量与限流。
- 冲突默认保留双方内容并生成带设备名和 UTC 时间的冲突副本，禁止静默覆盖；删除与修改、重命名与移动冲突必须形成可审计结果。
- Windows 路径层统一处理大小写折叠、保留设备名、尾随点/空格、Unicode normalization、长路径、符号链接和 reparse point；默认不跟随符号链接或 junction。
- 支持选择性同步、带宽与并发限制、文件忽略规则、失败重试和按文件查看同步状态；虚拟盘占位文件与 Windows Cloud Files API 作为后续增强，不进入首个双向同步版本。
- 发布经过签名的 Windows 安装包和更新清单，更新包必须验签并支持失败回退；Windows 稳定后再推进 macOS 和 Linux 适配。
- 验收至少覆盖 10,000 文件初始索引、1 GB 文件中断续传、离线编辑恢复、同文件双端并发修改、目录重命名冲突、异常退出恢复和凭据吊销。

### Sprint 9：核心产品能力闭环（目标版本 `0.6.0`）

- 文件版本：版本列表、指定版本下载、回滚为新版本、版本审计和容量流水。（`BE-036` 已完成核心 API：签名 cursor、DTP/1 历史版本下载、当前版本前置条件、不可变回滚、多维配额和事件）
- 回收站与批量操作：回收站分页列表、批量删除、移动、恢复和彻底删除；批量结果逐项返回，所有写操作支持 `Idempotency-Key`。（`BE-037` 已完成核心 API、迁移、部分失败和幂等重放）
- 内部分享接收端：“分享给我的”、创建者分享列表、接收人详情与下载、部门/用户组成员变化后的授权重算、撤销和站内通知。
- 管理 API：用户、部门、用户组、空间、配额、审计、统计、维护任务和导出，所有管理操作写审计并支持 cursor 分页。
- 完成上述接口的 OpenAPI、迁移、权限、审计、并发、容量和端到端测试，为 Web 与桌面客户端提供稳定契约。

### Sprint 10：Web 用户端与管理后台（目标版本 `0.7.0`）

- 在 `frontend/` 建立 TypeScript + React + Vite 工程，生成并锁定 OpenAPI client，统一 API 错误、Cookie Session、CSRF、request_id 和权限枚举处理。
- 用户端覆盖登录、空间/目录、批量操作、上传队列、下载、搜索、预览、回收站、文件版本、分享创建、分享给我的、通知中心和账号基础页面。
- 管理后台覆盖用户、部门、用户组、空间、配额、审计、统计、维护任务状态和导出；管理员路由与后端管理权限同时校验。
- 构建产物通过 Compose 内部 Web 服务交给 gateway，同一 API 域名下使用 `/api/v1`，Web 服务不直接发布宿主端口。
- CI 增加 lint、类型检查、单元测试、构建、OpenAPI breaking-change 检查和 Playwright E2E；验收覆盖 Chromium、Firefox、WebKit 和 Windows 常用缩放比例。

### Sprint 11：身份与账号安全（目标版本 `0.8.0`）

- 登录失败按用户与 IP 限流，支持阶梯延迟、临时锁定、管理员解锁和可插拔验证码，并写成功、失败、锁定和解锁审计。
- 密码管理支持用户改密、管理员重置、首次登录强制改密、全会话吊销、密码策略和受保护的恢复流程。
- OIDC/OAuth 2.1 + PKCE 支持提供商配置、账号绑定、回调状态校验、单点登录和单点登出；浏览器继续签发服务端 Cookie Session。
- LDAP 支持只读目录同步、稳定外部 ID 映射、用户/部门/组增量同步、禁用与离职处理、冲突报告和 dry-run。
- Web 用户端补齐验证码与锁定反馈、用户改密、首次登录强制改密、会话列表/吊销和 OIDC 登录回调；管理后台补齐账号解锁、密码重置、OIDC 提供商、LDAP 目录源、连接测试和同步运行记录。
- 完成身份提供商故障、重放、账号冲突、会话撤销、CSRF、开放重定向和权限边界安全测试。

### Sprint 12：规模化治理与内容能力（目标版本 `0.9.0`）

- 大目录删除、恢复和彻底删除已迁移到可恢复后台批处理并引入 `deleted_root_id`；大目录权限重算、管理页面和 closure table 规模触发条件继续后续治理。
- 生命周期覆盖过期分享、预览产物、回收站保留期、临时上传、无引用 blob 和孤儿对象，具备 dry-run、审计、指标、告警和失败重试。
- 搜索增加图片 OCR、扫描 PDF 和复杂格式抽取适配，限制页数、像素、CPU、内存、临时磁盘和正文体量。
- 审计增加月分区自动创建、保留与归档、外部日志投递、导出签名；Outbox 增加错误分类、jitter、dead-letter 查询与重放。
- 备份增加来源签名、可选完整包加密、离线副本轮换、周期隔离恢复记录，以及 Redis/OpenSearch 跨版本快照或迁移流程。
- 管理后台补齐大目录任务进度、生命周期策略/运行记录、审计归档与外部投递状态、Outbox dead-letter 查询/重放和治理告警页面。
- 完成真实 PostgreSQL、Redis、MinIO、OpenSearch 的集成矩阵、性能基准、故障注入和治理看板验收。

### Sprint 13：稳定版发布（目标版本 `1.0.0`）

- 后端、Web、Rust 桌面端完成统一版本、契约、安装升级、回滚和发布说明。
- 执行完整 UAT、性能压测、安全测试、依赖与镜像扫描、备份恢复、桌面升级和浏览器兼容验收。
- 修复所有阻断试点和正式发布的问题，明确已接受风险、运维责任、告警阈值、RPO/RTO 和支持边界。
- `dev` 合并 `main`，生成 `v1.0.0` tag、Release、OpenAPI 快照、SBOM、安装包、镜像和验收报告。

### 远期正式 Backlog

- `PLAT-001`：Windows Cloud Files API 虚拟盘占位文件。
- `PLAT-002`：macOS File Provider 与 Linux 虚拟文件系统适配。
- `PLAT-003`：WebDAV 网关。
- `PLAT-004`：SMB 网关。
- `PLAT-005`：Kubernetes 与 Linux systemd 迁移。
- `CLIENT-001`：Android、iOS 和移动 Web 产品调研与路线决策。
- `COLLAB-001`：在线 Office 协同与审批流。
- `GOV-001`：复杂 DLP、内容分类和 legal hold。
- `DR-001`：跨地域双活。
- `BILL-001`：多租户计费。

## 5. 当前下一步

2026-08-01 已按“实现优先、减少重复测试”的执行决策暂停 `BE-029` 目标规模灌入和完整 target profile。现有 Locust、真实 multipart、checkpoint、精确清理和 `BE-029/2` 报告成果保留，目标压测留到发布性能门禁恢复执行，不再阻塞编号靠后的工程功能。

2026-08-02 `BE-037` 回收站与批量文件操作已实现：回收站按 `deleted_at/id` 签名 cursor 仅列删除批次根节点；批量删除、移动、恢复和彻底删除最多处理 100 项，每项使用 savepoint 并逐项返回结果。新增 `file_batch_operations` 与 `20260801_0015` migration，按租户、用户、操作和 key hash 保存请求 hash/最终响应；同请求重放、异请求冲突。下一项进入 `BE-038` 内部分享接收端。

2026-08-02 Sprint 2 剩余增强已完成：文件树同名冲突支持 `fail/keep_both/replace`；大目录删除、恢复和彻底删除使用 `20260802_0016`、`file_tree_operations`、`deleted_root_id`、状态/重试 API 和 `file.process_tree_operations` 分批执行，任务中断后可从 PostgreSQL 状态继续。下一项仍为 `BE-038`。

2026-08-01 `BE-036` 文件版本核心 API 已实现：版本列表按 `created_at/id` 使用服务端签名 cursor 分页并标记当前版本；指定历史版本下载复用 DTP/1、下载权限和预签名限流；回滚在节点行锁内校验可选 `expected_current_version_id`，复用原 blob 创建递增新版本，原子增加引用、扣减多维配额、更新当前版本，并写入审计、搜索索引/抽取和预览事件。后续已进入并完成 `BE-037`。

2026-08-01 `BE-035` 维护任务监控核心运行时已实现：现有 Celery beat 继续调度五个 maintenance 任务，Celery signal 在每次结束后把连续失败和最近成功/失败时间原子写入 Redis；maintenance Worker 暴露连续失败、alert、stale、时间戳和任务结果计数，达到阈值时写结构化错误日志，并提供可加载的 Prometheus 规则文件。下一项进入 `BE-036` 文件版本列表、指定版本下载与回滚。

2026-08-01 `BE-034` 内部受控下载核心运行时已实现：新增 `GET /api/v1/files/{node_id}/content`，复用现有节点权限、版本和 blob 校验，通过对象存储适配器按 offset/length 分块流式读取，支持完整响应和单段 HTTP Range，并在审计中记录代理模式、范围和响应字节数。普通预签名入口保持不变；密级标签自动强制代理、外链代理、水印和内容 DLP 留给后续治理策略。

2026-08-01 `BE-033` 多维配额核心运行时已完成：新增 `quota_policies` 事实表；空间账户始终参与扣减，用户/租户默认额度大于 `0` 时启用对应账户，策略可按扩展名或 MIME 前缀限制累计额度和单文件大小；秒传和 multipart complete 在同一事务内按固定顺序执行原子扣减并写入各维度 ledger，彻底删除与回收站保留期清理按版本正向流水释放全部维度。当前默认用户/租户额度为 `0`，策略管理 HTTP API 与通用多维校准归 `BE-044`。

2026-08-01 `BE-029` multipart/report 收尾已通过真实隔离 Compose：`upload_complete` 执行 DTP/1 init、part presign、无 Cookie MinIO PUT、complete 和清理；Server-Timing 分段的 storage merge P95 为 `30 ms`，扣除 merge 的 complete API P95 为 `190 ms`，稳态 PUT P95 为 `120 ms`，0 失败。`report.json` 已升级为 `BE-029/2`，真实采集主机内存/磁盘、Docker server、9 个 compose 容器的 image ID/digest/限额、PostgreSQL `133` 个索引和 `10,361,879` bytes 数据库体量；该报告 smoke 的容器、卷和网络均清理为 `0`。100 万/1,000 万目标数据实际灌入和完整 target profile 尚未执行，现已作为非阻塞发布门禁待办保留。

2026-07-31 已完成 `BE-026` lifecycle cleanup jobs：现有 `upload.expire_sessions` 和 `file.cleanup_unreferenced_blobs` 加上新增 `file.cleanup_expired_trash` 已覆盖原验收中的过期上传、blob 清理和回收站清理。新增任务按删除批次根节点扫描并锁定子树，删除版本和节点、释放容量、扣减 blob 引用、写入搜索删除事件与系统审计；迁移 head 更新为 `20260731_0013`，Celery beat、Windows Compose 环境、Prometheus 指标、SQLite 回归测试和真实 PostgreSQL Docker 集成测试均已同步。随后已按编号完成 `BE-027` metrics/tracing 和 `BE-028` Windows Docker Compose 正式部署门禁。

2026-07-31 本机 Docker Desktop 已重新安装并恢复 `desktop-linux`：Docker client/server `29.6.2`、Linux `amd64` daemon 和 Docker Compose `v5.3.1` 可用；`compose.windows.yml` 使用 `.env.windows.example` 静态校验通过并解析出 15 个默认服务。Nginx、Certbot、PostgreSQL、Redis、MinIO Server/Client、OpenSearch、runtime 和 preview 镜像均已独立准备；runtime/preview 分别在 `1 CPU / 2 GiB` 和 `1 CPU / 3 GiB` BuildKit 上限下构建完成，本地镜像没有重复 image ID。当前没有运行中或残留容器。

2026-07-31 `BE-028` 已完成。首次备份恢复测试暴露旧入口把镜像构建、15 服务启动、备份、重复成功校验和恢复串成黑盒任务，且辅助容器缺少资源边界；现已把拉取、构建、启动和恢复测试拆分，普通 `manage.ps1 up` 固定 `--no-build --pull never`，备份 helper 默认限制 `0.50 CPU / 512m / 128 PIDs`、禁用额外 swap，gzip/`pg_dump` 默认压缩等级为 `1`。真实 integration 提供 `-PreflightOnly`、`COMPOSE_PARALLEL_LIMIT=1`、Worker concurrency `1`、分阶段耗时、默认数据服务恢复和显式 `-FullStackRestore`，失败时在清理前输出异常容器状态与尾部日志。OpenSearch 测试专用容器上限从不稳定的 `1024m` 调整为 `1280m`，正式默认仍为 `3g`。默认恢复和完整 target 全栈恢复分别在 `409.6s`、`357.3s` 内通过，完整栈采样峰值为 `123.5%` aggregate Docker CPU 和 `2226 MiB` 容器内存，结束后容器均为 `0`；GitHub Actions run `30648296028` 全部成功。

2026-07-31 `BE-029` 现状审计、第一版工具链和真实 Docker smoke 已落地：原仓库没有 benchmark/load-test 文件、Locust/k6/pytest-benchmark 依赖或 CI 性能门禁。新增 `backend/performance/`，使用仅 dev 依赖的 Locust，提供 `smoke`（100 个 fixture 子目录、2 用户、20 秒）、`baseline`（1,000、10 用户、60 秒）和显式 `target`（10,000、50 用户、300 秒）三档；fixture 使用单一随机根目录承载全部子目录，清理时先软删整棵子树再一次 purge，上传初始化继续使用稳定父目录，避免已取消会话外键阻塞清理。runner 捕获 Locust stdout/stderr，输出真实的 `stats_stats.csv`、history/failures/exceptions CSV、HTML 和可审计 `report.json`；OpenSearch 索引尚未创建时搜索返回空结果，其他 404 继续抛出。新增 `performance.target_data`，按专属 index/action 分阶段生成 100 万 OpenSearch 文档和 1,000 万审计日志，使用确定性 ID、批次 checkpoint、显式大规模确认和只清理自身数据的恢复/清理路径。2026-08-01 又以本地固定镜像和资源受限的 PostgreSQL/OpenSearch 容器完成 `100/100` 暂停、恢复到 `1,000/1,000`、精确清理到审计 `0`/index `404` 的真实闭环，并把 CLI 默认值收紧为每次 1 批、显式 `0` 才不限批次。隔离真实 Compose smoke 共执行 170 次请求、0 失败，文件列表/初始化上传/搜索/审计 P95 分别为 32/92/71/25 ms，报告 `passed=true`；峰值为 6 个容器、162% aggregate Docker CPU 和 1506.1 MiB 容器内存，fixture、容器、网络、卷和端口全部清理。首版覆盖登录、Cookie Session `/auth/me`、文件列表批量权限评估、DTP/1 `uploads/init`、搜索和管理员审计分页；真实 multipart complete 压测、100 万/1,000 万目标数据实际灌入和完整 target profile 验收仍未完成，不能把小闭环或 smoke 结果当作目标规模验收。

2026-07-31 `BE-030` 首轮安全测试修复已通过提交 `25acecf` 和 GitHub Actions run `30660034411` 闭环：对当前虚拟环境 123 个实际包的审计发现 20 条记录全部来自攻击者可达的图片预览依赖 `Pillow 12.2.0`，已升级并锁定 `Pillow 12.3.0`；加入项目内 `bandit` 与 `pip-audit` dev 依赖和 CI 门禁，升级后审计 145 个环境包为 0 已知漏洞，Bandit 中危/高危为 0。登录新增来源 IP 与账号哈希双维 Redis 固定窗口，不存在租户/用户时仍执行 Argon2id dummy verify；422 校验错误不再回显原始 `input`。随后 production `Settings` 应用内 fail-fast 已通过提交 `a52b4ce` 和 GitHub Actions run `30661668693` 闭环：API、Worker、beat、migration 和 seed 会拒绝示例/过短 secret、无强密码连接 URL、关闭限流、Wildcard Trusted Hosts 及不安全公网 CORS/S3/Cookie 配置，同时保留纯 localhost/回环 HTTP 基线；完整后端门禁为 `188 passed, 4 skipped`，受限 runtime 镜像和真实 PostgreSQL/认证 Redis/API/Worker Docker smoke 均已通过并彻底清理。2026-08-01 已继续完成 route 身份/租户、撤权、恶意文件、Range、预签名 URL、外链穷举、Host/CORS 和真实 Nginx 原始 HTTP 门禁，`BE-030` 进入提交与远端 CI 收尾。

2026-07-31 已把此前仅停留在接口示例、技术建议或“后续接入”的能力补成 Sprint 9 至 Sprint 13、工程任务和远期 Backlog。当前执行顺序保持：先完成 Sprint 6 和 `v0.4.0` 正式发布，再推进 Sprint 7/8 Rust 桌面端；随后按核心产品闭环、Web 用户端与管理后台、身份安全、规模治理、`v1.0.0` 稳定发布推进。桌面端所依赖的版本前置条件和增量变更契约继续优先交付，Web 页面不得反向定义后端业务规则。

2026-07-31 已把 Rust 桌面客户端从笼统的二期增强项提升为 Sprint 7 和 Sprint 8 正式路线。当前仓库仍没有桌面客户端代码；先完成 Sprint 6、发布 `v0.4.0`，随后以 `0.5.0` 为桌面 Alpha 目标建立 `desktop/` Cargo workspace。开工顺序固定为：先提交桌面架构 ADR 和后端设备会话/增量同步契约，再实现 Rust API client、本地索引和单向传输，最后进入双向同步、冲突处理和签名发布。

2026-07-31 已正式启用 `Drive Transfer Protocol v1`（线协议标识 `DTP/1`）：新增 `docs/drive-transfer-protocol-v1.md`，上传、文件下载和外链下载公开可选 `X-Drive-Transfer-Protocol` 协商头，未知版本返回 HTTP 426，全部传输响应返回 `protocol_version=DTP/1`。协议自定义的是 HTTPS 之上的分片、断点、校验、幂等和错误状态机，数据面继续使用预签名 HTTPS 直达 MinIO/S3，不自研 TCP/UDP、TLS、QUIC 或私有加密。批量分片签名、服务端并发提示和 Rust 持久化传输队列继续由 `DC-006` 实现。

2026-07-16 的 `v0.4.0` 上线治理阶段已固定 MinIO Server/Client release 与 digest，接入 SBOM、Grype 和新增 Critical 阻断，并交付 `backup`、`backup-verify`、`restore` 自动化。manifest 从 15 个无 profile 默认服务的实际 Compose 容器记录 image ID，并把当前 `compose.windows.yml` SHA-256、Git commit、项目版本、S3 bucket、OpenSearch index 和 `DRIVE_TLS_CERT_NAME` lineage 名称作为精确恢复门禁；备份和恢复同时持有 project 与逐 physical volume mutex。备份根目录还会拒绝卷根、仓库目录/祖先及未预先使用 restricted ACL 的既有非空目录。真实随机 source/target Compose project 演练已验证 PostgreSQL、MinIO、Redis、OpenSearch、TLS、CMS 环境文件、API、Worker、beat、gateway 和宿主端口边界；备份失败会恢复 source 原运行、退出与健康状态，恢复失败会停止 target、删除新卷、清空原空卷，并从受限 ACL rollback archive 还原 `-ForceRestore` 前的原非空卷。

备份和恢复会自动把备份根目录、staging/正式备份、rollback archive 与最终 CMS 明文文件限制为当前用户、SYSTEM、Administrators，并在无网络、只读根文件系统、drop capabilities 的临时容器/卷中预解包扫描 tar。`-RestoreEnvironmentOutput` 必须是仓库和备份目录外的绝对新文件路径，父目录预先存在；CMS 明文只在本次恢复模式全部门禁成功的末尾通过同目录临时文件原子发布，发布竞态中的 foreign file 不会被失败清理删除。恢复提交后的 rollback archive 清理异常只报告维护失败并保留路径，不会再次清空或回滚已恢复卷。

剩余边界必须保持明确：Windows CMS 只加密 `.env.windows`，其余数据库、对象、索引、队列和 TLS 卷归档仍依赖 BitLocker、restricted NTFS ACL 与加密外部介质；SHA-256 只校验完整性，不认证制作者身份；Redis/OpenSearch 原始卷只支持相同 image reference/image ID、单节点同拓扑；`-ForceRestore` rollback 是尽力恢复，异常时受限 ACL 归档会保留并报告路径；当前 MinIO Server/Client 19/12 个 Critical 基线仍是上线风险。本阶段收尾门禁包括 Windows fake Docker/CMS smoke、真实备份恢复 integration、完整后端与部署检查、文档同步和 GitHub Actions 结果确认；随后恢复推进 MinIO multipart 稳定封装、高密级下载、多维配额和治理告警。

2026-07-01 代码审计发现的实现边界问题已完成首轮整改：浏览器认证改为 BFF + HttpOnly Cookie Session，移除 JWT/refresh token 兼容路径；对象存储默认实现已移除 `boto3/botocore` 并改用 MinIO Python SDK；Redis 固定窗口限流已改为 Lua 原子脚本。容量校准草稿已从 `stash@{0}: paused quota reconciliation draft` 恢复并整理为 `quota.reconcile_space_usage` 维护任务，worker 默认按批次和 cursor 扫完整个租户，修复模式会在已有账户上使用数据库行锁重算差额并限制返回明细体量；blob/object 垃圾回收已整理为 `file.cleanup_unreferenced_blobs` 维护任务；孤儿最终对象扫描已整理为 `file.cleanup_orphaned_objects` 维护任务，默认 dry-run，按对象存储游标扫描受控 `objects/{tenant_id}/{hash_prefix}/{sha256}` key，以 DB blob 元数据为事实来源清理对象复制成功但 DB 最终化失败后的无引用最终对象，并写入审计和 `orphan_object_cleanup_total` 指标。真实 MinIO 集成测试已接入 `backend-ci`，覆盖对象读写、copy、delete、list 游标、预签名下载、multipart 私有方法封装、预签名分片 PUT、complete 后 hash 校验和孤儿最终对象扫描。Sprint 4 权限系统已开始，`space_members` 用户成员基础表、创建空间 owner 成员写入、空间级 `PermissionService` 角色检查和 owner/admin 空间成员管理 API 已落地，节点 ACL 已支持用户、部门和用户组三类主体并接入文件列表、文件夹创建、上传初始化、multipart complete 和下载入口，文件列表已返回基于批量权限评估的子节点常用动作权限，空间成员和节点 ACL 变更已写入 `permission.changed` 事件，`permission.invalidate_cache` 已消费该事件并失效 Redis 权限缓存；搜索 ACL 已具备 token builder、独立 outbox event 和 search 队列入口，上传完成、重命名、移动、删除、恢复和彻底删除后的文件索引同步已接入 OpenSearch 适配，ACL 变更后可按 space 或 node 子树保守重建索引 token，`GET /api/v1/search` 已接入查询层 allow/deny token 过滤、签名 cursor 分页、HTML 编码 highlight、搜索限流和应用层 `read_meta` 二次权限校验。搜索全文抽取入口已落地，当前支持安全的小型 UTF-8 文本类文件、基于成熟开源库 `pypdf` 的 PDF 可复制正文抽取、基于成熟开源库 `python-docx` 的 DOCX 段落/表格抽取、基于成熟开源库 `python-pptx` 的 PPTX 文本框/表格抽取和基于成熟开源库 `openpyxl` 的 XLSX 单元格抽取，并刷新索引 `content`；分享模块已完成基础数据模型、迁移、服务层、创建/详情/撤销 HTTP API、外链访问入口和外链下载入口；预览基础链路已新增 `preview.render_requested` outbox event、`preview` 队列 worker、`preview_artifacts` 私有产物表和 `GET /api/v1/files/{node_id}/preview` 权限控制入口，当前使用 Pillow 生成图片 WebP 预览产物，通过 Poppler `pdftoppm` 生成 PDF 首页 WebP 预览，并通过 LibreOffice headless 将 Office 文档转换为 PDF 后复用 PDF/图片链路；`preview.dispatch_outbox` 已配置 Celery 软/硬超时、速率限制、结构化失败日志和 `preview_failures_total` 指标，`/metrics` 已暴露 Prometheus 文本指标，`docs/deployment-preview-worker.md` 已补充预览 Worker CPU、内存和临时磁盘配额说明。上传/下载链路下一步优先补齐企业级治理缺口：MinIO SDK multipart 私有方法的替换评估或稳定封装、真实对象存储异常恢复和升级兼容测试、用户/租户/策略化配额、维护任务调度告警和清理指标、高密级下载代理与 Range/审计/水印/DLP、同 hash 首次上传竞争测试；同时继续补充真实 LibreOffice 环境联调和图片 OCR 等搜索复杂格式抽取的成熟开源工具适配。
