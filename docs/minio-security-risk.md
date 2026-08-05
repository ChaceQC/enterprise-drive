# MinIO 安全风险与发布门禁

## 1. 当前结论

截至 2026-08-05，正式 Compose 仍固定以下社区版 MinIO 镜像：

```text
minio/minio:RELEASE.2025-09-07T16-13-09Z@sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e
minio/mc:RELEASE.2025-08-13T08-35-41Z@sha256:a7fe349ef4bd8521fb8497f55c6042871b2ae640607cf99d9bede5e9bdf11727
```

GitHub Actions run `30793900577` 的 SPDX/Grype 工件复核结果为：

| 组件 | Critical matches | Critical 唯一 ID |
| --- | ---: | ---: |
| MinIO Server | 25 | 16 |
| MinIO Client | 9 | 9 |

CI 已把允许集收紧到本次实际观测的 16/9 个唯一 ID；任何新增 Critical 仍会阻断。但允许集只表示“已登记的现存风险”，不表示漏洞已经修复。

## 2. MinIO 自身 Critical

当前 Server 允许集中包含两个直接影响 MinIO 的 Critical：

- `GHSA-5cx5-wh4m-82fh`：OIDC JWT algorithm confusion。GitHub Advisory 标记受影响版本为 `< RELEASE.2026-03-17T21-25-16Z`，社区版 advisory 没有列出 patched version。
- `GHSA-jv87-32hw-hh99`：LDAP 用户枚举与无限尝试。GitHub Advisory 同样标记 `< RELEASE.2026-03-17T21-25-16Z` 受影响，社区版 advisory 没有列出 patched version。

官方 `minio/minio` 社区仓库已经归档，并在 README 中说明社区版不再维护。不能把“固定 digest”“关闭 Console”或“CI 没有新增 Critical”写成已获得上游安全修复。

官方参考：

- <https://github.com/advisories/GHSA-5cx5-wh4m-82fh>
- <https://github.com/advisories/GHSA-jv87-32hw-hh99>
- <https://github.com/minio/minio>

## 3. 当前可达性缓解

当前正式 Compose 已实施以下缓解：

- 未配置 `MINIO_IDENTITY_OPENID_*`，OIDC 身份入口未启用。
- 未配置 `MINIO_IDENTITY_LDAP_*`，LDAP 身份入口未启用。
- `MINIO_BROWSER=off`，MinIO Console 不发布宿主端口。
- MinIO API 只在 Compose 内网暴露，宿主只能经 Nginx gateway 的 S3 入口访问。
- gateway 对 API 和本机 S3 入口执行 Host allowlist；未知 Host 返回 `444`。
- MinIO Server/Client 使用 release + digest 双固定，CI 在同一 supply-chain runner 中生成两份 SBOM 和完整 Grype JSON，并阻断允许集之外的新 Critical；镜像配置变化和每周定时任务都会执行该门禁。

这些措施降低当前配置下两个 MinIO 身份漏洞的可达性，但不改变镜像本身仍处于受影响版本范围的事实。以后若启用 OIDC、LDAP、Console 或新的 MinIO 管理入口，必须先完成镜像替换与重新扫描。

## 4. `v1.0.0` 发布决策

满足以下任一修复路线并完成全部验证前，不创建 `v1.0.0` tag 或 GitHub Release：

1. 采用仍受支持、明确包含上述修复的 S3 兼容发行版，并完成许可证、采购/支持、配置迁移和数据兼容评审。
2. 从可审计源码构建修复镜像，保存补丁来源、构建脚本、源码 commit、镜像 digest、SBOM、签名/证明材料和完整扫描报告。

镜像替换后至少执行：

- 更新 `.env.windows.example`、`compose.windows.yml`、`backend/docker-compose.yml` 和 CI 的固定 reference/digest。
- 重新生成 Server/Client SPDX SBOM 与 Grype 报告，Critical 允许集归零或形成经签字的最小剩余集。
- 运行真实 MinIO 对象读写、预签名下载、标准 S3 multipart、失败清理和孤儿对象扫描门禁。
- 验证 `minio-init` 私有 bucket、匿名访问关闭和 CORS。
- 完成 Windows 备份、`backup-verify` 和隔离恢复兼容性验证。
- 由生产风险责任人记录接受范围、到期时间和回退方案。

## 5. 当前允许集

Server：

```text
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
```

Client：

```text
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

允许集只在镜像 digest、Syft/Grype 版本和扫描日期可追溯时有效。扫描器数据库变化造成 ID 合并、拆分或严重级别变化时，应审查差异后更新，禁止直接扩大允许集。

## 6. 2026-08-05 候选替换复核

本轮没有直接替换正式 Compose 镜像，原因是可获取镜像与可用于正式数据面不是同一件事：

- 官方社区仓库当前已归档；公开 release 列表中较新的社区版仍早于 2026 年两项
  MinIO Critical advisory 的披露与受影响边界，不能据此宣称漏洞已关闭。
- 已拉取并核对
  `quay.io/minio/aistor/minio:RELEASE.2026-07-24T16-43-31Z@sha256:17527b97a9e92dcc32b641dc161e4beb1eaf9a9198018c1489923c981f4af2ef`。
  该镜像版本可启动，`/minio/health/live` 返回 200；但未安装有效 AIStor license
  时日志明确进入 offline mode，并拒绝全部 S3 操作。因此，未完成许可证、支持条款、
  离线恢复和续期流程前，不把它写入正式 Compose。
- 已对
  `chrislusf/seaweedfs:4.40@sha256:52194fba4fecd0083c842158b3a902ba6e04a63619b2b0efcd08007bdb6a4602`
  完成候选镜像扫描和启动探测；镜像 OCI metadata 对应版本 `4.40`、源码 revision
  `875cd1f67ea25e8965a4f5ba1e6aaf501ba6b6fa`。本轮尚未完成现有 MinIO 数据迁移、
  S3 API/multipart、预签名、对象复制、匿名访问关闭、备份恢复和性能门禁，因此未采用。
  不得仅因候选镜像扫描结果较少，就绕过数据兼容与运维评审。

Sprint 13 的对象存储发布门禁保持以下顺序：

1. 确认候选发行版的许可证、支持期限、升级通道和镜像签名/证明材料。
2. 在隔离环境迁移代表性 `0.9.0` 数据，并验证对象数量、大小、SHA-256、metadata
   和 multipart 未完成会话的处理边界。
3. 只执行一次候选发行版的真实 S3 兼容测试、备份恢复兼容测试和最终 SBOM/Grype；
   失败后只重跑受影响项。
4. 把最终镜像 reference、digest、扫描工件、回退镜像和风险责任人写入
   `docs/sprint13-release-readiness.md` 的发布证据，再解除 tag/Release 阻塞。
