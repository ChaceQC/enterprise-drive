# 项目阶段进度

更新时间：2026-08-03

## 1. 总体结论

当前项目处于 **v0.5.0、Sprint 7 桌面 Alpha 已完成 CI 收尾、等待正式发布门禁的阶段**：

- 后端核心能力、权限、分享、预览、搜索、完整管理 API、Windows 11 Docker 部署、监控 profile 和备份治理入口已经形成试点基础，Sprint 2 至 Sprint 6 代码侧剩余项为空。
- `BE-036` 至 `BE-039`、`BE-044` 和 `BE-045` 已完成，Sprint 9 核心产品能力闭环。
- Sprint 7 的 `DC-001` 至 `DC-006` 已完成并收尾：Rust/Tauri Windows 11 骨架、设备会话、增量游标/tombstone、SQLite 索引、DTP/1 单向传输、诊断导出和 CI 门禁均已落地；最终 Windows CI 已全绿。
- 真实生产 DNS/受信证书证据和 MinIO 修复镜像不在当前本机环境内，正式 `v0.4.0` tag/Release 保持阻塞；Sprint 8 双向同步、Web 用户端、身份治理、规模化治理和 `v1.0.0` 尚未完成。

## 2. 当前仓库快照

- 分支：`dev`
- Sprint 3 对象存储稳定性基线：`31a0de1`；配额、安全与性能收尾：`6465c5a`；CI 安全解析与下载达限修复：`404cc08`、`d8185a5`
- 项目版本：`0.5.0`
- Sprint 7 最终代码提交：`a57d3fb`
- Sprint 7 最终 CI：`backend-ci` run `30838990372`（8 个 job 全部成功）
- Git tag：当前尚未建立 `v0.4.0` tag
- 运行时 OpenAPI：80 个路径、107 个操作
- 最新数据库迁移：`20260803_0022`
- 当前缺少目录：`frontend/`
- 当前未实现：大目录权限重算/治理页面，以及 Sprint 8 的双向同步/冲突/签名更新

## 3. 各阶段进度

| 阶段 | 已完成 | 尚未完成 |
|---|---|---|
| Sprint 1：工程底座 | FastAPI、uv、配置、日志、错误处理、健康检查、指标、Tracing、PostgreSQL/Redis/MinIO/OpenSearch/Celery、Cookie Session、CSRF、CI | OIDC、LDAP、账号治理属于后续 Sprint 11 |
| Sprint 2：空间和文件树 | 空间、目录、列表、重命名、移动、删除/恢复/彻底删除、大目录后台任务、回收站分页、四类批量操作、批量幂等、`fail/keep_both/replace`、游标分页、基础审计 | 无 |
| Sprint 3：上传下载 | multipart、秒传、断点状态、complete/abort 幂等、预签名/代理/水印下载、服务端 SHA-256、最终对象归档、限流、多维容量账本、账户/策略管理 API、文件安全策略、关键字 DLP、清理任务、真实 MinIO CI、标准 S3 HTTP multipart 控制面、同 hash 并发解析、失败存储清理，以及 10,000 节点/100 万索引/1,000 万审计日志目标规模门禁 | 无 |
| Sprint 4：权限系统 | 空间成员和角色、用户/部门/用户组 ACL、继承、deny 优先、缓存失效、搜索 ACL 过滤、关键入口二次查权，以及用户/部门/用户组的 cursor 列表、详情、创建、更新、停用和成员管理 API | 无 |
| Sprint 5：分享、预览、搜索 | 内外部分享、创建者列表、“分享给我的”、接收人详情与 DTP/1 受控下载、通知已读/失效、部门/用户组授权重算、过期分享维护、图片/PDF/Office 预览、预览产物生命周期、OpenSearch ACL 过滤、图片/扫描 PDF OCR 和旧 Office/ODF 抽取 | 无 |
| Sprint 6：管理、治理、上线 | 审计、用户/部门/用户组/空间/配额/文件安全/统计/维护/导出管理 API；生命周期、指标、Tracing、Prometheus/Alertmanager/Grafana、Windows Compose、Nginx、TLS/ACME、备份校验/轮换/隔离演练和安全门禁 | 仅剩生产环境的真实 DNS/受信证书记录、MinIO 修复镜像和正式 `v0.4.0` 发布标记 |
| Sprint 7：Rust 桌面基础 | `DC-001` 至 `DC-006`：Cargo/Tauri 骨架、设备会话、增量游标/tombstone、Rust API client、SQLite 索引、DTP/1 队列、托盘、同步根和诊断导出；Windows CI 已全绿 | 无 |
| Sprint 8：双向同步与桌面发布 | 尚未开始 | 双向同步、冲突副本、离线队列、签名安装包、更新回滚 |
| Sprint 9：核心产品闭环 | `BE-036` 至 `BE-039`、`BE-044`、`BE-045` 已完成 | 无 |
| Sprint 10：Web 用户端与管理后台 | 尚未开始 | React/Vite、生成 API Client、用户端、管理后台、Playwright E2E |
| Sprint 11：身份与账号安全 | 已有本地登录、限流、CSRF、会话能力 | OIDC/OAuth、LDAP、密码管理、账号锁定、会话管理页面 |
| Sprint 12：规模化治理与内容能力 | 已有文件树大目录删除/恢复/彻底删除后台任务、过期分享与预览产物治理、图片/扫描 PDF OCR、旧 Office/ODF 抽取、指标和基础治理 | 大目录权限重算/治理页面、审计分区、Outbox DLQ、治理看板、故障注入和完整集成矩阵 |
| Sprint 13：稳定版发布 | 尚未开始 | UAT、压测、安全验收、升级回滚、统一版本、`v1.0.0`、发布包和验收报告 |

## 4. 已有验证证据

- Sprint 6 管理 API 基线：`backend/tests/test_admin_sprint6_management.py` 首轮 `3 passed`；后续只重跑受 CSV/事务边界修改影响的导出生命周期和两个新增 owner transfer/CSV 防护用例，结果 `3 passed`。
- Sprint 6 静态门禁：管理模块、admin Worker、migration、网关 smoke 和测试共 28 个文件 Ruff/format 通过；管理模块与 admin Worker 共 25 个源码文件 Mypy 通过。
- 临时空 PostgreSQL 已从零升级到单一 head `20260803_0021`，确认 `admin_jobs.parameters_json=jsonb`、`spaces.version NOT NULL` 和管理列表索引存在；临时容器已删除。
- Windows 治理脚本保持 ASCII、无 BOM、PowerShell 5.1 parser 通过；新增 smoke 验证 backup ID/checksum、保留轮换、restricted ACL 记录、随机隔离恢复 project、target 清理和公网 IP 分类。
- Prometheus `promtool`、Alertmanager `amtool`、Grafana dashboard JSON 和三镜像 healthcheck 命令均已验证；Compose 同时启用 `monitoring`/`tls-tools` 时仍只有 gateway 发布宿主端口。
- Nginx 本机/TLS 模板 `nginx -t` 通过；真实 raw HTTP smoke 验证未知 API/S3 Host 返回空连接、CL/TE 和重复 Content-Length 拒绝、API 413、storage streaming 与本机 `localhost:19000` 兼容。
- 运行时 OpenAPI 与安全矩阵已同步为 80 个路径、107 个操作；写操作 CSRF、设备认证和管理员/登录态读取门禁的既有定向集合已通过。
- Sprint 7 后端定向测试：`backend/tests/test_desktop_sprint7.py` 与 OpenAPI 契约测试合计 `5 passed`；Ruff/format 与 `uv lock --check` 通过。
- 空 PostgreSQL 已从零升级至 `20260803_0022`，并确认 `desktop_devices`、`device_sessions`、`client_operations`、`sync_changes` 四张 Sprint 7 表存在。
- Rust workspace 已通过 `cargo fmt --all --check`、`cargo metadata --locked --no-deps`；本机未安装 MSVC linker，Rust 编译、Clippy、cargo test、cargo-deny 和 NSIS 构建由 Windows CI 执行。
- 最终 `backend-ci` run `30838990372`（提交 `a57d3fb`）的 `rust-desktop`、`rust-dependency-policy`、`backend`、`windows-deployment`、`minio-image-policy`、两组 MinIO supply-chain 和 `windows-desktop-installer` 共 8 个 job 全部成功。
- Rust CI 失败项均按实际日志收敛：先修正 Clippy `too_many_arguments`、reqwest `query` feature，再将 Windows 不支持的 cargo-deny 容器 action 移到 Ubuntu；依赖策略最终 advisories、bans、licenses、sources 均通过。
- Sprint 7 的全绿 CI 验证提交为 `a57d3fb`；全绿后仅追加状态文档收尾，不改变该提交中已验证的代码与 CI 配置；未重复执行已通过的后端、MinIO、备份恢复或性能集合。
- 本轮推送前已确认的 GitHub Actions `backend-ci` 基线：运行 `30782429638`、提交 `d8185a5`，5 个 job 全部成功。
- 该 CI 后端门禁：`314 passed`；Ruff、格式检查、Bandit、依赖漏洞审计、Mypy、真实 PostgreSQL/MinIO、Windows 部署和 MinIO 供应链门禁均通过。
- Sprint 4 用户/组织管理集中定向首轮：`92 passed, 1 skipped, 1 failed`；唯一失败修复后只重跑该用例，结果 `1 passed`。
- Sprint 4 临时真实 PostgreSQL：空库升级到 `20260803_0019` 通过，双会话用户组版本竞争和双管理员并发停用保护分别 `1 passed`，临时容器均已删除。
- Sprint 4 静态验证：171 个源码文件 Mypy 通过，Ruff lint 和本轮 Python 文件格式检查通过；OpenAPI 58 个路径、79 个操作与安全矩阵精确对账。
- Sprint 5 集中定向验证覆盖内部分享、通知/授权重算、过期分享、预览生命周期、OCR/复杂格式边界和 Celery schedule；首次相关集合仅 1 个访问日志动作命名不一致，修复后只重跑该失败用例并通过。
- Sprint 5 静态验证：178 个源码文件 Mypy 通过，Ruff、Bandit、Alembic 离线 SQL、单一 migration head 和 Windows Compose 解析通过；当时运行时 OpenAPI 为 64 个路径、85 个操作，migration head 为 `20260803_0020`。
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
- 路由安全矩阵覆盖当前 OpenAPI 的 73 个路径、99 个操作；Sprint 6 管理路由已纳入匿名、CSRF、管理员和跨租户门禁。
- `BE-029` 目标规模：10,000 节点、100 万 OpenSearch 文档、1,000 万审计日志；最终 `upload_complete` 1,936 个样本、0 失败、58.364 RPS、API P95 790 ms，`report.json passed=true`。
- 性能清理：2,000/2,000 个准备节点已 purge，隔离 target 容器、卷和网络为 0。
- Windows 备份恢复的默认数据恢复和完整全栈恢复均已通过。
- 当前无运行中的容器。

## 5. 下一步顺序

1. Sprint 7 已完成，不再重复执行已通过的 Sprint 7 或无关测试。
2. 在真实生产网络执行 `tls-validate-public`，保存双域名 DNS、HTTP `308`、HTTPS readiness 和受信证书记录。
3. 采用受支持修复镜像或可审计补丁镜像解决 MinIO Critical，重新生成 SBOM/Grype 并运行真实 MinIO/备份恢复兼容门禁。
4. 上述发布阻塞解除后创建 `v0.4.0` tag/Release；Sprint 3 目标规模性能证据继续复用已通过工件。
5. 按计划进入 Sprint 8，建立双向同步、冲突处理和签名更新。

## 6. 状态判断

当前项目已经超过“后端接口样例”阶段，具备完整后端主链路、管理面和可验证部署/治理基础；但距离完整企业产品仍有明显工作量，主要缺口集中在：

- 生产 DNS/受信证书证据、MinIO 修复镜像和正式发布；
- Web 用户端与管理后台；
- 企业身份、规模化治理和 `v1.0.0` 验收。
