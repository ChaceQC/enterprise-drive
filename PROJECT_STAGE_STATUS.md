# 项目阶段进度

更新时间：2026-08-03

## 1. 总体结论

当前项目处于 **后端 v0.4.0、Sprint 9 核心产品闭环阶段**：

- 后端核心能力、权限、分享、预览、搜索、Windows 11 Docker 部署和基础治理已经形成试点基础，Sprint 2 至 Sprint 5 已无剩余项。
- `BE-038` 内部分享接收端和 `BE-039` 通知/成员变化失效已经完成；下一项进入 `BE-044` 剩余空间管理和 `BE-045` 统计、维护、导出管理 API。
- Web 用户端和 Rust 桌面端尚未开工，身份治理、规模化治理和 `v1.0.0` 发布尚未完成。

## 2. 当前仓库快照

- 分支：`dev`
- Sprint 3 对象存储稳定性基线：`31a0de1`；配额、安全与性能收尾：`6465c5a`；CI 安全解析与下载达限修复：`404cc08`、`d8185a5`
- 项目版本：`0.4.0`
- Git tag：当前尚未建立 `v0.4.0` tag
- 运行时 OpenAPI：64 个路径、85 个操作
- 最新数据库迁移：`20260803_0020`
- 当前缺少目录：`frontend/`、`desktop/`
- 当前未实现：空间及统计/维护/导出管理 API、通用创建类幂等，以及大目录权限重算/治理页面

## 3. 各阶段进度

| 阶段 | 已完成 | 尚未完成 |
|---|---|---|
| Sprint 1：工程底座 | FastAPI、uv、配置、日志、错误处理、健康检查、指标、Tracing、PostgreSQL/Redis/MinIO/OpenSearch/Celery、Cookie Session、CSRF、CI | OIDC、LDAP、账号治理属于后续 Sprint 11 |
| Sprint 2：空间和文件树 | 空间、目录、列表、重命名、移动、删除/恢复/彻底删除、大目录后台任务、回收站分页、四类批量操作、批量幂等、`fail/keep_both/replace`、游标分页、基础审计 | 无 |
| Sprint 3：上传下载 | multipart、秒传、断点状态、complete/abort 幂等、预签名/代理/水印下载、服务端 SHA-256、最终对象归档、限流、多维容量账本、账户/策略管理 API、文件安全策略、关键字 DLP、清理任务、真实 MinIO CI、标准 S3 HTTP multipart 控制面、同 hash 并发解析、失败存储清理，以及 10,000 节点/100 万索引/1,000 万审计日志目标规模门禁 | 无 |
| Sprint 4：权限系统 | 空间成员和角色、用户/部门/用户组 ACL、继承、deny 优先、缓存失效、搜索 ACL 过滤、关键入口二次查权，以及用户/部门/用户组的 cursor 列表、详情、创建、更新、停用和成员管理 API | 无 |
| Sprint 5：分享、预览、搜索 | 内外部分享、创建者列表、“分享给我的”、接收人详情与 DTP/1 受控下载、通知已读/失效、部门/用户组授权重算、过期分享维护、图片/PDF/Office 预览、预览产物生命周期、OpenSearch ACL 过滤、图片/扫描 PDF OCR 和旧 Office/ODF 抽取 | 无 |
| Sprint 6：管理、治理、上线 | 管理员审计查询、用户/部门/用户组管理、配额账户/策略管理、文件安全策略管理、生命周期清理、指标与 Tracing、Windows 11 Docker Compose、Nginx、TLS/ACME、备份校验恢复、安全门禁 | 空间及统计/维护/导出管理 API、Alertmanager/Grafana 看板、生产 DNS/受信证书实测、周期恢复演练、备份轮换；正式 `v0.4.0` 发布标记 |
| Sprint 7：Rust 桌面基础 | 已固定 DTP/1 传输协议和后端传输基础 | 尚无桌面代码；设备会话、增量游标、tombstone、Rust/Tauri 工程均未开始 |
| Sprint 8：双向同步与桌面发布 | 尚未开始 | 双向同步、冲突副本、离线队列、签名安装包、更新回滚 |
| Sprint 9：核心产品闭环 | `BE-033` 至 `BE-039` 已完成；`BE-044` 的用户、部门、用户组和配额子集已完成 | `BE-044` 尚余空间管理，`BE-045` 尚余统计、维护和导出 |
| Sprint 10：Web 用户端与管理后台 | 尚未开始 | React/Vite、生成 API Client、用户端、管理后台、Playwright E2E |
| Sprint 11：身份与账号安全 | 已有本地登录、限流、CSRF、会话能力 | OIDC/OAuth、LDAP、密码管理、账号锁定、会话管理页面 |
| Sprint 12：规模化治理与内容能力 | 已有文件树大目录删除/恢复/彻底删除后台任务、过期分享与预览产物治理、图片/扫描 PDF OCR、旧 Office/ODF 抽取、指标和基础治理 | 大目录权限重算/治理页面、审计分区、Outbox DLQ、治理看板、故障注入和完整集成矩阵 |
| Sprint 13：稳定版发布 | 尚未开始 | UAT、压测、安全验收、升级回滚、统一版本、`v1.0.0`、发布包和验收报告 |

## 4. 已有验证证据

- 本轮推送前已确认的 GitHub Actions `backend-ci` 基线：运行 `30782429638`、提交 `d8185a5`，5 个 job 全部成功。
- 该 CI 后端门禁：`314 passed`；Ruff、格式检查、Bandit、依赖漏洞审计、Mypy、真实 PostgreSQL/MinIO、Windows 部署和 MinIO 供应链门禁均通过。
- Sprint 4 用户/组织管理集中定向首轮：`92 passed, 1 skipped, 1 failed`；唯一失败修复后只重跑该用例，结果 `1 passed`。
- Sprint 4 临时真实 PostgreSQL：空库升级到 `20260803_0019` 通过，双会话用户组版本竞争和双管理员并发停用保护分别 `1 passed`，临时容器均已删除。
- Sprint 4 静态验证：171 个源码文件 Mypy 通过，Ruff lint 和本轮 Python 文件格式检查通过；OpenAPI 58 个路径、79 个操作与安全矩阵精确对账。
- Sprint 5 集中定向验证覆盖内部分享、通知/授权重算、过期分享、预览生命周期、OCR/复杂格式边界和 Celery schedule；首次相关集合仅 1 个访问日志动作命名不一致，修复后只重跑该失败用例并通过。
- Sprint 5 静态验证：178 个源码文件 Mypy 通过，Ruff、Bandit、Alembic 离线 SQL、单一 migration head 和 Windows Compose 解析通过；运行时 OpenAPI 为 64 个路径、85 个操作，migration head 为 `20260803_0020`。
- 临时空 PostgreSQL 已从零升级到 `20260803_0020`，并确认分享授权/通知表及预览最后访问字段存在；内容处理 `preview` 镜像已成功构建并在构建阶段验证 Tesseract `eng`/`chi_sim` 语言包。
- CI 收尾修复：S3 multipart 外部 XML 改用 `defusedxml` 安全解析；外链下载在生成预签名 URL 或写入水印派生对象前原子占用下载次数，达限请求不再产生无效存储副作用。
- `BE-036` 定向验证：`3 passed`。
- `BE-037` 集中定向验证：`3 passed`；安全矩阵 `51 passed`；真实跨租户定向 `1 passed`。
- Sprint 2 剩余增强定向验证：冲突策略 `3 passed`、大目录 `2 passed`；与 schedule/安全矩阵/跨租户合并为 `61 passed`。
- `BE-035` 定向验证：`8 passed`。
- `BE-034` 定向验证：`6 passed`。
- `BE-029` 小规模真实 Docker smoke：170 个请求、0 失败。
- Sprint 3 配额管理定向：既有集中用例 `3 passed`；真实 PostgreSQL 乐观前置条件用例 `1 passed`；空库升级到 `20260803_0018` 通过。
- Sprint 3 文件安全与外链安全集中定向：8 passed；历史版本 DLP 与派生文件真实大小补充用例 2 passed。
- 路由安全矩阵覆盖当前 OpenAPI 的 64 个路径、85 个操作；新增 Sprint 5 路由已纳入匿名、CSRF、登录态和跨租户门禁。
- `BE-029` 目标规模：10,000 节点、100 万 OpenSearch 文档、1,000 万审计日志；最终 `upload_complete` 1,936 个样本、0 失败、58.364 RPS、API P95 790 ms，`report.json passed=true`。
- 性能清理：2,000/2,000 个准备节点已 purge，隔离 target 容器、卷和网络为 0。
- Windows 备份恢复的默认数据恢复和完整全栈恢复均已通过。
- 当前无运行中的容器。

## 5. 下一步顺序

1. 完成 `BE-044` 剩余的空间管理 API。
2. 完成 `BE-045` 统计、维护任务和导出管理 API。
3. 补齐其余正式发布门禁：生产 TLS/DNS、MinIO 风险治理和 `v0.4.0` 发布标记；Sprint 3 目标规模性能证据直接复用已通过工件。
4. 进入 Sprint 7/8，先实现桌面端依赖的设备会话与增量同步契约，再建立 Rust/Tauri 工程。
5. 进入 Sprint 10，建立 Web 用户端和管理后台。

## 6. 状态判断

当前项目已经超过“后端接口样例”阶段，具备完整后端主链路和可验证部署基础；但距离完整企业产品仍有明显工作量，主要缺口集中在：

- 空间管理和统计/维护/导出 API；
- 生产监控、备份治理和正式发布；
- Rust 桌面客户端；
- Web 用户端与管理后台；
- 企业身份、规模化治理和 `v1.0.0` 验收。
