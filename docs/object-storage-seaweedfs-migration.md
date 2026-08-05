# MinIO 到 SeaweedFS 的 S3 级迁移

适用版本：Sprint 13 / `1.0.0` 候选
正式目标：SeaweedFS `4.40`

```text
chrislusf/seaweedfs:4.40@sha256:52194fba4fecd0083c842158b3a902ba6e04a63619b2b0efcd08007bdb6a4602
OCI revision: 875cd1f67ea25e8965a4f5ba1e6aaf501ba6b6fa
```

## 1. 不可破坏的迁移边界

- 旧 `minio-data` 是 MinIO 原始卷，只能由创建该卷时的旧提交和固定 MinIO
  镜像读取。禁止把该卷直接挂载到 SeaweedFS，也禁止用当前 Compose 把它改名为
  `seaweedfs-data`。
- 迁移必须通过两个私有 S3 端点执行：旧 MinIO 是 source，新的 SeaweedFS 是
  target。对象正文、size、SHA-256、Content-Type、用户 metadata 和 tags 必须逐项
  对账。
- target 必须使用新的 Compose project 和新的 `seaweedfs-data` 卷。迁移通过并
  完成候选环境签字前，不删除旧 project、旧卷、旧镜像或旧提交 worktree。
- 切换前必须停止上传、预览、导出、生命周期和对象清理等写入面，并确认没有未完成
  multipart upload。`scripts.object_storage_admin migrate --apply` 在 multipart
  检测不完整或检测到未完成会话时会 fail-closed。
- 迁移证据写入仓库外的 restricted ACL 目录；连接 secret 只通过当前进程环境变量或
  受控环境文件注入，不写入命令参数、Git、报告或截图。

## 2. 已验证基线

2026-08-05 的实现验证结果：

- 正式 `compose.windows.yml` 使用 `seaweedfs` 和一次性 `storage-init`；
  `storage-init` 已通过签名 PUT/GET/DELETE、删除后 404、匿名 bucket/object 拒绝及
  CORS 允许/拒绝来源检查。
- 既有真实 S3 集成集合在 SeaweedFS 上为 `3 passed`。
- 一次真实的 MinIO 到 SeaweedFS 单对象迁移已确认 size、SHA-256、Content-Type、
  用户 metadata 和 tags 全部保持一致。
- Windows backup/restore smoke `27 passed`；真实完整恢复已完成 `seaweedfs-data`
  归档、发布前校验、隔离 target 四依赖/全栈健康和对象恢复点对账。
- 本地 Grype `v0.115.0` 扫描为 `0 Critical / 1 High`；High 为
  `GHSA-hrxh-6v49-42gf`，报告的修复版本为 gRPC `1.82.1`。该 High 仍需在正式发布
  前形成外部风险接受或修复证据。

上述结果关闭了旧 MinIO `16/9` 个 Critical 基线的**正式运行时替换**问题并完成
Windows 备份恢复兼容；提交 `ba378cf2f18a` 的远端 run `31031565671` 也已全绿，
但不等于完整升级/RPO-RTO 或生产 UAT 已完成。

## 3. 准备两个隔离环境

以下示例使用两个不同的 Compose project 和两个不同的 gateway S3 端口。占位值必须
替换为实际值。

```powershell
$RepoRoot = "D:\enterprise-drive"
$BackendRoot = Join-Path $RepoRoot "backend"
```

### 3.1 旧 MinIO source

1. 找到创建现有 `minio-data` 的准确旧提交和固定镜像 reference。
2. 从该提交建立只用于迁移的 detached worktree：

```powershell
$LegacyCommit = "LEGACY_COMMIT"
$LegacyWorktree = "D:\enterprise-drive-legacy-$($LegacyCommit.Substring(0, 12))"
git worktree add --detach $LegacyWorktree $LegacyCommit
```

3. 使用旧提交的 `.env.windows.example` 生成受控环境文件，并至少设置：

```dotenv
COMPOSE_PROJECT_NAME=enterprise-drive-legacy
DRIVE_GATEWAY_PORT=LEGACY_API_PORT
DRIVE_STORAGE_GATEWAY_PORT=LEGACY_STORAGE_PORT
```

4. 由旧 worktree 的 `compose.windows.yml`、旧管理脚本和旧固定 MinIO 镜像启动
   source。不要用当前 `compose.windows.yml` 打开旧卷。启动后只把 source 用于
   S3 list/stat/get/tags 和 multipart 盘点，不再接受业务写入。

### 3.2 新 SeaweedFS target

1. 使用当前候选的环境模板创建独立 target 环境，并至少设置：

```dotenv
COMPOSE_PROJECT_NAME=enterprise-drive-seaweedfs
DRIVE_GATEWAY_PORT=TARGET_API_PORT
DRIVE_STORAGE_GATEWAY_PORT=TARGET_STORAGE_PORT
DRIVE_S3_ENDPOINT_URL=http://seaweedfs:9000
SEAWEEDFS_IMAGE=chrislusf/seaweedfs:4.40@sha256:52194fba4fecd0083c842158b3a902ba6e04a63619b2b0efcd08007bdb6a4602
```

2. 确认 target 没有复用旧 physical volume。渲染后的逻辑卷必须是
   `seaweedfs-data`，并由 target project 新建。
3. 启动 target 后检查 `seaweedfs` 为 healthy、`storage-init` 退出码为 `0`。
   `api`、Worker 和 gateway 都依赖 `storage-init` 成功，任一 S3 私有性、签名、
   CORS 或删除检查失败都会阻止业务栈继续启动。

## 4. 注入迁移连接

在新的 PowerShell 进程中设置 source/target 连接。不要把真实 secret 放到命令行
参数中：

```powershell
$EvidenceRoot = "D:\enterprise-drive-governance\object-storage-migration\MIGRATION_ID"

$env:DRIVE_SOURCE_S3_ENDPOINT_URL = "http://127.0.0.1:LEGACY_STORAGE_PORT"
$env:DRIVE_SOURCE_S3_ACCESS_KEY_ID = "LEGACY_ACCESS_KEY"
$env:DRIVE_SOURCE_S3_SECRET_ACCESS_KEY = "LEGACY_SECRET_KEY"
$env:DRIVE_SOURCE_S3_BUCKET = "enterprise-drive"
$env:DRIVE_SOURCE_S3_REGION = "us-east-1"

$env:DRIVE_TARGET_S3_ENDPOINT_URL = "http://127.0.0.1:TARGET_STORAGE_PORT"
$env:DRIVE_TARGET_S3_ACCESS_KEY_ID = "TARGET_ACCESS_KEY"
$env:DRIVE_TARGET_S3_SECRET_ACCESS_KEY = "TARGET_SECRET_KEY"
$env:DRIVE_TARGET_S3_BUCKET = "enterprise-drive"
$env:DRIVE_TARGET_S3_REGION = "us-east-1"

if (-not (Test-Path -LiteralPath $EvidenceRoot -PathType Container)) {
    throw "Pre-create EvidenceRoot outside the repository with restricted ACL."
}
```

`DRIVE_SOURCE_*` 与 `DRIVE_TARGET_*` 只供 `migrate` 子命令使用。`inventory` 使用无
前缀的 `DRIVE_S3_*`，下面会在同一进程中显式切换。

## 5. 迁移前 inventory 与 dry-run

```powershell
Set-Location $BackendRoot

$env:DRIVE_S3_ENDPOINT_URL = $env:DRIVE_SOURCE_S3_ENDPOINT_URL
$env:DRIVE_S3_ACCESS_KEY_ID = $env:DRIVE_SOURCE_S3_ACCESS_KEY_ID
$env:DRIVE_S3_SECRET_ACCESS_KEY = $env:DRIVE_SOURCE_S3_SECRET_ACCESS_KEY
$env:DRIVE_S3_BUCKET = $env:DRIVE_SOURCE_S3_BUCKET
$env:DRIVE_S3_REGION = $env:DRIVE_SOURCE_S3_REGION
uv run python -X utf8 -m scripts.object_storage_admin inventory `
  --output "$EvidenceRoot\source-before.json"

$env:DRIVE_S3_ENDPOINT_URL = $env:DRIVE_TARGET_S3_ENDPOINT_URL
$env:DRIVE_S3_ACCESS_KEY_ID = $env:DRIVE_TARGET_S3_ACCESS_KEY_ID
$env:DRIVE_S3_SECRET_ACCESS_KEY = $env:DRIVE_TARGET_S3_SECRET_ACCESS_KEY
$env:DRIVE_S3_BUCKET = $env:DRIVE_TARGET_S3_BUCKET
$env:DRIVE_S3_REGION = $env:DRIVE_TARGET_S3_REGION
uv run python -X utf8 -m scripts.object_storage_admin inventory `
  --output "$EvidenceRoot\target-before.json"

uv run python -X utf8 -m scripts.object_storage_admin migrate `
  --output "$EvidenceRoot\migration-dry-run.json"
```

检查 dry-run：

```powershell
$DryRun = Get-Content -LiteralPath "$EvidenceRoot\migration-dry-run.json" `
  -Raw -Encoding utf8 | ConvertFrom-Json

if ($DryRun.status -ne "ok") {
    throw "S3 migration dry-run failed."
}
if ($DryRun.multipart_uploads.detection -ne "complete") {
    throw "Incomplete multipart detection is not complete."
}
if ([int]$DryRun.multipart_uploads.count -ne 0) {
    throw "Incomplete multipart uploads must be completed or aborted before migration."
}
```

dry-run 的 `records[].action` 应为 `would_copy`。未完成 multipart upload 不会迁移，
也不能通过忽略检测继续 apply。

## 6. 执行一次 apply

```powershell
uv run python -X utf8 -m scripts.object_storage_admin migrate `
  --apply `
  --output "$EvidenceRoot\migration-apply.json"

$Apply = Get-Content -LiteralPath "$EvidenceRoot\migration-apply.json" `
  -Raw -Encoding utf8 | ConvertFrom-Json
if ($Apply.status -ne "ok") {
    throw "S3 migration apply or per-object verification failed."
}
```

每个已复制对象都必须包含以下全 true 的验证结果：

```text
verification.size
verification.sha256
verification.content_type
verification.user_metadata
verification.tags
```

出现任一 false 时停止切流，保留两端和报告，不删除 source，也不对失败对象做无差别
覆盖。

## 7. 迁移后全量对账

```powershell
$env:DRIVE_S3_ENDPOINT_URL = $env:DRIVE_SOURCE_S3_ENDPOINT_URL
$env:DRIVE_S3_ACCESS_KEY_ID = $env:DRIVE_SOURCE_S3_ACCESS_KEY_ID
$env:DRIVE_S3_SECRET_ACCESS_KEY = $env:DRIVE_SOURCE_S3_SECRET_ACCESS_KEY
$env:DRIVE_S3_BUCKET = $env:DRIVE_SOURCE_S3_BUCKET
$env:DRIVE_S3_REGION = $env:DRIVE_SOURCE_S3_REGION
uv run python -X utf8 -m scripts.object_storage_admin inventory `
  --output "$EvidenceRoot\source-after.json"

$env:DRIVE_S3_ENDPOINT_URL = $env:DRIVE_TARGET_S3_ENDPOINT_URL
$env:DRIVE_S3_ACCESS_KEY_ID = $env:DRIVE_TARGET_S3_ACCESS_KEY_ID
$env:DRIVE_S3_SECRET_ACCESS_KEY = $env:DRIVE_TARGET_S3_SECRET_ACCESS_KEY
$env:DRIVE_S3_BUCKET = $env:DRIVE_TARGET_S3_BUCKET
$env:DRIVE_S3_REGION = $env:DRIVE_TARGET_S3_REGION
uv run python -X utf8 -m scripts.object_storage_admin inventory `
  --output "$EvidenceRoot\target-after.json"
```

使用相同字段做严格对账：

```powershell
$Source = Get-Content -LiteralPath "$EvidenceRoot\source-after.json" `
  -Raw -Encoding utf8 | ConvertFrom-Json
$Target = Get-Content -LiteralPath "$EvidenceRoot\target-after.json" `
  -Raw -Encoding utf8 | ConvertFrom-Json

$SourceObjects = $Source.objects | ConvertTo-Json -Depth 20 -Compress
$TargetObjects = $Target.objects | ConvertTo-Json -Depth 20 -Compress

if ([int]$Source.object_count -ne [int]$Target.object_count) {
    throw "Object count mismatch."
}
if ([int64]$Source.total_size -ne [int64]$Target.total_size) {
    throw "Total size mismatch."
}
if ($SourceObjects -cne $TargetObjects) {
    throw "Key/size/hash/content-type/metadata/tags inventory mismatch."
}
```

只有 inventory、业务对象抽样、真实预签名上传下载和候选环境 UAT 均通过后，才把应用
的内部 S3 端点切到 `http://seaweedfs:9000`。

## 8. 切流、观察和回退

- 切流前再次冻结写入并执行最终增量 inventory/migrate；切流后记录首个成功写对象、
  首个读取对象和首个 multipart complete。
- 旧 MinIO source 保留只读，直到 UAT、soak、升级/恢复、RPO/RTO 和备份恢复兼容
  演练完成并签字。当前实现完成不代表这些外部门禁已经通过。
- 若 SeaweedFS 尚未接受新写入，可直接把应用流量切回已验证的旧 project。若已经产生
  新写入，先冻结两端并对新增对象做反向 S3 级迁移与 inventory 对账；禁止仅修改端点
  后丢弃 target 上的新对象。
- 回退也不得把 `seaweedfs-data` 挂到 MinIO，或把 `minio-data` 挂到 SeaweedFS。
  两种原始卷始终由各自的固定服务版本读取，跨实现交换只走 S3。

## 9. 发布证据

最终发布记录至少保存：

- legacy commit、MinIO image reference/digest 和旧 physical volume 名称；
- SeaweedFS image reference/digest、OCI revision 和新 physical volume 名称；
- source/target endpoint、bucket、region 的脱敏描述；
- dry-run、apply、source/target inventory JSON；
- multipart 检测结果；
- 对象数、总字节数及 size/SHA-256/Content-Type/metadata/tags 对账结论；
- SeaweedFS SBOM、Grype 报告及 `GHSA-hrxh-6v49-42gf` 的风险接受或修复记录；
- UAT、soak、升级/恢复、备份恢复和 RPO/RTO 责任人签字。

在上述发布前置项关闭前，不创建 `v1.0.0` tag 或 GitHub Release。

迁移命令结束后关闭该 PowerShell 进程，或显式清除
`DRIVE_SOURCE_S3_*`、`DRIVE_TARGET_S3_*` 和临时 `DRIVE_S3_*` 环境变量，避免凭据
继续驻留在后续交互式命令中。
