# Sprint 13 稳定版发布验收清单

适用版本：`1.0.0`
任务范围：`REL-001` 至 `REL-005`
状态口径：代码门禁、候选环境验收、生产环境签字分别记录，不相互替代。

## 1. 发布决策总表

| 任务 | 发布门禁 | 当前候选状态 | 正式完成证据 |
|---|---|---|---|
| `REL-001` | 全产品 UAT | 清单已冻结，待候选环境逐项签字 | UAT 记录、缺陷关闭表、业务/技术签字 |
| `REL-002` | 性能与安全 | SeaweedFS digest 扫描完成；`upload_complete` target 已通过；最新 `mixed` 工件仍仅 `upload_init` 未通过，代码侧已完成 blob 单查并新增 quota 三维账户批量读取，长稳和 High 风险签字待执行 | 性能报告、修复后最终 target/mixed 工件、soak 报告、SeaweedFS SBOM/漏洞报告、非阻断风险接受 |
| `REL-003` | 安装、升级与回滚 | SeaweedFS 备份恢复兼容已通过，待 `0.9.0 -> 1.0.0` 升级/回滚演练 | 升级时间线、备份/恢复、桌面自动回退证据 |
| `REL-004` | 运维责任与 RPO/RTO | 模板已冻结，待生产责任人和实测值签字 | 值班表、告警验证、RPO/RTO 测量和接受记录 |
| `REL-005` | `v1.0.0` 发布 | 候选版本与工件规范已冻结 | `main` 合并提交、tag、Release、工件清单、交接记录 |

## 2. `REL-001` 按角色 UAT

每条记录至少包含：候选 commit、环境、执行人、开始/结束时间、测试数据范围、
预期、实际、截图或日志、缺陷 ID 和结论。

| ID | 角色 | 主流程 | 必须覆盖的失败/撤权分支 | 状态 |
|---|---|---|---|---|
| UAT-USER-01 | 普通用户 | 登录、浏览、上传、下载、版本、回收站 | 错误密码、锁定、配额不足、hash 不符 | 待候选环境 |
| UAT-EDITOR-01 | 空间编辑者 | 新建、移动、重命名、批量操作 | 同名冲突、版本前置条件冲突、ACL deny | 待候选环境 |
| UAT-VIEWER-01 | 只读成员 | 列表、预览、搜索、下载 | 写操作拒绝、撤权后搜索与下载拒绝 | 待候选环境 |
| UAT-OWNER-01 | 空间所有者 | 成员与 ACL、配额、分享 | owner 保护、跨租户、过期/撤销分享 | 待候选环境 |
| UAT-ADMIN-01 | 系统管理员 | 用户/组织/空间/治理/审计/导出 | 非管理员、CSRF、乐观版本冲突、dead-letter 重放 | 待候选环境 |
| UAT-IDENTITY-01 | 身份管理员 | OIDC 登录/绑定/登出、LDAP dry-run/full/incremental | state/nonce、issuer/JWKS、冲突、离职和会话吊销 | 待真实身份源 |
| UAT-PUBLIC-01 | 外部接收人 | 外链访问、提取码、预览/下载 | 过期、次数达限、撤销、错误租户/提取码 | 待候选环境 |
| UAT-DESKTOP-01 | Windows 用户 | 登录、同步、离线、冲突、续传、更新 | 设备吊销、网络恢复、更新失败和自动回退 | 待签名候选包 |
| UAT-OPS-01 | 运维人员 | 部署、监控、备份、恢复、迁移 | 依赖故障、错误镜像、清单篡改、回滚失败 | 待候选环境 |

通过规则：

- P0/P1 缺陷为 0。
- P2 缺陷必须有负责人、接受人、影响范围和关闭版本。
- 所有权限、身份、分享和公开入口必须在真实 API/gateway 上执行；Playwright
  mock 场景只作为 UI 回归，不替代 UAT。

### 2.1 对象存储 UAT 前置

- 正式候选必须使用
  `chrislusf/seaweedfs:4.40@sha256:52194fba4fecd0083c842158b3a902ba6e04a63619b2b0efcd08007bdb6a4602`
  （OCI revision `875cd1f67ea25e8965a4f5ba1e6aaf501ba6b6fa`）、`seaweedfs`、
  `storage-init` 和新的 `seaweedfs-data`。
- 旧 `minio-data` 只能由旧提交和固定 MinIO 镜像读取，并按
  `docs/object-storage-seaweedfs-migration.md` 通过 S3 级迁移；禁止直接挂载给
  SeaweedFS。
- 当前已验证既有真实 S3 集成 `3 passed`、`storage-init` 全检查、一次真实单对象
  迁移，以及 Windows 完整 backup/restore 兼容；全量 migration inventory、正式
  升级/RPO-RTO 和生产 UAT 仍需单独执行。

## 3. `REL-002` 性能、稳定性与安全

### 3.1 性能门禁

- `target/mixed` 必须同时出现并有样本：
  `file_list_permission_batch`、`upload_init`、`search`、`admin_audit`。
- `target/mixed`、`target/search` 和 `target/audit` 必须显式提供
  `--target-state`；mixed 的 state 目标值、完成值和运行环境实际快照必须同时达到
  100 万 OpenSearch 文档与 1,000 万条专属审计日志。
- 正式 target 负载不得缩小：fixture 子目录至少 10,000 个、并发用户至少 50、
  Locust `--run-time` 至少 300 秒，且所有用户启动后至少 warm-up 5 秒再重置统计。
- `target/upload_complete` 必须同时出现
  `upload_complete_api_without_storage_merge` 与 `upload_complete_end_to_end`。
- 既有 P95 阈值继续以 `backend/performance/profiles.py` 为事实来源；最小吞吐继续
  对 `upload_init` 和 `upload_complete` 生效。
- `report.json` 必须满足：Locust 退出码为 0、环境快照完整、无缺失必需指标、
  `target_data_errors` 与 `target_workload_errors` 为空、全部指标通过且失败数为 0。
- 长期 soak 必须单独记录持续时间、稳态负载、资源曲线、错误率、任务积压、
  数据库连接池、Redis、OpenSearch、SeaweedFS 与 Worker 恢复情况；既有 300 秒 target
  结果不替代 soak。

### 3.1.1 当前 Sprint 13 target 工件（事实记录）

本节只记录已经存在的工件，不以文档或代码修改替代负载证据，也不重复执行已经完成的
完整负载：

- `upload_complete`：
  `backend/tmp/performance/20260805-sprint13-final-54d6135/upload-complete-target-workers8/report.json`
  为 `passed=true`；1,934 个样本、0 失败、吞吐 `58.0579 RPS`，API（不含
  storage merge）P95 `600 ms`，端到端 P95 `650 ms`。同目录
  `complete_cleanup.json` 记录准备和清理 `2000/2000`。
- `mixed`：
  `backend/tmp/performance/20260807-sprint13-a5e44af/mixed-target-workers8-final/report.json`
  对应 `ca83d94`，共 43,403 个请求、0 失败，环境与 1,000,000 OpenSearch
  文档/10,000,000 审计行门禁均完整；`admin_audit` P95 `240 ms`、
  `file_list_permission_batch` P95 `340 ms`、`search` P95 `280 ms` 均通过，
  `upload_init` P95 `540 ms`（目标 `300 ms`），所以报告必须保持
  `passed=false`。旧 45,535 请求/470 ms 工件保留为历史对比。
- 2026-08-07 已在 `backend/app/modules/upload/service.py` 合并新 hash 路径的两次
  blob 查询；active 秒传与 deleting blob 拒绝的直接行为验证为 `2 passed`。当前工作树
  另有 quota 空间/租户/用户账户批量读取补丁，定向配额用例 `2 passed`，未运行性能负载。
- 提交 `a5e44af` 已推送；`backend-ci` run `31135045950` 的 `changes` 与 backend
  全部成功。该 CI 结果不替代仍未通过的 `upload_init` target 性能工件。
- 随后发现原代码提交的 backend job 曾因并发取消，已在 `a5e44af` 中修复 pytest
  收集阶段的 Locust/gevent late monkey-patch，并定向重跑 backend CI
  `31135045950`；`changes` 与 backend 全部成功。该修复只作用于测试导入隔离，
  不改变真实 `python -m locust` runner。
- 只有在最终候选发布窗口才按同一 target 规模重新执行一次 mixed，并用新工件替换
  当前候选性能证据；不得通过缩小 fixture、用户数、时长、warm-up 或改变统计方式
  规避门禁。

### 3.2 安全与供应链

- Bandit 中高风险为 0，`pip-audit` 已知漏洞为 0。
- Rust advisories/licenses/bans/sources 门禁通过。
- 后端、Preview、Web、SeaweedFS 和 Windows 安装包均有对应 SBOM 或
  可审计组件清单。
- Grype 最终报告的 Critical 必须为 0。旧 MinIO `16/9` Critical 已通过 SeaweedFS
  正式运行时替换关闭；本地 Grype `v0.115.0` 当前为 `0 Critical / 1 High`，
  High 为 `GHSA-hrxh-6v49-42gf`，报告修复版本是 gRPC `1.82.1`。
- 该 High 必须在发布前修复，或记录具体 ID、可达性、补偿控制、责任人和到期日后由
  外部风险责任人签字接受。Run `31031565671` 的 artifact `8940899557` 已提供当前
  digest 的远端 SPDX/Grype 证据；若修复更换 digest，必须重新执行扫描门禁。
- Windows 安装包必须验证 Authenticode 完整性和固定签名者证书 SHA-256；桌面更新
  还必须通过 Ed25519 与包 SHA-256。
- 发布密钥、证书和 webhook secret 必须记录保管人、轮换日期、恢复方式和吊销流程，
  不写入仓库或 Release 工件。

## 4. `REL-003` 升级、备份与回滚

必须使用同一候选 commit 和同一组正式工件执行：

1. 在 `0.9.0` 环境建立有代表性的用户、权限、文件、版本、分享、治理和身份数据。
2. 执行受保护备份并完成 `backup-verify`；将备份恢复到随机隔离 project，核对恢复点。
3. 升级镜像、配置和桌面客户端到 `1.0.0`，执行 migration 与 readiness 检查。
4. 完成 UAT 冒烟、对象上传下载、搜索、异步任务、监控和审计核对。
5. 注入应用、PostgreSQL、Redis、SeaweedFS 和 OpenSearch 失败，记录探测与恢复时间线。
6. 执行服务端回滚/恢复演练；确认配置、数据、镜像、migration 与外部端点一致。
7. 对桌面更新执行“新版本未确认健康”故障，确认 watchdog 使用已验签的 `0.9.0`
   安装包自动回退；再执行正常升级并确认健康标记只在本地恢复/watcher 前置步骤
   成功、Tauri setup/托盘完成、后台循环已调度且进程继续存活 15 秒后生成。
8. 归档命令、开始/结束时间、日志、manifest、校验和、恢复点和清理结果。

通过规则：

- 数据库、对象、索引、队列和配置均回到签字确认的恢复点。
- 演练 project 的容器和卷清理为 0 残留。
- 回滚包缺失、签名者不匹配、清单或包被篡改时必须在安装前失败。
- 任何超出批准 RPO/RTO 的结果必须形成缺陷或风险接受，不能仅记录为“成功”。

## 5. `REL-004` 运维责任、风险与 RPO/RTO

### 5.1 责任矩阵

| 领域 | 执行负责人 | 审批/接受人 | 必备证据 |
|---|---|---|---|
| DNS、证书、续期 | 待生产指定 | 待生产指定 | 双域名解析、链路、到期日与续期记录 |
| 身份源 | 待生产指定 | 安全/业务负责人 | OIDC/LDAPS 互操作与离职回收 |
| 备份与恢复 | 待生产指定 | 数据负责人 | 最近成功备份、离线副本、恢复演练 |
| 监控与值班 | 待生产指定 | 运维负责人 | 告警发送、接收、确认、升级时间线 |
| 镜像与供应链 | 待生产指定 | 安全负责人 | SeaweedFS digest/revision、SBOM、扫描、High 风险修复或接受 |
| 桌面签名与更新 | 待生产指定 | 发布负责人 | 证书指纹、密钥保管、升级/回退记录 |

### 5.2 RPO/RTO 签字

不得在未测量时填入推测值。签字表必须记录：

| 项目 | 批准目标 | 本次实测 | 测量起止点 | 结论/缺陷 |
|---|---:|---:|---|---|
| PostgreSQL RPO | 待批准 | 待实测 | 最后可验证事务到恢复点 | 待签字 |
| 对象存储 RPO | 待批准 | 待实测 | 最后可验证对象到恢复点 | 待签字 |
| 全栈 RTO | 待批准 | 待实测 | 宣布恢复开始到 gateway/API/S3/Worker 就绪 | 待签字 |
| 桌面更新 RTO | 待批准 | 待实测 | 安装失败到旧版恢复可用 | 待签字 |
| 告警 MTTD/MTTA | 待批准 | 待实测 | 故障发生到告警/确认 | 待签字 |

## 6. `REL-005` 发布与交接

只有 `REL-001` 至 `REL-004` 均为通过时执行。非阻断发现可按批准流程保留正式风险
接受记录；SeaweedFS 的 `GHSA-hrxh-6v49-42gf` 必须修复或获得外部风险责任人签字。
真实 DNS/TLS、企业 OIDC/LDAPS、告警接收、MinIO→SeaweedFS 全量迁移、SeaweedFS
备份恢复、升级回滚与 RPO/RTO 签字不得由一般风险接受替代：

1. 冻结候选 commit，确认工作树、版本、OpenAPI、lock、migration 和工件 manifest。
2. 将已验证的 `dev` 合并到 `main`，不在合并后追加未经验证的代码。
3. 创建带注释 tag `v1.0.0`。
4. 创建 GitHub Release，上传同一 manifest 中的工件、SBOM、扫描和验收报告。
5. 在正式环境按已验收步骤部署，验证 DNS、HTTPS、API、S3、Web、Worker、监控和
   告警接收。
6. 完成试点管理员、业务负责人、运维和安全交接；记录支持时间、升级窗口、
   回退触发条件和升级联系人。
7. 发布后观察期结束后形成复盘，记录事件、性能、告警噪声、用户反馈和下一版本项。

发布清单和校验和必须由
`.github/scripts/release_manifest.py` 生成并在上传 Release 前再次执行 `verify`。
