# PROJECT_PLAN.md

本文件是《企业网盘开发者技术计划书.md》的执行版摘要。完整架构、数据模型、接口契约、安全策略和里程碑以技术计划书为准。

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
- 部署：应用和依赖服务可容器化，生产 Nginx 使用宿主机安装和管理。

## 3. 架构原则

- 一期采用模块化单体，不提前拆微服务。
- 分层路径为 `router -> service -> domain/policy -> repository -> db/infrastructure`。
- 模块之间通过 service 接口协作，禁止跨模块直接访问 repository。
- 领域事件统一通过 outbox 或任务队列投递。
- Redis、OpenSearch、对象存储都不是核心事实来源，核心事实以 PostgreSQL 为准。

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
- 企业级补强计划：当前上传/下载链路已具备主路径能力，但仍需补齐 MinIO SDK multipart 私有方法替换或稳定封装、同 hash 首次上传竞争的细粒度并发测试和恢复路径，以及真实对象存储集成测试。

### 上传下载企业级补强计划

上传/下载链路、秒传、multipart、服务端 hash 校验、容量账本和彻底删除容量释放是当前最重要的企业级主链路。现阶段已经形成基础闭环，但上线前必须继续按以下计划补强，避免把临时实现误当成企业级完成态：

- MinIO Python SDK multipart 当前在 `infrastructure` 适配层使用 `_create_multipart_upload`、`_complete_multipart_upload`、`_abort_multipart_upload` 私有方法。这不属于业务层随意自研，但 SDK 升级稳定性不够企业级；后续要评估公开 API、稳定开源 S3 兼容客户端、标准 HTTP/SigV4 适配，或至少补齐版本探测、窄封装和真实对象存储集成测试。
- 对象复制到最终 `objects/{tenant_id}/{hash_prefix}/{content_hash}` 成功但数据库最终化失败后，可能出现孤儿最终对象。当前已补 `file.cleanup_orphaned_objects` 反向扫描任务，但还需要继续补真实 MinIO 集成测试、生产调度、告警和运行指标，把它从可手动治理推进到可持续治理。
- 容量治理当前主要覆盖空间维度。后续必须补齐用户维度、租户维度和策略化配额，例如空间默认额度、用户个人额度、部门额度、文件密级或扩展名策略、临时上传占用上限和租户总池限制。
- 维护任务当前仍偏“可手动跑 / worker 可消费”。后续需要补齐定时调度、失败告警、清理吞吐指标和治理看板，至少覆盖过期上传、blob 清理、孤儿对象扫描、容量校准、过期分享和预览产物治理。
- 下载当前仍以短期预签名直连为主。高密级文件、外链和审计敏感场景需要补充后端代理下载、HTTP Range、增强审计、水印导出或 DLP 策略；低风险大文件仍可保留预签名直连以降低 API 带宽压力。
- 并发下同 hash 首次上传竞争当前主要依赖数据库唯一约束和补偿路径，已有基础处理，但还需要补更细的并发测试、对象归档幂等检查和失败恢复路径，确保不会产生错误引用、漏容量或孤儿最终对象。
- 真实对象存储集成测试仍不足，当前更多依赖内存适配器验证。必须补充 MinIO 或等价 S3 兼容服务的集成测试，覆盖 multipart 私有方法封装、预签名 PUT/GET、copy、delete、list、hash 校验、孤儿最终对象扫描和异常恢复。

### Sprint 4：权限系统

- 空间成员和角色。（已完成 `space_members` 用户成员基础表、创建空间 owner 成员写入、空间级成员角色检查和 owner/admin 成员管理 API）
- 目录 ACL、权限继承、拒绝优先。（已完成用户、部门、用户组三类节点 ACL 主体，管理 API、继承开关、deny 优先和文件/上传/下载关键入口校验）
- 权限缓存和失效事件。（已完成文件列表批量权限评估、`permission.changed` outbox 事件写入和 Redis 缓存失效 worker）
- 部门/用户组 ACL 主体。（已完成 `departments`、`department_members`、`user_groups`、`user_group_members` 事实表、repository 和权限判断主体展开）
- 搜索 ACL 事件、文件索引写入和查询过滤。（已完成 ACL token builder、`search.acl_rebuild_requested` outbox event、上传完成、重命名、移动、删除、恢复和彻底删除后的 `search.index_requested` 事件、OpenSearch 文件索引写入/删除入口、ACL 变更后的保守范围重建，上传完成后的 `search.extract_requested` 文本/PDF/DOCX/PPTX/XLSX 抽取入口，以及 `GET /api/v1/search` 查询层 allow/deny token 过滤、签名 cursor 分页、highlight、搜索限流和应用层二次权限校验）
- 高危操作二次查库。

### Sprint 5：分享、预览、搜索

- 内部分享和外链分享。（已完成基础表、迁移、服务层、创建/详情/撤销 HTTP API、带租户边界的外链访问入口和外链下载入口）
- 提取码、过期、次数限制、撤销。（已完成提取码哈希、过期/次数字段、撤销服务、外链访问次数原子扣减、外链下载次数原子扣减、IP 总量和 `token + IP` / `token + node + IP` 维度限流）
- 预览任务和搜索索引任务。（已完成搜索索引/抽取入口、图片 WebP 预览、PDF 首页 WebP 预览和 Office 通过 LibreOffice headless 转 PDF 的基础链路）
- 权限过滤与二次校验。

### Sprint 6：管理、治理、上线

- 管理 API、审计查询、统计。
- 生命周期治理、孤儿对象扫描和容量治理增强。
- 用户/租户维度配额和策略化配额；维护任务定时调度、失败告警、清理指标和运行看板。
- 高密级下载治理：在预签名直连之外补充后端代理、HTTP Range、增强审计、水印或 DLP 策略能力。
- Dockerfile、部署文档、宿主机 Nginx 配置说明。
- 发布、回滚和可观测性检查。

## 5. 当前下一步

2026-07-01 代码审计发现的实现边界问题已完成首轮整改：浏览器认证改为 BFF + HttpOnly Cookie Session，移除 JWT/refresh token 兼容路径；对象存储默认实现已移除 `boto3/botocore` 并改用 MinIO Python SDK；Redis 固定窗口限流已改为 Lua 原子脚本。容量校准草稿已从 `stash@{0}: paused quota reconciliation draft` 恢复并整理为 `quota.reconcile_space_usage` 维护任务，worker 默认按批次和 cursor 扫完整个租户，修复模式会在已有账户上使用数据库行锁重算差额并限制返回明细体量；blob/object 垃圾回收已整理为 `file.cleanup_unreferenced_blobs` 维护任务；孤儿最终对象扫描已整理为 `file.cleanup_orphaned_objects` 维护任务，默认 dry-run，按对象存储游标扫描受控 `objects/{tenant_id}/{hash_prefix}/{sha256}` key，以 DB blob 元数据为事实来源清理对象复制成功但 DB 最终化失败后的无引用最终对象，并写入审计和 `orphan_object_cleanup_total` 指标。Sprint 4 权限系统已开始，`space_members` 用户成员基础表、创建空间 owner 成员写入、空间级 `PermissionService` 角色检查和 owner/admin 空间成员管理 API 已落地，节点 ACL 已支持用户、部门和用户组三类主体并接入文件列表、文件夹创建、上传初始化、multipart complete 和下载入口，文件列表已返回基于批量权限评估的子节点常用动作权限，空间成员和节点 ACL 变更已写入 `permission.changed` 事件，`permission.invalidate_cache` 已消费该事件并失效 Redis 权限缓存；搜索 ACL 已具备 token builder、独立 outbox event 和 search 队列入口，上传完成、重命名、移动、删除、恢复和彻底删除后的文件索引同步已接入 OpenSearch 适配，ACL 变更后可按 space 或 node 子树保守重建索引 token，`GET /api/v1/search` 已接入查询层 allow/deny token 过滤、签名 cursor 分页、HTML 编码 highlight、搜索限流和应用层 `read_meta` 二次权限校验。搜索全文抽取入口已落地，当前支持安全的小型 UTF-8 文本类文件、基于成熟开源库 `pypdf` 的 PDF 可复制正文抽取、基于成熟开源库 `python-docx` 的 DOCX 段落/表格抽取、基于成熟开源库 `python-pptx` 的 PPTX 文本框/表格抽取和基于成熟开源库 `openpyxl` 的 XLSX 单元格抽取，并刷新索引 `content`；分享模块已完成基础数据模型、迁移、服务层、创建/详情/撤销 HTTP API、外链访问入口和外链下载入口；预览基础链路已新增 `preview.render_requested` outbox event、`preview` 队列 worker、`preview_artifacts` 私有产物表和 `GET /api/v1/files/{node_id}/preview` 权限控制入口，当前使用 Pillow 生成图片 WebP 预览产物，通过 Poppler `pdftoppm` 生成 PDF 首页 WebP 预览，并通过 LibreOffice headless 将 Office 文档转换为 PDF 后复用 PDF/图片链路；`preview.dispatch_outbox` 已配置 Celery 软/硬超时、速率限制、结构化失败日志和 `preview_failures_total` 指标，`/metrics` 已暴露 Prometheus 文本指标，`docs/deployment-preview-worker.md` 已补充预览 Worker CPU、内存和临时磁盘配额说明。上传/下载链路下一步优先补齐企业级治理缺口：真实对象存储集成测试、MinIO SDK multipart 私有方法的替换评估或稳定封装、用户/租户/策略化配额、维护任务调度告警和清理指标、高密级下载代理与 Range/审计/水印/DLP、同 hash 首次上传竞争测试；同时继续补充真实 LibreOffice 环境联调和图片 OCR 等搜索复杂格式抽取的成熟开源工具适配。
