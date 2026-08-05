# 企业网盘 v1.0.0 候选发布说明

发布日期：待正式发布门禁完成后确定
候选版本：`1.0.0`
候选分支：`dev`
候选基线 commit：`8c54c96e12f925fe7e0a07bf3a6444e63f600044`
候选 CI：[`backend-ci` run `31019866714`](https://github.com/ChaceQC/enterprise-drive/actions/runs/31019866714)（成功）
Windows artifact：[`8937081786`](https://github.com/ChaceQC/enterprise-drive/actions/runs/31019866714/artifacts/8937081786)
数据库 migration head：`20260804_0026`
OpenAPI：116 paths / 148 operations / 178 schemas
对象存储替换：实现、直接验证和 Windows 备份恢复兼容完成，最终 commit/push/受影响 CI 待确认

## 1. 发布定位

`v1.0.0` 是企业网盘首个稳定版候选。当前代码已统一后端、Web、生成式 OpenAPI
client、Rust workspace、Tauri 安装包和桌面更新清单版本，并保留 Windows 11 +
Docker Desktop 作为正式部署基线。

本文件是候选发布说明，不替代生产环境验收记录。正式对象存储已从 MinIO 替换为
SeaweedFS `4.40`，旧 `16/9` Critical 已退出正式运行时，Windows 备份恢复兼容已
通过；但 SeaweedFS High 风险签字、全量数据迁移、真实 DNS/受信证书、企业
OIDC/LDAPS、告警接收端、升级/RPO-RTO 和最终签字未完成前，不创建正式 tag 或
GitHub Release。

## 2. 主要能力

- 文件、目录、版本、回收站、批量操作、multipart、秒传、断点续传、Range 下载。
- 空间角色、节点 ACL、继承与 deny 优先、搜索二次查权和权限缓存失效。
- 内外部分享、分享给我的、通知、预览、OCR、全文检索和内容安全策略。
- Web 用户端、管理后台、账号安全、OIDC/OAuth 2.1 + PKCE、LDAP 同步。
- Windows 11 Rust/Tauri 双向同步、离线恢复、冲突副本、选择性同步和诊断导出。
- 生命周期、权限重算、审计分区/归档/投递、Outbox dead-letter 和治理看板。
- Windows Compose、Nginx gateway、TLS/ACME、监控、备份恢复、离线副本及
  Redis/OpenSearch 可移植迁移。
- 固定 digest 的 SeaweedFS `4.40` S3 数据面、fail-closed `storage-init` 和
  MinIO→SeaweedFS S3 级迁移工具。

## 3. Sprint 13 候选修复

- 性能 target 报告为每个场景固定必需指标；缺少指标或零样本时发布门禁失败。
- OpenAPI 冻结检查递归检测 `type`、`format` 变化与 enum 收窄。
- 桌面更新清单携带并验证上一版本安装包，watchdog 才允许进入自动回退。
- 桌面健康标记仅在本地操作恢复、自动传输恢复和已保存 watcher 启动均成功，
  Tauri setup/托盘完成、后台循环已调度且进程继续存活 15 秒后写入。
- 下载的 Windows 安装包在运行时校验 Authenticode 签名者证书 SHA-256。
- 发布工件使用 `.github/scripts/release_manifest.py` 生成清单与 `SHA256SUMS`，
  并可在发布前重新验证文件大小、SHA-256 和完整库存。
- 正式 Compose 使用
  `chrislusf/seaweedfs:4.40@sha256:52194fba4fecd0083c842158b3a902ba6e04a63619b2b0efcd08007bdb6a4602`
  （OCI revision `875cd1f67ea25e8965a4f5ba1e6aaf501ba6b6fa`）、
  `seaweedfs`、`storage-init` 和新的 `seaweedfs-data`；旧 `minio-data` 只允许
  由旧提交/旧固定镜像读取并通过 S3 迁移。

## 4. 兼容性与升级

- 目标升级路径为项目上一稳定候选 `0.9.0 -> 1.0.0`；正式发布前必须使用同一
  候选 commit 和工件完成升级、失败恢复与回滚演练，演练通过后才声明正式支持。
- 数据库沿用单一 migration head `20260804_0026`，本次版本冻结不新增 migration。
- OpenAPI 路径、操作和 schema 数量保持 116 / 148 / 178；客户端重新生成并锁定
  `1.0.0`。
- 桌面更新要求主安装包和回滚包均通过 Ed25519、SHA-256、目标平台及
  Authenticode 固定签名者校验。
- 正式升级必须先完成备份校验，在隔离 project 中验证恢复点，再执行生产升级。
- 对象存储升级必须先按 `docs/object-storage-seaweedfs-migration.md` 完成 dry-run、
  未完成 multipart fail-closed、全量 apply 和两端 inventory 对账。一次真实单对象
  迁移已保持 size、SHA-256、Content-Type、用户 metadata 和 tags；该抽样不替代
  全量迁移。
- SeaweedFS Windows 备份恢复兼容已完成真实 source→backup→verify→隔离 target
  全栈恢复；正式 `0.9.0 -> 1.0.0` 升级、恢复耗时和 RPO/RTO 仍需使用最终候选执行。

## 5. 发布工件

正式 Release 的同一提交必须提供：

| 角色 | 工件 |
|---|---|
| API 契约 | `openapi.json` |
| Web | 静态 Web 包或带 digest 的 Web 镜像 |
| 后端 | API/核心 Worker 镜像与 digest |
| 内容处理 | Preview Worker 镜像与 digest |
| Windows | Authenticode 签名 NSIS 安装包 |
| 桌面更新 | `latest.json`、当前安装包、上一版回滚安装包、更新公钥 |
| 供应链 | 各正式镜像/安装包 SBOM 与漏洞扫描报告；SeaweedFS High 风险处理记录 |
| 完整性 | `release-manifest.json`、`SHA256SUMS` |
| 验收 | UAT、性能、安全、升级/回滚、RPO/RTO 和风险签字记录 |

清单生成示例：

```powershell
python -X utf8 .github/scripts/release_manifest.py build `
  --input-dir TARGET_ARTIFACT_DIRECTORY `
  --version 1.0.0 `
  --git-commit TARGET_COMMIT `
  --require openapi=openapi.json `
  --require windows_installer=TARGET_CURRENT_INSTALLER_NAME `
  --require rollback_installer=TARGET_ROLLBACK_INSTALLER_NAME `
  --require update_manifest=latest.json `
  --require release_notes=RELEASE_NOTES.md `
  --require update_key=update-public-key.txt `
  --require signing_certificate=desktop-code-signing.pem

python -X utf8 .github/scripts/release_manifest.py verify `
  --input-dir TARGET_ARTIFACT_DIRECTORY
```

## 6. 已知发布阻塞

1. SeaweedFS 本地 Grype `v0.115.0` 为 `0 Critical / 1 High`；
   `GHSA-hrxh-6v49-42gf`（报告修复版本 gRPC `1.82.1`）仍需修复或外部风险接受，
   并需最终 SPDX/Grype 与受影响 CI 证据。
2. 旧 MinIO 全量 S3 级迁移和对象 RPO/RTO 尚未执行完成；旧 `minio-data` 不得
   直接挂载到 SeaweedFS。
3. 真实公网 DNS、受信证书签发/续期、双域名 HTTPS 验收尚需生产网络。
4. 企业 OIDC provider、LDAPS 目录和生产告警接收端尚需真实互操作验收。
5. 候选版本仍需完成角色 UAT、长期 soak、升级/回滚、恢复耗时测量与 RPO/RTO
   责任人签字。

上述项目的验收和签字格式见
[`docs/sprint13-release-readiness.md`](sprint13-release-readiness.md)。
