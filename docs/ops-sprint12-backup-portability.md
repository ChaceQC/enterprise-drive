# Sprint 12 备份安全、离线副本与跨版本数据迁移

本文说明 `OPS-001`、`OPS-002`、`OPS-003` 在 Windows 11 + Docker Desktop 正式路径中的操作入口。实现位于：

- `deploy/windows/backup-security.ps1`
- `deploy/windows/offline-backup.ps1`
- `deploy/windows/data-migration.ps1`
- `deploy/windows/manage.ps1`

所有输出目录必须是仓库外的绝对专用目录，并由脚本应用或校验 restricted NTFS ACL。

## 1. Manifest 来源签名

新备份格式为 `format_version=2`。传入 `-BackupSigningCertificateThumbprint` 后，备份会：

1. 在 `manifest.json` 中记录签名证书 thumbprint、subject 和有效期；
2. 使用证书私钥生成 detached CMS 签名 `manifest.p7s`；
3. 在发布前由 `backup-verify` 校验签名、签名者证书和 manifest 元数据；
4. 离线副本盘点时再次校验签名。

建议单独创建带私钥的签名证书，并将私钥备份到受保护介质：

```powershell
$signing = New-SelfSignedCertificate `
  -Subject "CN=Enterprise Drive Backup Signing" `
  -Type CodeSigningCert `
  -CertStoreLocation "Cert:\CurrentUser\My" `
  -KeyAlgorithm RSA `
  -KeyLength 3072 `
  -NotAfter (Get-Date).AddYears(3)
```

脚本验证的是 detached CMS 密码学签名和预期 thumbprint。证书签发、信任链、吊销和双人保管仍由组织 PKI 流程负责。

## 2. 可选完整包加密

传入 `-PackageEncryptionCertificateThumbprint` 后，PostgreSQL dump、MinIO/Redis/OpenSearch/TLS 卷归档、Compose/Nginx 配置及可选 CMS 环境文件会被打包并加密。发布目录不再保留这些明文 payload，只保留：

- `package/payload.enc`
- `package/envelope.json`
- `manifest.json`
- 可选的 `manifest.p7s`
- `manifest.sha256`

加密使用：

- 内容：AES-256-CBC；
- 完整性：HMAC-SHA256，覆盖 IV 和完整 ciphertext；
- 密钥封装：证书 RSA-OAEP-SHA256；
- payload 解密后继续逐工件校验 size 和 SHA-256，并执行既有 PostgreSQL dump 与 tar 安全扫描。

建议使用独立的文档加密证书：

```powershell
$encryption = New-SelfSignedCertificate `
  -Subject "CN=Enterprise Drive Backup Package Encryption" `
  -Type DocumentEncryptionCert `
  -CertStoreLocation "Cert:\CurrentUser\My" `
  -KeyAlgorithm RSA `
  -KeyLength 3072 `
  -NotAfter (Get-Date).AddYears(3)
```

创建签名且完整加密的备份：

```powershell
.\deploy\windows\manage.ps1 backup `
  -EnvFile .env.windows `
  -BackupDirectory "E:\enterprise-drive-backups" `
  -ConfigEncryptionCertificateThumbprint $configEncryption.Thumbprint `
  -BackupSigningCertificateThumbprint $signing.Thumbprint `
  -PackageEncryptionCertificateThumbprint $encryption.Thumbprint
```

`backup-verify` 和 `restore` 会从 manifest 的 thumbprint 定位当前用户证书。执行恢复的账户必须拥有完整包加密证书私钥。

`manifest.json`、`manifest.p7s` 和 `manifest.sha256` 位于加密包外，便于离线盘点和来源验证；其中不包含环境 secret、数据库内容或文件内容。

## 3. 离线副本轮换

`backup-offline-rotate` 从指定备份或当前项目最新托管备份创建原子离线副本，复制前后逐文件比较 size/SHA-256，并记录 canonical inventory digest。

```powershell
.\deploy\windows\manage.ps1 backup-offline-rotate `
  -EnvFile .env.windows `
  -BackupDirectory "E:\enterprise-drive-backups" `
  -OfflineBackupDirectory "F:\enterprise-drive-offline" `
  -RetentionDays 120 `
  -RetentionCount 12 `
  -ApplyRetention
```

也可用 `-BackupPath` 指定单个备份；`-BackupPath` 与 `-BackupDirectory` 必须且只能提供一个。

轮换规则同时保留：

- 最近 `RetentionCount` 份；
- `RetentionDays` 天内的全部备份。

只有同时超出数量和时间门槛的副本才进入删除候选。未传 `-ApplyRetention` 时仍执行复制和完整性核对，但只预览过期候选。

每次执行都会在离线根目录下写入：

```text
.governance/offline-copies/offline-copy-*.json
```

记录包含 source/offline 路径、backup ID、文件数、inventory SHA-256、复制状态、保留策略和实际删除路径。操作系统无法判断介质是否已物理下线；复制完成后仍需按运维流程卸载、断开或移交加密介质。

## 4. Redis/OpenSearch 可移植导出

`data-migration-export` 不复制 Redis/OpenSearch 原始卷：

- Redis 使用 `redis-cli --rdb` 生成标准 RDB；
- OpenSearch 导出目标索引 settings/mappings、文档 bulk NDJSON 和文档数；
- manifest 记录 source project、Git commit、项目版本、服务版本、image reference/image ID 与全部工件 SHA-256。

```powershell
.\deploy\windows\manage.ps1 data-migration-export `
  -EnvFile .env.windows `
  -MigrationDirectory "E:\enterprise-drive-migrations"
```

导出使用 Redis RDB 快照与 OpenSearch scroll context，各自具有一致视图，但二者不是跨产品的全局事务快照。PostgreSQL 仍是业务事实来源，正式升级后应按业务流程校验或重建搜索索引。

## 5. 跨版本迁移与自动回退

目标版本的 Compose 配置、镜像和环境准备完成且 Redis/OpenSearch 健康后执行：

```powershell
.\deploy\windows\manage.ps1 data-migration-apply `
  -EnvFile .env.windows `
  -MigrationPath "E:\enterprise-drive-migrations\20260804T120000Z-source-portable-ID" `
  -MigrationRollbackDirectory "E:\enterprise-drive-governance\data-migration-rollbacks" `
  -MigrationRecordDirectory "E:\enterprise-drive-governance\data-migrations"
```

流程为：

1. 校验导出 manifest 和全部工件；
2. 记录目标 Redis/OpenSearch 版本；
3. 在修改目标前创建目标当前状态的可移植 rollback export；
4. 拒绝导入到更低 major version；
5. 用 RDB 重建目标 Redis 数据卷并等待 healthcheck；
6. 重建目标 OpenSearch 索引，分批写入 bulk NDJSON，刷新并核对文档数；
7. 任一步失败时自动导入 rollback export；
8. 无论成功或失败都写 JSON 报告。

显式回退使用相同门禁：

```powershell
.\deploy\windows\manage.ps1 data-migration-rollback `
  -EnvFile .env.windows `
  -MigrationPath "E:\enterprise-drive-governance\data-migration-rollbacks\ROLLBACK_EXPORT" `
  -MigrationRollbackDirectory "E:\enterprise-drive-governance\data-migration-rollbacks" `
  -MigrationRecordDirectory "E:\enterprise-drive-governance\data-migrations"
```

回退操作本身也会先保存当前状态，因此回退失败时仍保留恢复前证据。

报告字段包括 source/target project、source/target 版本、rollback export 路径、状态、耗时、原始错误和回退错误。状态取值：

- `succeeded`
- `failed-rolled-back`
- `failed-rollback-failed`

## 6. 定向验证

只运行 Sprint 12 OPS 及直接受影响的 Windows 脚本测试：

```powershell
.\deploy\windows\tests\ops-sprint12.security.smoke.ps1
.\deploy\windows\tests\ops-sprint12.governance.smoke.ps1
.\deploy\windows\tests\backup-restore.smoke.ps1
.\deploy\windows\tests\governance.smoke.ps1
```

真实 Redis/OpenSearch 导出、迁移和回退：

```powershell
.\deploy\windows\tests\ops-sprint12.integration.ps1 -PreflightOnly
.\deploy\windows\tests\ops-sprint12.integration.ps1
```

集成脚本只启动两个隔离 Compose project 的 Redis/OpenSearch，验证 source 导出、target 应用和恢复 target 原状态，并在结束后删除对应容器、网络和卷。

2026-08-04 本机真实 Docker 集成已通过：source 数据成功导出并应用到 target，随后使用自动生成的 rollback export 恢复 target 原 Redis key 与 OpenSearch 文档；测试创建的容器、网络、卷和宿主端口均已清理。
