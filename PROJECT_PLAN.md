# PROJECT_PLAN.md

本文件是《企业网盘开发者技术计划书.md》的执行版摘要。完整架构、数据模型、接口契约、安全策略和里程碑以技术计划书为准。当前代码基线为 Sprint 11 / `0.8.0`，已完成后端主链路、Rust 桌面端、Web 用户端与管理后台、账号安全、OIDC 和 LDAP；下一产品阶段进入 Sprint 12 规模化治理。

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
- 桌面客户端：Rust stable、Cargo workspace、Tauri 2，Windows 11 优先；Sprint 7 和 Sprint 8 已交付设备会话、增量索引、双向同步、离线恢复、冲突处理、选择性同步、Windows 路径边界、系统凭据和签名更新/回退。
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
- 企业级补强计划：对象存储稳定性、同 hash 并发、配额账户/策略管理、下载自动选路、图片/PDF 水印、关键字 DLP 和目标规模性能门禁均已闭环；multipart 控制面使用 MinIO 公共预签名 API 和标准 S3 HTTP POST/DELETE，不再调用 SDK 私有方法。

### 上传下载企业级补强计划

上传/下载链路、秒传、multipart、服务端 hash 校验、容量账本和彻底删除容量释放是当前最重要的企业级主链路。2026-08-03 已按阶段表完成本节原有补强项；以下记录当前已落地结果及继续留在后续治理中的真实边界：

- MinIO multipart create/complete/abort 已改为 `S3MultipartControlClient`：通过公共 `get_presigned_url` 生成内部短期控制 URL，再发送标准 S3 HTTP POST/DELETE 和 XML 请求，不再依赖 `_create_multipart_upload`、`_complete_multipart_upload`、`_abort_multipart_upload`。依赖范围锁定为 `minio>=7.2.20,<8`，控制请求超时与 URL 有效期可配置；升级必须通过真实 MinIO 集成门禁。
- 对象复制到最终 `objects/{tenant_id}/{hash_prefix}/{content_hash}` 成功但数据库最终化失败后，可能出现孤儿最终对象。`file.cleanup_orphaned_objects` 反向扫描任务、`BE-031/BE-032` 的真实 MinIO 主路径及 `BE-035` 连续失败/stale 指标告警均已完成；Alertmanager 企业 webhook 路由和 Grafana overview/maintenance 看板已纳入可选 `monitoring` profile，实际 webhook 端点与值班流程由生产环境配置。
- `BE-033` 已补齐空间、可选用户、可选租户和文件策略四类容量账户，上传初始化执行快速检查，版本创建通过原子条件更新和统一 ledger 扣减，彻底删除按版本流水释放全部维度。系统管理员现可分页查询账户、创建或更新空间/租户/用户额度，并列表、创建、更新和停用策略；更新使用乐观前置条件且额度不得低于已用容量。部门额度、临时上传占用上限和多维通用校准继续后续治理。
- `BE-035` 已建立维护任务的 Redis 连续失败状态、结构化阈值告警、stale/时间戳 Gauge、通用任务结果计数和 Prometheus 规则文件；`file.process_tree_operations`、`share.expire_shares` 与 `preview.cleanup_artifacts` 均已接入同一健康状态。可选 `monitoring` profile 已补齐 Prometheus、Alertmanager webhook 路由和 Grafana overview/maintenance 看板，生产部署只需注入真实接收端并执行告警链路验收。
- `BE-034` 已在短期预签名直连之外补充内部受控代理下载、单段 HTTP Range、流式对象读取和范围审计。新增租户隔离的文件安全策略后，当前版本和历史版本可按扩展名/MIME 自动选择预签名、代理、水印或阻断，并执行关键字 DLP audit/block 与 fail-closed；内部图片/PDF 支持动态水印，公开外链支持预签名或水印派生对象，搜索正文已支持图片/扫描 PDF OCR。外链代理流、历史版本专用水印、legal hold 和高级内容分类继续 `GOV-001`。
- 同 hash 首次上传竞争已使用数据库 savepoint 解析唯一约束竞争：并发事务只创建一个 blob，后续事务复用并原子增加引用；真实 PostgreSQL 双会话测试确认 `1` 个 blob、`ref_count=2`。complete 响应丢失时会通过对象 stat 恢复结果，hash、归档或数据库最终化失败会最佳努力 abort multipart 并删除 `uploads/...` 临时对象，最终对象孤儿继续由既有反向扫描兜底。
- 真实对象存储集成测试已在 CI 和本机真实 Docker 中覆盖标准 HTTP multipart、预签名 PUT/GET、copy、delete、list、hash 校验和孤儿最终对象扫描；单元门禁覆盖 complete 成功但响应丢失后的 stat 恢复，以及不存在 upload 的幂等 abort。
- `BE-029` 目标门禁已覆盖 10,000 节点、100 万 OpenSearch 文档和 1,000 万审计日志；最终 target `upload_complete` 计入 1,936 个样本、0 失败，吞吐 `58.364 RPS`，不含对象存储合并的 API P95 `790 ms`，端到端 P95 `840 ms`，storage merge P95 `71 ms`，并清理 2,000/2,000 个准备节点。

### Sprint 4：权限系统

- 空间成员和角色。（已完成 `space_members` 用户成员基础表、创建空间 owner 成员写入、空间级成员角色检查和 owner/admin 成员管理 API）
- 目录 ACL、权限继承、拒绝优先。（已完成用户、部门、用户组三类节点 ACL 主体，管理 API、继承开关、deny 优先和文件/上传/下载关键入口校验）
- 权限缓存和失效事件。（已完成文件列表批量权限评估、`permission.changed` outbox 事件写入和 Redis 缓存失效 worker）
- 部门/用户组 ACL 主体。（已完成 `departments`、`department_members`、`user_groups`、`user_group_members` 事实表、repository 和权限判断主体展开）
- 用户、部门和用户组管理。（已完成系统管理员专用的 cursor 列表、筛选、详情、创建、更新、停用及部门/用户组成员管理；所有入口按租户隔离，写操作使用实体 `version` 前置条件并写入审计，用户停用会吊销有效会话，组织成员或状态变化会递增租户权限版本并触发租户级缓存失效）
- 搜索 ACL 事件、文件索引写入和查询过滤。（已完成 ACL token builder、`search.acl_rebuild_requested` outbox event、上传完成、重命名、移动、删除、恢复和彻底删除后的 `search.index_requested` 事件、OpenSearch 文件索引写入/删除入口、ACL 变更后的保守范围重建，上传完成后的 `search.extract_requested` 文本/PDF/DOCX/PPTX/XLSX 抽取入口，以及 `GET /api/v1/search` 查询层 allow/deny token 过滤、签名 cursor 分页、highlight、搜索限流和应用层二次权限校验）
- 高危操作二次查库。（已完成；权限读路径当前直接以 PostgreSQL 空间成员与 ACL 为事实来源，成员/ACL 管理、上传完成、下载、分享、预览和文件写操作均在对应接口重新调用权限服务）

### Sprint 5：分享、预览、搜索

- 内部分享和外链分享。（已完成基础表、迁移、服务层、创建/详情/撤销、创建者列表、“分享给我的”、接收人详情与 DTP/1 受控下载；部门/用户组接收人通过物化授权重算，撤销、过期或成员移除会同步失效授权和通知）
- 提取码、过期、次数限制、撤销。（已完成提取码哈希、过期/次数字段、内外部访问/下载次数原子扣减、撤销服务、过期分享周期任务、IP 总量和用户/分享/节点维度限流）
- 预览任务和搜索索引任务。（已完成搜索索引/抽取入口、图片 WebP 预览、PDF 首页 WebP 预览、Office 通过 LibreOffice headless 转 PDF、图片/扫描 PDF Tesseract OCR、旧 Office/ODF 转换抽取，以及旧版本产物与超期孤儿预览对象清理）
- 权限过滤与二次校验。（已完成；搜索查询同时执行 OpenSearch allow/deny token 过滤和 PostgreSQL `read_meta` 二次校验，分享、预览与下载在签发访问地址前重新检查当前权限）

### Sprint 6：管理、治理、上线

- 管理员审计查询 API。（已完成 `GET /api/v1/admin/audit-logs`，仅系统管理员可访问，按租户隔离，支持用户、资源、动作、结果、风险、请求 ID、时间范围和签名 cursor 筛选，并审计成功与拒绝查询）
- 用户、部门、用户组、空间、配额账户/策略、审计、统计、维护和导出管理 API 已完成；`BE-044`、`BE-045` 已闭环。
- 生命周期治理、孤儿对象扫描和容量治理增强。（`BE-026` 已完成过期上传、无引用 blob 和回收站保留期清理；回收站任务按删除批次根节点加锁清理，释放容量、扣减 blob 引用并写入审计、搜索事件和指标；完整策略化治理继续由 `BE-047` 承担）
- 多维配额核心运行时及账户/策略管理 API 已完成；部门/临时额度、通用校准和容量治理看板继续由后续管理治理提供。维护任务定时调度、连续失败告警和清理指标已由 `BE-035` 完成核心运行时。
- 高密级下载治理：后端流式代理、单段 HTTP Range、自动选路、图片/PDF 水印、关键字 DLP、图片/扫描 PDF OCR 和增强审计已完成；外链代理流、历史版本专用水印、legal hold 和高级内容分类继续后续交付。
- Windows 11 Docker Desktop 正式部署：多阶段 Dockerfile、根 `compose.windows.yml`、Compose 内 Nginx gateway、根 `.env.windows.example` 和 `deploy/windows/manage.ps1`。（已完成本机 HTTP、公网 ACME/TLS、续期、`tls-validate-public` 验收入口、可选 monitoring profile、`backup`/`backup-verify`/`restore`、备份轮换和周期恢复演练自动化；真实 DNS/受信证书记录待生产环境执行）
- API、migration、seed、MinIO 初始化、按队列隔离的 Worker、Celery beat、PostgreSQL、Redis、MinIO、OpenSearch 的完整编排；只有 gateway 发布宿主端口，默认 HTTP `18080/19000`，公网模式由 gateway 发布 `80/443` 并按 API/存储域名 Host 分流。（已完成）
- S3 容器内端点和浏览器外部端点分离；默认本机 API 为 `http://localhost:18080`、S3 外部端点为 `http://localhost:19000`，均由 gateway 发布；生产支持 API/存储独立域名的 Host 分流并保留原始 Host。（已完成）
- named volumes、真实 `/readyz` PostgreSQL 探针、Preview Worker 资源限制、定时维护任务和数据库连接池边界。（已完成）`v0.4.0` 阶段的代码侧已交付 PostgreSQL custom dump、MinIO/Redis/OpenSearch/TLS 停止状态卷归档、CMS 环境文件保护、当时 15 个默认服务实际容器 image ID 与精确 Compose/Git/版本/configuration lineage 门禁、project/逐物理卷 mutex、restricted ACL、隔离 tar 预扫描、`-ForceRestore` rollback archive、失败恢复、备份保留轮换、Windows 周期任务和随机隔离恢复演练；Sprint 10 加入 `web` 后当前门禁已同步为 16 个默认服务，离线介质、来源签名和完整包加密继续后续治理。
- Kubernetes、systemd 降为未来可选迁移方案，不作为当前交付目标。

### Sprint 7：Rust 桌面客户端基础（目标版本 `0.5.0`）

截至 2026-08-03，`DC-001` 至 `DC-006` 已完成：

- 已在 `desktop/` 建立 Cargo workspace 和 Tauri 2 桌面应用，Windows 11 作为首发平台。
- Rust crate 已按职责拆分为 API client、设备会话、服务端增量同步、SQLite 本地索引、DTP/1 传输队列、Windows 平台适配和脱敏诊断；界面层只消费状态和发送命令。
- 后端已新增桌面设备会话、设备列表与吊销、短期会话轮换；设备 token 只保存于 Windows Credential Manager，不写入 SQLite、普通配置文件或日志。
- 后端已新增按租户和用户隔离的增量变更游标、删除 tombstone、节点/版本前置条件和幂等客户端操作 ID，桌面端不通过高频全量目录轮询实现同步。
- `Drive Transfer Protocol v1` 已补齐并发提示、批量签名、分片确认、断点状态、整文件 SHA-256、Range 下载、幂等完成和取消。
- 桌面 Alpha 已提供登录、空间和目录浏览、上传/下载队列、暂停/继续/取消、任务栏托盘、同步目录选择、离线元数据浏览和错误诊断导出。
- CI 已增加 Rust fmt、Clippy、单元/集成测试、依赖许可证与漏洞门禁、release build 和 Windows NSIS 安装包构建。

### Sprint 8：Rust 双向同步与桌面发布

截至 2026-08-03，`DC-007` 至 `DC-010` 已完成：

- 已实现远端增量变更拉取、本地文件系统监听、SQLite 离线操作队列、进程重启恢复、网络恢复续传和有界指数退避。
- 下载先写同目录 `.drivepart`，只有版本、hash、持久化进度和实际长度一致时才续传，完成 SHA-256 后原子替换；上传复用现有 multipart、秒传、权限、审计、容量、限流和服务端 hash 校验，并支持既有节点安全创建新版本。
- 冲突默认保留双方内容并生成带设备名和 UTC 时间的冲突副本；双端同时修改、删除/修改、目录重命名/移动和目标路径占用都会形成 SQLite 冲突记录，原排队操作被终止，禁止随后覆盖远端结果。
- Windows 路径层已统一处理大小写折叠、保留设备名、尾随点/空格、Unicode NFC、长路径、符号链接和 reparse point；默认不跟随符号链接或 junction。
- 已支持选择性同步、带宽与并发限制、文件忽略规则、失败重试、逐文件状态和冲突诊断；虚拟盘占位文件与 Windows Cloud Files API 继续作为后续增强。
- 已新增 Ed25519 签名更新清单和包、SHA-256/目标平台/版本校验、暂存安装、健康标记和 watchdog 回退；CI 使用 GitHub Secrets 生成 Authenticode 签名安装包并校验证书指纹，仓库只保留公钥和公开证书。
- 验收已覆盖 10,000 文件初始索引、1 GiB 中断恢复状态、真实进程重启 Range 续传、离线编辑恢复、同文件双端并发修改、目录移动/重命名冲突、异常退出恢复、设备吊销停止同步和签名篡改/回退。

### Sprint 9：核心产品能力闭环（目标版本 `0.6.0`）

- 文件版本：版本列表、指定版本下载、回滚为新版本、版本审计和容量流水。（`BE-036` 已完成核心 API：签名 cursor、DTP/1 历史版本下载、当前版本前置条件、不可变回滚、多维配额和事件）
- 回收站与批量操作：回收站分页列表、批量删除、移动、恢复和彻底删除；批量结果逐项返回，所有写操作支持 `Idempotency-Key`。（`BE-037` 已完成核心 API、迁移、部分失败和幂等重放）
- 内部分享接收端：“分享给我的”、创建者分享列表、接收人详情与下载、部门/用户组成员变化后的授权重算、撤销和站内通知。（`BE-038`、`BE-039` 已完成）
- 管理 API：用户、部门、用户组、空间、配额、审计、统计、维护任务和导出，所有管理操作写审计并支持 cursor 分页。（`BE-044`、`BE-045` 已完成；异步维护/导出状态由 `admin_jobs` 持久化）
- 完成上述接口的 OpenAPI、迁移、权限、审计、并发、容量和端到端测试，为 Web 与桌面客户端提供稳定契约。

### Sprint 10：Web 用户端与管理后台（目标版本 `0.7.0`）

- 在 `frontend/` 建立 TypeScript + React + Vite 工程，生成并锁定 OpenAPI client，统一 API 错误、Cookie Session、CSRF、request_id 和权限枚举处理。（`FE-001`、`FE-002` 已完成；Sprint 10 当时归档为 83 paths / 110 operations / 132 schemas）
- 用户端覆盖登录、空间/目录、批量操作、上传队列、下载、搜索、预览、回收站、文件版本、分享创建、分享给我的、通知中心和账号基础页面。（`FE-003` 至 `FE-005` 已完成）
- 管理后台覆盖用户、部门、用户组、空间、配额、审计、统计、维护任务状态和导出；管理员路由与后端管理权限同时校验。（`FE-006`、`FE-007` 已完成）
- 构建产物通过 Compose 内部 Web 服务交给 gateway，同一 API 域名下使用 `/api/v1`，Web 服务不直接发布宿主端口。（`FE-009` 已完成：`web` 内部 `8080`，默认无 profile 服务 16 个，gateway 是唯一宿主端口发布者）
- CI 增加 lint、类型检查、单元测试、构建、OpenAPI breaking-change 检查和 Playwright E2E；验收覆盖 Chromium、Firefox、WebKit 和 Windows 常用缩放比例。（`FE-008`、`FE-009` 已完成；本地与远端受影响三引擎均为 `13 passed, 2 skipped`，最终 run `30893658311` 全绿）

### Sprint 11：身份与账号安全（目标版本 `0.8.0`）

- `BE-040` 已完成：保留既有 Redis IP/账号限流，新增用户行锁、失败时间窗口、阶梯延迟、可插拔验证码、持久临时锁定、`423 ACCOUNT_LOCKED`/`Retry-After`、管理员乐观解锁和成功/失败/锁定/解锁审计。
- `BE-041` 已完成：统一密码策略查询与校验，支持用户改密、管理员重置、首次登录强制改密、浏览器会话列表/本人吊销，以及浏览器和桌面设备全部会话吊销；改密成功后必须重新认证。
- `BE-042` 已完成：OIDC provider 管理/连接测试、Authorization Code + PKCE、一次性 state/nonce、issuer/JWKS/签名/claims 校验、账号绑定/解除、登录回调、opaque Cookie Session 和 RP-Initiated Logout；redirect path 使用配置 allowlist。
- `BE-043` 已完成：LDAP 目录源管理/连接测试、dry-run/full/incremental run、稳定 external ID 绑定、用户/部门/组和成员 claim、冲突记录、禁用/离职处理、最后超级管理员保护，以及离职后的浏览器/桌面会话吊销；`identity.sync_ldap` 进入 maintenance 队列。
- `FE-010` 已完成：登录页展示验证码与锁定时间，提供 OIDC provider 登录与回调；账号页支持密码策略/改密、强制改密、浏览器会话吊销和 OIDC 绑定管理。
- `FE-011` 已完成：管理后台提供账号解锁/密码重置、OIDC provider 创建/启停/连接测试、LDAP Source 创建/启停/连接测试、dry-run/full/incremental 同步、run 统计和冲突列表；secret 只显示是否已配置。
- migration head 已更新为 `20260804_0024`；运行时 OpenAPI 为 105 paths / 134 operations / 162 schemas。
- Sprint 11 本地门禁已通过：账号安全 4 项与受影响回归 12 项、OIDC/LDAP 10 项、route matrix 134 条路由及 6 项集合校验、前端三浏览器 12 场景均通过；Ruff/format、Mypy（223 个源码文件）、uv lock、frontend lint/typecheck/build/api:check、PostgreSQL `0024` 往返、Compose config、Cargo metadata 和 `git diff --check` 均通过。最终提交为 `e6b4f6d`，`backend-ci` run `30922718148` 成功：changes/backend 成功，7 个未受影响 job 按 scope 跳过；frontend 已在 run `30919983108` 成功，Rust/MinIO/Windows/安装包已在 run `30917345858` 成功。

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

2026-08-04 Sprint 11 的 `BE-040` 至 `BE-043`、`FE-010` 至 `FE-011` 已完成代码侧交付：项目版本统一为 `0.8.0`，新增账号锁定/解锁、密码策略与全会话治理、OIDC/OAuth 2.1 + PKCE、LDAP 只读目录同步和对应 Web 身份页面；migration head 为 `20260804_0024`。运行时 OpenAPI 归档、生成 client 与 route matrix 已精确对账为 105 个路径、134 个操作、162 个 schemas，本地相关门禁均已通过。最终提交 `e6b4f6d` 已推送，`backend-ci` run `30922718148` 成功；Sprint 11 远端门禁完成，下一步进入 Sprint 12，不重复执行未受影响的 Sprint 10、MinIO、备份恢复、性能和桌面历史集合。

2026-08-04 Sprint 10 的 `FE-001` 至 `FE-009` 已完成：新增 `frontend/` React/Vite/TypeScript 工程、锁定依赖与生成式 API client，统一 Cookie Session、CSRF、request_id、401 会话事件和错误恢复；用户端覆盖文件/批量/上传下载、搜索预览回收站、分享通知和公开分享，管理后台覆盖用户、组织、空间、配额、审计、统计、维护与导出。项目版本已统一为 `0.7.0`，OpenAPI 归档为 83 个路径、110 个操作、132 个 schemas；Compose 增加内部 `web:8080`，16 个无 profile 默认服务仍只由 gateway 发布宿主 `18080/19000`。提交 `8da1abe` 已推送到 `dev`，对应 `backend-ci` run `30893658311` 的 9 个 job 全部成功，Sprint 10 远端门禁完成；当前下一步进入 Sprint 11。

2026-08-04 已开始收敛 `backend-ci` 的重复执行：新增可测试的变更范围路由和同分支并发取消，backend、Rust、Windows 部署、安装包、MinIO 与依赖策略按受影响文件运行；Rust crate 源码/测试只进入 `rust-desktop`，Tauri UI/配置/图标/签名只进入安装包，Tauri `src-tauri` Rust 入口同时进入两者，CI workflow/router 与文档变更只保留 changes 路由校验。安装包 job 移除“任意 push 都执行”的兜底条件；Rust job 先执行 workspace tests，再以 `cargo clippy --workspace --all-targets --no-deps` 检查本地 crate。Cargo registry/git cache 和锁定 workspace `cargo fetch` 继续复用，手工 `workflow_dispatch` 保留完整门禁；每周定时任务继续覆盖 MinIO 与 Rust 依赖数据库漂移。

2026-08-04 Sprint 9 的功能范围此前已经由 `BE-036` 至 `BE-039`、`BE-044`、`BE-045` 实现，本轮补齐最后的版本与契约收尾：后端包、FastAPI/健康检查、Rust workspace、Tauri 安装包、更新器 User-Agent 和桌面 OpenAPI 契约统一到目标版本 `0.6.0`，并新增跨后端/桌面清单的一致性测试。提交 `d31eaaa` 已推送到 `dev`，对应 `backend-ci` run `30872900207` 的 8 个 job 全部成功，Sprint 9 远端门禁完成；其后 Sprint 10 已由上方最新记录完成代码侧交付。真实 DNS、MinIO 修复镜像和正式 `v0.4.0` 发布门禁继续保持。

2026-08-03 Sprint 8 的 `DC-007` 至 `DC-010` 已完成实现和本地专项验收：项目版本保持 `0.5.0`，运行时 OpenAPI 为 80 个路径、107 个操作，migration head 为 `20260803_0023`；桌面端已形成文件监听、双向同步、离线队列、冲突副本、选择性同步、Windows 路径边界、逐文件诊断、签名更新和回退闭环，后端支持既有节点版本化上传。当前下一步是以本次 `dev` 推送的 `backend-ci` 全绿完成远端门禁，然后进入 Sprint 10 Web 用户端与管理后台；真实 DNS、MinIO 修复镜像和正式 `v0.4.0` 发布门禁继续保持。

2026-08-03 Sprint 5 剩余项已完成：新增创建者分享列表、“分享给我的”、接收人详情与 DTP/1 下载、`share_recipient_grants` 物化授权、部门/用户组成员变化后的异步重算、站内通知列表/已读/失效、过期分享维护任务；预览产物记录最后访问时间，并周期清理旧版本产物和超期孤儿对象；搜索 Worker 接入 Tesseract 图片/扫描 PDF OCR 和 LibreOffice 旧 Office/ODF 转换抽取，使用内容处理镜像、独立 tmpfs 和子进程回收边界。当时运行时 OpenAPI 为 64 个路径、85 个操作，migration head 为 `20260803_0020`；该阶段记录的下一项是 `BE-044` 剩余空间管理和 `BE-045` 统计、维护、导出管理 API，现已由上方 Sprint 6 记录闭环。

2026-08-03 Sprint 4 原剩余的用户、部门和用户组管理 API 已完成：新增 21 个系统管理员操作，覆盖三类实体的 cursor 列表、详情、创建、更新、停用及部门/用户组成员增删；所有入口按租户隔离，写操作使用实体 `version` 乐观前置条件、写入审计并联动会话或租户权限版本。当时运行时 OpenAPI 为 58 个路径、79 个操作，migration head 为 `20260803_0019`；当时 `BE-044` 只完成用户、组织和配额子集，空间管理现已由上方 Sprint 6 记录闭环，`BE-038`、`BE-039` 也已由 Sprint 5 完成。

2026-08-02 `BE-037` 回收站与批量文件操作已实现：回收站按 `deleted_at/id` 签名 cursor 仅列删除批次根节点；批量删除、移动、恢复和彻底删除最多处理 100 项，每项使用 savepoint 并逐项返回结果。新增 `file_batch_operations` 与 `20260801_0015` migration，按租户、用户、操作和 key hash 保存请求 hash/最终响应；同请求重放、异请求冲突。其后的 `BE-038`、`BE-039` 已完成。

2026-08-02 Sprint 2 剩余增强已完成：文件树同名冲突支持 `fail/keep_both/replace`；大目录删除、恢复和彻底删除使用 `20260802_0016`、`file_tree_operations`、`deleted_root_id`、状态/重试 API 和 `file.process_tree_operations` 分批执行，任务中断后可从 PostgreSQL 状态继续。其后已按顺序完成 `BE-038`、`BE-039`。

2026-08-01 `BE-036` 文件版本核心 API 已实现：版本列表按 `created_at/id` 使用服务端签名 cursor 分页并标记当前版本；指定历史版本下载复用 DTP/1、下载权限和预签名限流；回滚在节点行锁内校验可选 `expected_current_version_id`，复用原 blob 创建递增新版本，原子增加引用、扣减多维配额、更新当前版本，并写入审计、搜索索引/抽取和预览事件。后续已进入并完成 `BE-037`。

2026-08-01 `BE-035` 维护任务监控核心运行时已实现：现有 Celery beat 继续调度五个 maintenance 任务，Celery signal 在每次结束后把连续失败和最近成功/失败时间原子写入 Redis；maintenance Worker 暴露连续失败、alert、stale、时间戳和任务结果计数，达到阈值时写结构化错误日志，并提供可加载的 Prometheus 规则文件。下一项进入 `BE-036` 文件版本列表、指定版本下载与回滚。

2026-08-01 `BE-034` 内部受控下载核心运行时已实现：新增 `GET /api/v1/files/{node_id}/content`，复用现有节点权限、版本和 blob 校验，通过对象存储适配器按 offset/length 分块流式读取，支持完整响应和单段 HTTP Range，并在审计中记录代理模式、范围和响应字节数。2026-08-03 又完成文件安全策略自动选路、图片/PDF 水印、关键字 DLP 和外链水印派生对象；外链代理流、历史版本专用水印和复杂内容识别继续后续治理。

2026-08-01 `BE-033` 多维配额核心运行时已完成：新增 `quota_policies` 事实表；空间账户始终参与扣减，用户/租户默认额度大于 `0` 时启用对应账户，策略可按扩展名或 MIME 前缀限制累计额度和单文件大小；秒传和 multipart complete 在同一事务内按固定顺序执行原子扣减并写入各维度 ledger，彻底删除与回收站保留期清理按版本正向流水释放全部维度。2026-08-03 已补齐管理员账户/策略 HTTP API、租户隔离、乐观前置条件和额度不得低于已用容量；部门/临时额度及通用多维校准继续后续治理。

2026-08-01 `BE-029` multipart/report smoke 已通过真实隔离 Compose；2026-08-03 已完成目标规模收尾。报告环境确认 10,000 fixture 节点、100 万 OpenSearch 文档和 1,000 万审计日志；显式 warm-up 5 秒后统计重置，target `upload_complete` 计入 1,936 个 complete、0 失败，吞吐 `58.364 RPS`，storage merge P95 `71 ms`，扣除 merge 的 complete API P95 `790 ms`，端到端 P95 `840 ms`，`report.json passed=true`。2,000 个准备节点已全部 purge，隔离 project 的容器、卷和网络均清理为 `0`。

2026-07-31 已完成 `BE-026` lifecycle cleanup jobs：现有 `upload.expire_sessions` 和 `file.cleanup_unreferenced_blobs` 加上新增 `file.cleanup_expired_trash` 已覆盖原验收中的过期上传、blob 清理和回收站清理。新增任务按删除批次根节点扫描并锁定子树，删除版本和节点、释放容量、扣减 blob 引用、写入搜索删除事件与系统审计；迁移 head 更新为 `20260731_0013`，Celery beat、Windows Compose 环境、Prometheus 指标、SQLite 回归测试和真实 PostgreSQL Docker 集成测试均已同步。随后已按编号完成 `BE-027` metrics/tracing 和 `BE-028` Windows Docker Compose 正式部署门禁。

2026-07-31 本机 Docker Desktop 已重新安装并恢复 `desktop-linux`：Docker client/server `29.6.2`、Linux `amd64` daemon 和 Docker Compose `v5.3.1` 可用；`compose.windows.yml` 使用 `.env.windows.example` 静态校验通过并解析出 15 个默认服务。Nginx、Certbot、PostgreSQL、Redis、MinIO Server/Client、OpenSearch、runtime 和 preview 镜像均已独立准备；runtime/preview 分别在 `1 CPU / 2 GiB` 和 `1 CPU / 3 GiB` BuildKit 上限下构建完成，本地镜像没有重复 image ID。当前没有运行中或残留容器。

2026-07-31 `BE-028` 已完成。首次备份恢复测试暴露旧入口把镜像构建、15 服务启动、备份、重复成功校验和恢复串成黑盒任务，且辅助容器缺少资源边界；现已把拉取、构建、启动和恢复测试拆分，普通 `manage.ps1 up` 固定 `--no-build --pull never`，备份 helper 默认限制 `0.50 CPU / 512m / 128 PIDs`、禁用额外 swap，gzip/`pg_dump` 默认压缩等级为 `1`。真实 integration 提供 `-PreflightOnly`、`COMPOSE_PARALLEL_LIMIT=1`、Worker concurrency `1`、分阶段耗时、默认数据服务恢复和显式 `-FullStackRestore`，失败时在清理前输出异常容器状态与尾部日志。OpenSearch 测试专用容器上限从不稳定的 `1024m` 调整为 `1280m`，正式默认仍为 `3g`。默认恢复和完整 target 全栈恢复分别在 `409.6s`、`357.3s` 内通过，完整栈采样峰值为 `123.5%` aggregate Docker CPU 和 `2226 MiB` 容器内存，结束后容器均为 `0`；GitHub Actions run `30648296028` 全部成功。

2026-07-31 `BE-029` 现状审计、第一版工具链和真实 Docker smoke 已落地：原仓库没有 benchmark/load-test 文件、Locust/k6/pytest-benchmark 依赖或 CI 性能门禁。新增 `backend/performance/`，使用仅 dev 依赖的 Locust，提供 `smoke`（100 个 fixture 子目录、2 用户、20 秒）、`baseline`（1,000、10 用户、60 秒）和显式 `target`（10,000、50 用户、300 秒）三档；fixture 使用单一随机根目录承载全部子目录，清理时先软删整棵子树再一次 purge，上传初始化继续使用稳定父目录，避免已取消会话外键阻塞清理。runner 捕获 Locust stdout/stderr，输出真实的 `stats_stats.csv`、history/failures/exceptions CSV、HTML 和可审计 `report.json`；OpenSearch 索引尚未创建时搜索返回空结果，其他 404 继续抛出。新增 `performance.target_data`，按专属 index/action 分阶段生成 100 万 OpenSearch 文档和 1,000 万审计日志，使用确定性 ID、批次 checkpoint、显式大规模确认和只清理自身数据的恢复/清理路径。2026-08-01 又以本地固定镜像和资源受限的 PostgreSQL/OpenSearch 容器完成 `100/100` 暂停、恢复到 `1,000/1,000`、精确清理到审计 `0`/index `404` 的真实闭环，并把 CLI 默认值收紧为每次 1 批、显式 `0` 才不限批次。隔离真实 Compose smoke 共执行 170 次请求、0 失败，文件列表/初始化上传/搜索/审计 P95 分别为 32/92/71/25 ms，报告 `passed=true`；峰值为 6 个容器、162% aggregate Docker CPU 和 1506.1 MiB 容器内存，fixture、容器、网络、卷和端口全部清理。首版覆盖登录、Cookie Session `/auth/me`、文件列表批量权限评估、DTP/1 `uploads/init`、搜索和管理员审计分页；真实 multipart complete 压测、100 万/1,000 万目标数据实际灌入和完整 target profile 验收仍未完成，不能把小闭环或 smoke 结果当作目标规模验收。

2026-07-31 `BE-030` 首轮安全测试修复已通过提交 `25acecf` 和 GitHub Actions run `30660034411` 闭环：对当前虚拟环境 123 个实际包的审计发现 20 条记录全部来自攻击者可达的图片预览依赖 `Pillow 12.2.0`，已升级并锁定 `Pillow 12.3.0`；加入项目内 `bandit` 与 `pip-audit` dev 依赖和 CI 门禁，升级后审计 145 个环境包为 0 已知漏洞，Bandit 中危/高危为 0。登录新增来源 IP 与账号哈希双维 Redis 固定窗口，不存在租户/用户时仍执行 Argon2id dummy verify；422 校验错误不再回显原始 `input`。随后 production `Settings` 应用内 fail-fast 已通过提交 `a52b4ce` 和 GitHub Actions run `30661668693` 闭环：API、Worker、beat、migration 和 seed 会拒绝示例/过短 secret、无强密码连接 URL、关闭限流、Wildcard Trusted Hosts 及不安全公网 CORS/S3/Cookie 配置，同时保留纯 localhost/回环 HTTP 基线；完整后端门禁为 `188 passed, 4 skipped`，受限 runtime 镜像和真实 PostgreSQL/认证 Redis/API/Worker Docker smoke 均已通过并彻底清理。2026-08-01 已继续完成 route 身份/租户、撤权、恶意文件、Range、预签名 URL、外链穷举、Host/CORS 和真实 Nginx 原始 HTTP 门禁，`BE-030` 进入提交与远端 CI 收尾。

2026-07-31 已把此前仅停留在接口示例、技术建议或“后续接入”的能力补成 Sprint 9 至 Sprint 13、工程任务和远期 Backlog。2026-08-03 Sprint 6 和 Sprint 9 的代码侧能力已完成；正式 `v0.4.0` 仍需生产 DNS/受信证书记录和 MinIO 修复镜像门禁。当前并行顺序为：外部发布门禁不伪造完成，同时开始桌面端依赖的设备会话与增量同步契约；随后推进 Sprint 7/8 Rust 桌面端、Web 用户端与管理后台、身份安全、规模治理和 `v1.0.0` 稳定发布。Web 页面不得反向定义后端业务规则。

2026-07-31 已把 Rust 桌面客户端从笼统的二期增强项提升为 Sprint 7 和 Sprint 8 正式路线。当时仓库仍没有桌面客户端代码；其后已按 `0.5.0` 目标完成 Sprint 7 的架构 ADR、后端设备会话/增量同步契约、Rust API client、本地索引和单向传输，下一阶段进入双向同步、冲突处理和签名发布；正式发布仍不得绕过 MinIO 风险门禁。

2026-07-31 已正式启用 `Drive Transfer Protocol v1`（线协议标识 `DTP/1`）：新增 `docs/drive-transfer-protocol-v1.md`，上传、文件下载和外链下载公开可选 `X-Drive-Transfer-Protocol` 协商头，未知版本返回 HTTP 426，全部传输响应返回 `protocol_version=DTP/1`。协议自定义的是 HTTPS 之上的分片、断点、校验、幂等和错误状态机，数据面继续使用预签名 HTTPS 直达 MinIO/S3，不自研 TCP/UDP、TLS、QUIC 或私有加密。批量分片签名、服务端并发提示和 Rust 持久化传输队列继续由 `DC-006` 实现。

2026-07-16 的 `v0.4.0` 上线治理阶段已固定 MinIO Server/Client release 与 digest，接入 SBOM、Grype 和新增 Critical 阻断，并交付 `backup`、`backup-verify`、`restore` 自动化。manifest 从 15 个无 profile 默认服务的实际 Compose 容器记录 image ID，并把当前 `compose.windows.yml` SHA-256、Git commit、项目版本、S3 bucket、OpenSearch index 和 `DRIVE_TLS_CERT_NAME` lineage 名称作为精确恢复门禁；备份和恢复同时持有 project 与逐 physical volume mutex。备份根目录还会拒绝卷根、仓库目录/祖先及未预先使用 restricted ACL 的既有非空目录。真实随机 source/target Compose project 演练已验证 PostgreSQL、MinIO、Redis、OpenSearch、TLS、CMS 环境文件、API、Worker、beat、gateway 和宿主端口边界；备份失败会恢复 source 原运行、退出与健康状态，恢复失败会停止 target、删除新卷、清空原空卷，并从受限 ACL rollback archive 还原 `-ForceRestore` 前的原非空卷。

备份和恢复会自动把备份根目录、staging/正式备份、rollback archive 与最终 CMS 明文文件限制为当前用户、SYSTEM、Administrators，并在无网络、只读根文件系统、drop capabilities 的临时容器/卷中预解包扫描 tar。`-RestoreEnvironmentOutput` 必须是仓库和备份目录外的绝对新文件路径，父目录预先存在；CMS 明文只在本次恢复模式全部门禁成功的末尾通过同目录临时文件原子发布，发布竞态中的 foreign file 不会被失败清理删除。恢复提交后的 rollback archive 清理异常只报告维护失败并保留路径，不会再次清空或回滚已恢复卷。

剩余边界必须保持明确：Windows CMS 只加密 `.env.windows`，其余数据库、对象、索引、队列和 TLS 卷归档仍依赖 BitLocker、restricted NTFS ACL 与加密外部介质；SHA-256 只校验完整性，不认证制作者身份；Redis/OpenSearch 原始卷只支持相同 image reference/image ID、单节点同拓扑；`-ForceRestore` rollback 是尽力恢复，异常时受限 ACL 归档会保留并报告路径。2026-08-03 扫描复核把 MinIO Server/Client Critical 唯一 ID 允许集收紧为 16/9，其中两个 MinIO 自身 Critical 在固定社区镜像中没有 patched version；当前配置关闭 OIDC/LDAP/Console 只属于可达性缓解。正式 `v0.4.0` tag/Release 在受支持修复镜像或可审计补丁镜像替换、SBOM/Grype 重扫和真实 MinIO/备份恢复兼容性验证前保持阻塞，详见 `docs/minio-security-risk.md`。

2026-07-01 代码审计发现的实现边界问题已完成首轮整改：浏览器认证改为 BFF + HttpOnly Cookie Session，移除 JWT/refresh token 兼容路径；对象存储默认实现已移除 `boto3/botocore` 并改用 MinIO Python SDK；Redis 固定窗口限流已改为 Lua 原子脚本。容量校准草稿已从 `stash@{0}: paused quota reconciliation draft` 恢复并整理为 `quota.reconcile_space_usage` 维护任务，worker 默认按批次和 cursor 扫完整个租户，修复模式会在已有账户上使用数据库行锁重算差额并限制返回明细体量；blob/object 垃圾回收已整理为 `file.cleanup_unreferenced_blobs` 维护任务；孤儿最终对象扫描已整理为 `file.cleanup_orphaned_objects` 维护任务，默认 dry-run，按对象存储游标扫描受控 `objects/{tenant_id}/{hash_prefix}/{sha256}` key，以 DB blob 元数据为事实来源清理对象复制成功但 DB 最终化失败后的无引用最终对象，并写入审计和 `orphan_object_cleanup_total` 指标。真实 MinIO 集成测试已接入 `backend-ci`，覆盖对象读写、copy、delete、list 游标、预签名下载、multipart 私有方法封装、预签名分片 PUT、complete 后 hash 校验和孤儿最终对象扫描。Sprint 4 权限系统已开始，`space_members` 用户成员基础表、创建空间 owner 成员写入、空间级 `PermissionService` 角色检查和 owner/admin 空间成员管理 API 已落地，节点 ACL 已支持用户、部门和用户组三类主体并接入文件列表、文件夹创建、上传初始化、multipart complete 和下载入口，文件列表已返回基于批量权限评估的子节点常用动作权限，空间成员和节点 ACL 变更已写入 `permission.changed` 事件，`permission.invalidate_cache` 已消费该事件并失效 Redis 权限缓存；搜索 ACL 已具备 token builder、独立 outbox event 和 search 队列入口，上传完成、重命名、移动、删除、恢复和彻底删除后的文件索引同步已接入 OpenSearch 适配，ACL 变更后可按 space 或 node 子树保守重建索引 token，`GET /api/v1/search` 已接入查询层 allow/deny token 过滤、签名 cursor 分页、HTML 编码 highlight、搜索限流和应用层 `read_meta` 二次权限校验。搜索全文抽取入口已落地，当前支持安全的小型 UTF-8 文本类文件、基于成熟开源库 `pypdf` 的 PDF 可复制正文抽取、基于成熟开源库 `python-docx` 的 DOCX 段落/表格抽取、基于成熟开源库 `python-pptx` 的 PPTX 文本框/表格抽取和基于成熟开源库 `openpyxl` 的 XLSX 单元格抽取，并刷新索引 `content`；分享模块已完成基础数据模型、迁移、服务层、创建/详情/撤销 HTTP API、外链访问入口和外链下载入口；预览基础链路已新增 `preview.render_requested` outbox event、`preview` 队列 worker、`preview_artifacts` 私有产物表和 `GET /api/v1/files/{node_id}/preview` 权限控制入口，当前使用 Pillow 生成图片 WebP 预览产物，通过 Poppler `pdftoppm` 生成 PDF 首页 WebP 预览，并通过 LibreOffice headless 将 Office 文档转换为 PDF 后复用 PDF/图片链路；`preview.dispatch_outbox` 已配置 Celery 软/硬超时、速率限制、结构化失败日志和 `preview_failures_total` 指标，`/metrics` 已暴露 Prometheus 文本指标，`docs/deployment-preview-worker.md` 已补充预览 Worker CPU、内存和临时磁盘配额说明。上传/下载链路下一步优先补齐企业级治理缺口：MinIO SDK multipart 私有方法的替换评估或稳定封装、真实对象存储异常恢复和升级兼容测试、用户/租户/策略化配额、维护任务调度告警和清理指标、高密级下载代理与 Range/审计/水印/DLP、同 hash 首次上传竞争测试；同时继续补充真实 LibreOffice 环境联调和图片 OCR 等搜索复杂格式抽取的成熟开源工具适配。
