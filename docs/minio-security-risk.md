# 对象存储安全风险与发布门禁

## 1. 当前结论

截至 2026-08-05，正式 `compose.windows.yml` 已不再运行 MinIO Server/Client，改为：

```text
chrislusf/seaweedfs:4.40@sha256:52194fba4fecd0083c842158b3a902ba6e04a63619b2b0efcd08007bdb6a4602
OCI revision: 875cd1f67ea25e8965a4f5ba1e6aaf501ba6b6fa
```

当前正式服务和数据边界：

- 常驻服务为 `seaweedfs`，一次性门禁为 `storage-init`。
- 正式原始卷为新的 `seaweedfs-data`。
- MinIO `minio-data` 不属于当前服务卷，禁止直接挂载给 SeaweedFS。
- 旧 MinIO Server/Client 的 `16/9` 个 Critical 基线已在**正式运行时替换层面**
  关闭，不再作为当前 Compose 镜像的漏洞允许集。

这不等于 `v1.0.0` 已满足发布条件。SeaweedFS Windows 备份恢复兼容已通过，但剩余
High、最终远端供应链报告、旧数据全量迁移、UAT、soak、升级/RPO-RTO 和外部责任
签字仍需完成。

## 2. SeaweedFS 当前扫描

本地使用 Grype `v0.115.0` 扫描当前固定 SeaweedFS 镜像：

| 严重级别 | 唯一 ID 数量 | 当前记录 |
| --- | ---: | --- |
| Critical | 0 | 无 |
| High | 1 | `GHSA-hrxh-6v49-42gf` |

Grype 报告为该 High 标注的修复版本是 gRPC `1.82.1`。正式发布前必须完成以下任一项：

1. 更新到包含修复依赖且通过全部对象存储兼容门禁的固定镜像；或
2. 由外部风险责任人记录可达性、补偿控制、责任人、到期日和升级计划后签字接受。

功能提交 `ba378cf2f18a5d56ea154a8f50f24bf6d3d2079d` 已推送。`backend-ci`
run `31031565671` 的 object-storage image policy 与 supply-chain 均成功；artifact
`8940899557` 包含 Syft `1.46.0` SPDX、Grype `0.115.0` JSON 和 Critical/High ID
列表，结果为 `0 Critical / 1 High`，ZIP digest 为
`sha256:13ffc1fa5e2ec0a19f153c5e8047458ca3780a3618441ec7a04ee6cb773a48b4`。

## 3. 已完成的直接验证

当前实现已经获得以下本地直接证据：

- 既有真实 S3 集成集合在 SeaweedFS 上为 `3 passed`。
- 正式 `storage-init` 全部检查通过：
  - 创建或确认私有 bucket；
  - 签名 PUT；
  - 签名 GET 与正文一致；
  - 未签名 bucket 请求被拒绝；
  - 未签名 object 请求被拒绝；
  - 配置的 CORS origin 允许 PUT；
  - 未配置 origin 不获得允许头；
  - 签名 DELETE；
  - 删除后的签名 GET 返回 404。
- 一次真实 MinIO→SeaweedFS 单对象迁移保持：
  - size；
  - SHA-256；
  - Content-Type；
  - 用户 metadata；
  - tags。
- Windows backup/restore smoke `27 passed`；真实完整恢复完成 `seaweedfs-data`
  归档、发布前 `backup-verify`、隔离 target 数据/全栈健康和对象恢复点对账。末尾
  gateway 请求因 IP Host 命中 Nginx `444`，修复为显式 Host 后已定向验证
  `healthz/readyz=200`。
- 远端 run `31031565671` 的 backend 为 `468 passed, 2 warnings`；四依赖 artifact
  `8941042883` 对 PostgreSQL、Redis、S3 和 OpenSearch 均检测到故障并恢复，
  `final_state=healthy`。

这些证据证明当前实现、代表性对象路径和 Windows 恢复兼容可工作，但不替代全量
inventory、长期稳定性、性能、升级/RPO-RTO 和生产网络验收。

## 4. 旧数据迁移门禁

旧 `minio-data` 的安全迁移规则是不可豁免门禁：

1. 只使用创建该卷时的旧提交、旧 `compose.windows.yml` 和固定 MinIO 镜像启动
   source。
2. 新 target 使用不同 Compose project 和新的 `seaweedfs-data`。
3. source/target 之间只通过 S3 list/stat/get/put/tags 迁移，不交换原始卷。
4. `scripts.object_storage_admin migrate` 必须先 dry-run；未完成 multipart 检测不完整
   或数量非零时，`--apply` 必须失败。
5. apply 后按 key、size、SHA-256、Content-Type、用户 metadata 和 tags 做全量
   inventory 对账。
6. UAT、soak、升级/回滚和 RPO/RTO 签字前保留旧 source、旧卷、旧镜像和旧提交。

完整命令见 `docs/object-storage-seaweedfs-migration.md`。

## 5. `v1.0.0` 发布决策

对象存储相关门禁必须全部满足：

- SeaweedFS image reference/digest 与 OCI revision 已写入发布证据。
- SPDX SBOM 与 Grype JSON 已对当前 digest 生成；Critical 为 0。若修复 High 导致
  image digest 变化，必须对新 digest 重新生成并执行同一门禁。
- `GHSA-hrxh-6v49-42gf` 已修复或获得正式外部风险接受。
- `storage-init` fail-closed 检查通过。
- 真实 S3 multipart、预签名 PUT/GET、copy、delete、list、hash、失败清理和孤儿对象
  扫描通过。
- 旧 MinIO 全量 S3 级迁移和 inventory 对账通过。
- SeaweedFS 版本的 Windows `backup`、`backup-verify`、隔离 `restore` 和恢复点检查
  已通过本地完整兼容演练；正式候选仍需纳入升级/RPO-RTO 签字。
- 同一候选完成 UAT、soak、升级/回滚和 RPO/RTO。
- 真实 DNS/TLS、OIDC/LDAPS、告警接收、密钥保管和责任签字完成。

上述门禁完成前，不创建 `v1.0.0` tag 或 GitHub Release。

## 6. 历史 MinIO 风险记录

以下内容保留用于解释替换决策，不代表当前正式 Compose 仍运行这些镜像。

2026-08-03 至替换前固定的社区版镜像为：

```text
minio/minio:RELEASE.2025-09-07T16-13-09Z@sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e
minio/mc:RELEASE.2025-08-13T08-35-41Z@sha256:a7fe349ef4bd8521fb8497f55c6042871b2ae640607cf99d9bede5e9bdf11727
```

GitHub Actions run `30793900577` 的 SPDX/Grype 复核结果为：

| 历史组件 | Critical matches | Critical 唯一 ID |
| --- | ---: | ---: |
| MinIO Server | 25 | 16 |
| MinIO Client | 9 | 9 |

其中两个直接影响 MinIO 的 Critical：

- `GHSA-5cx5-wh4m-82fh`：OIDC JWT algorithm confusion。
- `GHSA-jv87-32hw-hh99`：LDAP 用户枚举与无限尝试。

当时的关闭 OIDC/LDAP/Console、内网隔离、固定 digest 和“只阻断新增 Critical”都只是
可达性缓解，不能把旧镜像写成已修复。历史参考：

- <https://github.com/advisories/GHSA-5cx5-wh4m-82fh>
- <https://github.com/advisories/GHSA-jv87-32hw-hh99>
- <https://github.com/minio/minio>

历史允许集仅作为审计证据保留：

```text
Server:
CVE-2026-10536
CVE-2026-11856
CVE-2026-8924
CVE-2026-8927
CVE-2026-9079
GHSA-5cgq-3rg8-m6cv
GHSA-5cx5-wh4m-82fh
GHSA-89gr-r52h-f8rx
GHSA-f5wc-c3c7-36mc
GHSA-jppx-rxg9-jmrx
GHSA-jv87-32hw-hh99
GHSA-p77j-4mvh-x3m3
GHSA-rm3j-f69w-wqmq
GHSA-vgwf-h737-ff37
GHSA-x527-x647-q7gg
GO-2026-4337

Client:
GHSA-5cgq-3rg8-m6cv
GHSA-89gr-r52h-f8rx
GHSA-f5wc-c3c7-36mc
GHSA-jppx-rxg9-jmrx
GHSA-p77j-4mvh-x3m3
GHSA-rm3j-f69w-wqmq
GHSA-vgwf-h737-ff37
GHSA-x527-x647-q7gg
GO-2026-4337
```

## 7. 候选评估记录

- AIStor 候选
  `quay.io/minio/aistor/minio:RELEASE.2026-07-24T16-43-31Z@sha256:17527b97a9e92dcc32b641dc161e4beb1eaf9a9198018c1489923c981f4af2ef`
  在无有效 license 时进入 offline mode 并拒绝 S3 操作，因此未采用。
- SeaweedFS `4.40` 在候选阶段完成镜像扫描、启动探测和 S3 兼容验证后进入正式
  Compose。选择该镜像不能绕过数据迁移、备份恢复和发布环境责任签字。

## 8. 发布证据登记

最终风险记录应包含：

- 当前 SeaweedFS image reference/digest、OCI revision；
- Syft/Grype 版本、数据库时间、SPDX SBOM、完整 Grype JSON；
- `GHSA-hrxh-6v49-42gf` 的修复或风险接受记录；
- `storage-init` JSON 输出或等价日志；
- S3 集成测试结果；
- MinIO→SeaweedFS dry-run、apply、两端 inventory 和逐字段对账；
- Windows 备份恢复、升级/回滚和 RPO/RTO 报告；
- 风险责任人、安全负责人和发布负责人的签字日期。
