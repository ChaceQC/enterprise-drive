# 项目阶段状态

更新时间：2026-08-05

## 1. 统计口径

本文件的“已完成”只依据当前工作区中的实际源码、运行时 OpenAPI、数据库迁移、测试代码、Compose 配置、Rust workspace 和前端工程判断。

- 阶段名称只用于归类，不把计划文字当作实现证据。
- CI 结果只作为验证证据，不作为项目功能清单。
- “代码侧完成”与“生产环境验收完成”分开记录。

## 2. 当前代码基线

| 项目 | 当前实际状态 |
|---|---|
| 分支 | `dev` |
| HEAD | `a2ac96a7c84d`（Sprint 13 候选改动尚未提交） |
| 工作区 | Sprint 13 候选版本、桌面更新、发布门禁和文档改动待统一提交 |
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
| Sprint 12：规模化治理 | 代码完成，进入发布前收口 | 审计分区与归档、外部投递、Outbox dead-letter、生命周期策略、权限重算、治理页面、Grafana 看板、备份签名/加密、离线副本、跨版本迁移、四依赖故障恢复矩阵 | 生产密钥、外部接收端、MinIO 修复镜像和发布环境演练 |

## 4. Sprint 13：稳定版发布拆分

目标版本：`1.0.0`

| 子阶段 | 目标 | 当前状态 | 代码/工件依据 | 仍需完成 |
|---|---|---|---|---|
| Sprint 13.1：发布基线冻结 | 固定版本、OpenAPI、迁移、依赖、配置和兼容窗口 | 代码完成，待远端门禁 | 后端、Web、OpenAPI client、Rust workspace、Tauri 和锁文件已统一为 `1.0.0`；migration head 保持 `20260804_0026` | 推送后完成同提交 CI 与候选工件核对 |
| Sprint 13.2：生产环境前置条件 | DNS、HTTPS、证书、Secret、OIDC/LDAP、MinIO 镜像和监控接收端 | 待生产环境 | Compose、TLS、OIDC、LDAP、监控和 Secret 注入代码已存在 | 真实 DNS/受信证书、真实身份源、受支持 MinIO 修复镜像、真实告警接收 |
| Sprint 13.3：完整 UAT | 用户端、管理端、公开分享、权限、上传下载、身份、桌面同步全流程 | 清单冻结，待候选环境签字 | `docs/sprint13-release-readiness.md` 已按普通用户、空间角色、管理员、身份、外部分享、桌面和运维角色固定真实 UAT | 执行真实 gateway/API 流程、关闭缺陷并签字 |
| Sprint 13.4：性能与稳定性 | 目标规模、长时间运行、并发、依赖故障、恢复和资源边界 | 自动门禁已补强，候选运行待执行 | target 各场景已强制必需指标和非零样本；既有 10,000 节点/100 万索引/1,000 万审计证据保留 | 对 `1.0.0` 执行 target、长期 soak、升级恢复耗时与 RPO/RTO 实测 |
| Sprint 13.5：安全与供应链 | 代码、依赖、镜像、签名、SBOM、密钥和发布风险 | 代码门禁已补强，外部风险仍阻塞 | OpenAPI 已检测 type/format/enum 收窄；桌面运行时校验 Authenticode 固定签名者；现有 Bandit、pip-audit、Grype、SBOM 门禁保留 | 处理 MinIO Critical、最终扫描、风险接受和密钥轮换签字 |
| Sprint 13.6：升级、备份与回滚 | 版本升级、跨版本迁移、失败恢复、备份恢复、桌面更新回退 | 桌面主链路修复完成，演练待执行 | 更新清单强制携带当前客户端对应的上一版安装包；缺包阻止安装；关键恢复失败不写健康标记；watchdog 错误 fail-closed；CI 从 Git 历史构建并签名 `0.9.0` 回滚包 | 用候选工件执行服务端和桌面完整升级/回滚、形成 RPO/RTO 证据 |
| Sprint 13.7：发布工件 | 镜像、Web 包、Windows 安装包、更新包、OpenAPI、SBOM、校验和 | 候选工件流水线已补齐，待 CI 产出 | 新增发布说明、工件清单工具与校验和；Windows artifact 将包含当前/回滚安装包、`latest.json`、OpenAPI、发布说明、公钥和证书 | 推送后核对 artifact；正式镜像 digest/SBOM 与全套 Release 工件仍待生产门禁 |
| Sprint 13.8：正式发布收口 | 合并主分支、创建 tag/Release、部署、监控和试点交接 | 尚未开始 | 当前仓库仍无 Git tag，未发现 `v1.0.0` 发布工件 | `dev` 合并 `main`、创建 `v1.0.0`、发布 Release、完成试点交接和上线复盘 |

## 5. 当前验证状态

| 检查 | 结果 |
|---|---|
| 运行时 OpenAPI 导入 | `1.0.0 / 116 / 148 / 178`；归档和生成 client 均为 current |
| Alembic head | `20260804_0026` |
| 版本一致性 | `1 passed`；覆盖 backend/uv、Web/package lock/OpenAPI/client、Cargo/Tauri/桌面契约 |
| 性能门禁聚焦测试 | `4 passed`；覆盖 mixed 缺指标、零样本、upload-init 吞吐和 complete 端到端指标 |
| OpenAPI breaking checker | `8 tests OK`；候选归档对旧基线 `a2ac96a` 兼容检查通过 |
| 发布清单工具 | `6 tests OK`；覆盖工件/校验和篡改、缺件、绝对路径、UNC 和大小写重复路径 |
| 后端受影响 Ruff lint/format | 通过 |
| Rust 定向门禁 | `drive-update` GNU check、3 tests、Clippy，`drive-desktop` GNU check/Clippy，workspace fmt 和 metadata 通过；9 个 package 均为 `1.0.0` |
| CI 配置 | actionlint 通过；scope router `20 tests OK`；本次预计触发 backend/frontend/desktop/installer/rust-policy |
| Git 差异检查 | `git diff --check` 通过 |
| 未重复范围 | 未运行历史性能 target、全量 Playwright、全量 pytest、MinIO/备份恢复和无关桌面集合 |
| 远端候选门禁 | 待本次提交推送后生成 |

## 6. 目前真正剩余的工作

1. 处理受支持的 MinIO 修复镜像和最终供应链风险。
2. 在真实网络完成 DNS、受信证书、OIDC/LDAPS 和监控通知验收。
3. 推送当前 `1.0.0` 候选改动，确认本次 CI 和 Windows 候选工件全绿。
4. 按 Sprint 13.3—13.6 执行真实候选环境的 UAT、soak、安全、升级、恢复、回滚和 RPO/RTO 签字。
5. 外部阻塞全部关闭后，执行 `dev -> main`、创建 `v1.0.0` tag/Release，并完成试点交接。
