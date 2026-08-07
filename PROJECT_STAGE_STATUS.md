# 项目阶段状态

更新时间：2026-08-07

## 1. 统计口径

本文件的“已完成”只依据当前工作区中的实际源码、运行时 OpenAPI、数据库迁移、测试代码、Compose 配置、Rust workspace 和前端工程判断。

- 阶段名称只用于归类，不把计划文字当作实现证据。
- CI 结果只作为验证证据，不作为项目功能清单。
- “代码侧完成”与“生产环境验收完成”分开记录。

## 2. 当前代码基线

| 项目 | 当前实际状态 |
|---|---|
| 分支 | `dev` |
| 候选功能代码 | `a5e44af`（本轮 `upload_init` 单次 blob 查询优化、CI 导入兼容修复与 Sprint 13 文档收口；backend CI run `31135045950` 全绿） |
| 当前对象存储变更 | 正式运行时已从 MinIO 替换为 SeaweedFS `4.40`；提交、push、远端 backend/Windows/image-policy/supply-chain 门禁均已完成 |
| 工作区 | Sprint 13 对象存储替换已完成本地直接验证、Windows 备份恢复兼容、远端门禁及当前 Windows 候选工件复验；`upload_init` 代码侧已完成最小查询优化；生产环境验收仍待外部执行 |
| 后端、前端、Rust、Tauri 版本 | `1.0.0` 候选 |
| 运行时 OpenAPI | 116 个路径、148 个操作、178 个 Schema |
| 数据库迁移 head | `20260804_0026` |
| Compose 服务 | 默认 16 个；启用全部 profile 后 20 个 |
| 宿主端口 | 由 gateway 提供 API/Web `18080` 和 S3 `19000` |
| Rust workspace | 9 个 package |
| Web 前端 | React/Vite/TypeScript，包含用户端和管理后台 |
| Git tag | 当前尚未建立 `v1.0.0` |

## 3. Sprint 1—12 实际代码状态

| 阶段 | 状态 | 实际代码已具备 | 仍需保留的缺口 |
|---|---|---|---|
| Sprint 1：工程底座 | 代码完成 | FastAPI、配置、日志、错误协议、健康检查、指标、Tracing、SQLAlchemy、Alembic、Redis、Celery、Session、CSRF | 核心范围无明显缺口 |
| Sprint 2：空间和文件树 | 代码完成 | 空间、文件夹、列表、重命名、移动、回收站、彻底删除、批量操作、批量幂等、大目录后台任务、操作重试 | 核心范围无明显缺口 |
| Sprint 3：上传下载 | 主链路完成 | 秒传、multipart、分片确认、断点、SHA-256、配额、标准 S3 multipart、预签名/代理/Range/水印下载、DLP、对象清理 | 部门配额、临时上传占用额度、外链代理流、历史版本专用水印、legal hold |
| Sprint 4：权限系统 | 代码完成 | 空间角色、节点 ACL、继承、deny 优先、缓存失效、二次查权、用户/部门/用户组管理 API | 核心范围无明显缺口 |
| Sprint 5：分享/预览/搜索 | 代码完成 | 内外部分享、分享给我的、通知、授权重算、过期治理、图片/PDF/Office 预览、OCR、复杂格式抽取、搜索 ACL | 高级内容分类属于远期治理 |
| Sprint 6：管理/部署 | 代码完成 | 管理 API、统计、维护、导出、Windows Compose、Nginx、TLS/ACME、监控、备份恢复、备份轮换和隔离演练代码 | 真实 DNS、受信证书、生产通知端点和正式发布验收 |
| Sprint 7：Rust 桌面基础 | 代码完成 | Tauri、设备会话、增量游标、tombstone、SQLite 索引、传输队列、凭据存储、托盘、诊断导出 | Cloud Files API 虚拟盘未实现 |
| Sprint 8：双向同步与桌面发布 | 代码完成 | 文件监听、离线队列、断点续传、冲突副本、选择性同步、路径安全、签名更新和回退 | macOS/Linux 文件提供器未实现 |
| Sprint 9：核心产品闭环 | 代码完成 | 文件版本、回滚、回收站批量操作、内部分享接收端、完整管理 API | 核心范围无明显缺口 |
| Sprint 10：Web 用户端与管理后台 | 代码完成 | React/Vite、生成 API client、文件/上传/搜索/回收站/分享/通知/账号页面、管理后台 | 生产网络浏览器验收仍待发布阶段 |
| Sprint 11：身份与账号安全 | 代码完成 | 登录锁定、验证码、密码策略、全会话治理、OIDC/PKCE、LDAP 同步、身份管理页面 | 真实企业 OIDC/LDAPS 互操作验收 |
| Sprint 12：规模化治理 | 代码完成，进入发布前收口 | 审计分区与归档、外部投递、Outbox dead-letter、生命周期策略、权限重算、治理页面、Grafana 看板、备份签名/加密、离线副本、跨版本迁移、四依赖故障恢复矩阵 | 生产密钥、外部接收端和发布环境演练；当时遗留的 MinIO 风险已在 Sprint 13 通过运行时替换处理 |

## 4. Sprint 13：稳定版发布拆分

目标版本：`1.0.0`

| 子阶段 | 目标 | 当前状态 | 代码/工件依据 | 仍需完成 |
|---|---|---|---|---|
| Sprint 13.1：发布基线冻结 | 固定版本、OpenAPI、迁移、依赖、配置和兼容窗口 | 代码与远端门禁完成 | 基线 `8c54c96e12f` 完成跨端 `1.0.0` 冻结；对象存储必要变更 `ba378cf2f18a` 保持版本/OpenAPI/migration 不变，受影响 CI 全绿 | 保持候选冻结，生产前置关闭前不追加未经验证的代码 |
| Sprint 13.2：生产环境前置条件 | DNS、HTTPS、证书、Secret、OIDC/LDAP、对象存储和监控接收端 | 对象存储运行时替换完成，外部环境待验收 | 正式 Compose 使用 `seaweedfs`、`storage-init` 和新的 `seaweedfs-data`；SeaweedFS 固定为 `4.40@sha256:52194fba4fecd0083c842158b3a902ba6e04a63619b2b0efcd08007bdb6a4602`，OCI revision `875cd1f67ea25e8965a4f5ba1e6aaf501ba6b6fa` | 真实 DNS/受信证书、真实身份源、真实告警接收、生产 secret 与责任签字 |
| Sprint 13.3：完整 UAT | 用户端、管理端、公开分享、权限、上传下载、身份、桌面同步全流程 | 清单冻结，待候选环境签字 | `docs/sprint13-release-readiness.md` 已按普通用户、空间角色、管理员、身份、外部分享、桌面和运维角色固定真实 UAT | 执行真实 gateway/API 流程、关闭缺陷并签字 |
| Sprint 13.4：性能与稳定性 | 目标规模、长时间运行、并发、依赖故障、恢复和资源边界 | 代码侧优化完成；现有 mixed 候选仅 `upload_init` 未过 | target 各场景已强制必需指标和非零样本；`upload_complete` 已有通过工件；mixed 保留 10,000 节点/100 万索引/1,000 万审计证据，唯一失败为 `upload_init` P95 `470 ms`（目标 `300 ms`） | 以修复后的最终候选按发布窗口重新执行一次 target/mixed；另需长期 soak、升级恢复耗时与 RPO/RTO 实测；本轮不重复完整负载 |
| Sprint 13.5：安全与供应链 | 代码、依赖、镜像、签名、SBOM、密钥和发布风险 | 当前 SeaweedFS digest 的远端扫描证据完成，剩余 High 与生产密钥待签字 | Run `31031565671` 的 artifact `8940899557` 含 Syft `1.46.0` SPDX 与 Grype `0.115.0`，结果 `0 Critical / 1 High`；High 为 `GHSA-hrxh-6v49-42gf` | 修复该 High 或完成外部风险接受；若修复更换 digest 则重新扫描；完成生产密钥轮换与责任签字 |
| Sprint 13.6：升级、备份与回滚 | 版本升级、跨版本迁移、失败恢复、备份恢复、桌面更新回退 | 对象存储 Windows 备份恢复兼容已通过，完整升级与全量迁移待执行 | 更新清单强制携带当前客户端对应的上一版安装包；对象存储迁移工具 fail-closed 检测未完成 multipart；SeaweedFS 完整 source→backup→verify→隔离 target 恢复已核对 PostgreSQL、Redis、OpenSearch、对象和全栈健康 | 用同一候选执行 MinIO→SeaweedFS 全量迁移、服务端/桌面升级回滚并形成 RPO/RTO 证据 |
| Sprint 13.7：发布工件 | 镜像、Web 包、Windows 安装包、更新包、OpenAPI、SBOM、校验和 | 当前 Windows 候选工件已产出并复验；正式 Release 工件待外部门禁关闭 | Run `31033796164` 的 artifact `8942405724` 对应 `5144dede8117`，manifest 为 `REL-005/1`、`1.0.0`、7 个角色；对象存储 SBOM artifact `8940899557` 对应功能提交 `ba378cf2f18a` | 外部门禁关闭后使用最终候选生成正式后端/Web/Preview digest、必要的新 digest SBOM 和 Release 资产 |
| Sprint 13.8：正式发布收口 | 合并主分支、创建 tag/Release、部署、监控和试点交接 | 尚未开始 | 当前仓库仍无 Git tag 或正式 GitHub Release；现有 Actions candidate artifact 不等于正式发布 | `dev` 合并 `main`、创建 `v1.0.0`、发布 Release、完成试点交接和上线复盘 |

## 5. 当前验证状态

| 检查 | 结果 |
|---|---|
| 运行时 OpenAPI 导入 | `1.0.0 / 116 / 148 / 178`；归档和生成 client 均为 current |
| Alembic head | `20260804_0026` |
| 版本一致性 | `1 passed`；覆盖 backend/uv、Web/package lock/OpenAPI/client、Cargo/Tauri/桌面契约 |
| 性能门禁聚焦测试 | `4 passed`；覆盖 mixed 缺指标、零样本、upload-init 吞吐和 complete 端到端指标 |
| Sprint 13 目标工件 | `upload_complete`：1,934 个样本、0 失败、API P95 `600 ms`、端到端 P95 `650 ms`、吞吐 `58.0579 RPS`，`passed=true`；`mixed`：45,535 个请求、0 失败，`admin_audit`/`file_list_permission_batch`/`search` 通过，`upload_init` P95 `470 ms`、`passed=false` |
| `upload_init` 直接受影响验证 | active 秒传与 deleting blob 拒绝：`2 passed`；未重跑完整 upload、mixed 或 upload-complete 负载 |
| OpenAPI breaking checker | `8 tests OK`；候选归档对旧基线 `a2ac96a` 兼容检查通过 |
| 发布清单工具 | `6 tests OK`；覆盖工件/校验和篡改、缺件、绝对路径、UNC 和大小写重复路径 |
| 后端受影响 Ruff lint/format | 通过 |
| Rust 定向门禁 | `drive-update` GNU check、3 tests、Clippy，`drive-desktop` GNU check/Clippy，workspace fmt 和 metadata 通过；9 个 package 均为 `1.0.0` |
| CI 配置 | actionlint 通过；scope router `21 tests OK`；backend CI run `31135045950` 的 `changes` 与 backend 全部成功，其余不受影响 job 按 scope 跳过 |
| Git 差异检查 | `git diff --check` 通过 |
| 未重复范围 | 本轮未重跑历史性能 target、完整 mixed/upload-complete、全量 Playwright、全量 pytest 和无关桌面集合；仅复核既有 JSON 工件并运行两条直接受影响上传测试 |
| 远端对象存储门禁 | `backend-ci` run `31031565671` 对 `ba378cf2f18a` 成功；changes、backend、windows-deployment、object-storage-image-policy、object-storage-supply-chain 全绿，未受影响 frontend/Rust/installer 按 scope 跳过；backend `468 passed, 2 warnings` |
| 当前 Windows 候选工件 | Run `31033796164` 的 changes 与 `windows-desktop-installer` 成功，其余不受影响 job 跳过；artifact `8942405724`（ZIP digest `sha256:43064a14eb24722c94be4263789ec174d2d1e632e27ddcb328e58109f3d6e55a`）对应 `5144dede8117`，清单复验通过；当前包 SHA-256 `c8071773...e1ecd`，回滚包 `513a075a...d735b` |
| 历史 Windows 候选工件 | Artifact `8937081786` 对应对象存储替换前的 `8c54c96e12f`，仅保留历史证据 |
| SeaweedFS 正式镜像 | `chrislusf/seaweedfs:4.40@sha256:52194fba4fecd0083c842158b3a902ba6e04a63619b2b0efcd08007bdb6a4602`；OCI revision `875cd1f67ea25e8965a4f5ba1e6aaf501ba6b6fa` |
| 对象存储直接验证 | 既有真实 S3 集成 `3 passed`；正式 `storage-init` 的签名 PUT/GET/DELETE、匿名拒绝、CORS allow/deny 和删除后检查全部通过；最小化为 7 个 S3/TZ 变量后真实复测仍为 8 项通过 |
| 旧数据迁移抽样 | 真实 MinIO→SeaweedFS 单对象迁移通过，size、SHA-256、Content-Type、用户 metadata 和 tags 均保持一致 |
| Windows 备份恢复兼容 | backup/restore smoke `27 passed`；真实 `-FullStackRestore` 已完成 `seaweedfs-data` 归档、发布前 `backup-verify`、隔离 target 恢复和四依赖/全栈健康检查，恢复对象与 bucket 均保持；末尾 gateway 探针 Host 路由缺陷已定向修复并验证 `healthz/readyz=200` |
| 对象存储供应链 | Artifact `8940899557`（ZIP digest `sha256:13ffc1fa5e2ec0a19f153c5e8047458ca3780a3618441ec7a04ee6cb773a48b4`）包含 SPDX、Grype JSON、Critical/High ID；`0 Critical / 1 High` |
| 四依赖恢复矩阵 | Artifact `8941042883` 对 PostgreSQL、Redis、S3、OpenSearch 各完成故障检测与恢复，`final_state=healthy` |

## 6. 目前真正剩余的工作

1. 为 SeaweedFS 的 `GHSA-hrxh-6v49-42gf` 完成外部风险接受或修复。
2. 按 `docs/object-storage-seaweedfs-migration.md` 完成旧 MinIO 全量 S3 级迁移和
   inventory 对账；旧 `minio-data` 不得直接挂载到 SeaweedFS。
3. 在真实网络完成 DNS、受信证书、OIDC/LDAPS 和监控通知验收。
4. 以本轮 `upload_init` 修复后的最终候选执行一次 target/mixed 复验，并完成真实 UAT、
   soak、安全、升级、恢复、回滚和 RPO/RTO 签字；外部门禁关闭后使用最终候选生成
   正式镜像 digest 与 Release 资产。
5. 外部阻塞全部关闭后，执行 `dev -> main`、创建 `v1.0.0` tag/Release，并完成试点交接。
