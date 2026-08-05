# 企业网盘 v1.0.0 候选发布说明

发布日期：待正式发布门禁完成后确定
候选版本：`1.0.0`
候选分支：`dev`
数据库 migration head：`20260804_0026`
OpenAPI：116 paths / 148 operations / 178 schemas

## 1. 发布定位

`v1.0.0` 是企业网盘首个稳定版候选。当前代码已统一后端、Web、生成式 OpenAPI
client、Rust workspace、Tauri 安装包和桌面更新清单版本，并保留 Windows 11 +
Docker Desktop 作为正式部署基线。

本文件是候选发布说明，不替代生产环境验收记录。受支持 MinIO 修复镜像、真实
DNS/受信证书、企业 OIDC/LDAPS、告警接收端和最终签字未完成前，不创建正式 tag
或 GitHub Release。

## 2. 主要能力

- 文件、目录、版本、回收站、批量操作、multipart、秒传、断点续传、Range 下载。
- 空间角色、节点 ACL、继承与 deny 优先、搜索二次查权和权限缓存失效。
- 内外部分享、分享给我的、通知、预览、OCR、全文检索和内容安全策略。
- Web 用户端、管理后台、账号安全、OIDC/OAuth 2.1 + PKCE、LDAP 同步。
- Windows 11 Rust/Tauri 双向同步、离线恢复、冲突副本、选择性同步和诊断导出。
- 生命周期、权限重算、审计分区/归档/投递、Outbox dead-letter 和治理看板。
- Windows Compose、Nginx gateway、TLS/ACME、监控、备份恢复、离线副本及
  Redis/OpenSearch 可移植迁移。

## 3. Sprint 13 候选修复

- 性能 target 报告为每个场景固定必需指标；缺少指标或零样本时发布门禁失败。
- OpenAPI 冻结检查递归检测 `type`、`format` 变化与 enum 收窄。
- 桌面更新清单携带并验证上一版本安装包，watchdog 才允许进入自动回退。
- 桌面健康标记仅在本地操作恢复、自动传输恢复和已保存 watcher 启动均成功，
  Tauri setup/托盘完成、后台循环已调度且进程继续存活 15 秒后写入。
- 下载的 Windows 安装包在运行时校验 Authenticode 签名者证书 SHA-256。
- 发布工件使用 `.github/scripts/release_manifest.py` 生成清单与 `SHA256SUMS`，
  并可在发布前重新验证文件大小、SHA-256 和完整库存。

## 4. 兼容性与升级

- 目标升级路径为项目上一稳定候选 `0.9.0 -> 1.0.0`；正式发布前必须使用同一
  候选 commit 和工件完成升级、失败恢复与回滚演练，演练通过后才声明正式支持。
- 数据库沿用单一 migration head `20260804_0026`，本次版本冻结不新增 migration。
- OpenAPI 路径、操作和 schema 数量保持 116 / 148 / 178；客户端重新生成并锁定
  `1.0.0`。
- 桌面更新要求主安装包和回滚包均通过 Ed25519、SHA-256、目标平台及
  Authenticode 固定签名者校验。
- 正式升级必须先完成备份校验，在隔离 project 中验证恢复点，再执行生产升级。

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
| 供应链 | 各正式镜像/安装包 SBOM 与漏洞扫描报告 |
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

1. 固定 MinIO Server/Client 镜像的既有 Critical 风险尚未由受支持修复镜像或可审计
   补丁镜像关闭。
2. 真实公网 DNS、受信证书签发/续期、双域名 HTTPS 验收尚需生产网络。
3. 企业 OIDC provider、LDAPS 目录和生产告警接收端尚需真实互操作验收。
4. 候选版本仍需完成角色 UAT、长期 soak、升级/回滚、恢复耗时测量与 RPO/RTO
   责任人签字。

上述项目的验收和签字格式见
[`docs/sprint13-release-readiness.md`](sprint13-release-readiness.md)。
