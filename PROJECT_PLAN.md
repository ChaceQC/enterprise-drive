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
- 用户登录、JWT、基础用户表和管理员 seed。
- CI：ruff、mypy、pytest。

### Sprint 2：空间和文件树

- space、node、file_blob、file_version model 和 migration。（已完成基础骨架）
- 空间创建、文件夹创建、文件列表。（已完成最小 API）
- 重命名、移动、删除到回收站。
- 同目录重名策略和 cursor pagination。（已完成基础约束和签名游标）
- 基础审计日志。

### Sprint 3：上传下载

- upload_session、multipart presign、complete、abort。
- 秒传、对象存储适配、容量初版。
- 下载预签名 URL。
- 上传下载审计。

### Sprint 4：权限系统

- 空间成员和角色。
- 目录 ACL、权限继承、拒绝优先。
- 权限缓存和失效事件。
- 高危操作二次查库。

### Sprint 5：分享、预览、搜索

- 内部分享和外链分享。
- 提取码、过期、次数限制、撤销。
- 预览任务和搜索索引任务。
- 权限过滤与二次校验。

### Sprint 6：管理、治理、上线

- 管理 API、审计查询、统计。
- 生命周期清理、容量校准。
- Dockerfile、部署文档、宿主机 Nginx 配置说明。
- 发布、回滚和可观测性检查。

## 5. 当前下一步

继续推进 Sprint 2：补充文件树重命名、移动、删除到回收站和恢复能力，并将临时“空间拥有者访问”边界逐步替换为 Sprint 4 权限系统前可复用的权限策略入口。
