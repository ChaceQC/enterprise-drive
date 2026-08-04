[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $Utf8NoBom
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom

$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\.."))
. (Join-Path $RepoRoot "deploy\windows\backup-restore.ps1")
. (Join-Path $RepoRoot "deploy\windows\governance.ps1")
. (Join-Path $RepoRoot "deploy\windows\offline-backup.ps1")
. (Join-Path $RepoRoot "deploy\windows\data-migration.ps1")

function Assert-SmokeEqual {
    param(
        [AllowNull()]
        [object]$Expected,

        [AllowNull()]
        [object]$Actual,

        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    if ($Expected -ne $Actual) {
        throw "$Message Expected '$Expected', received '$Actual'."
    }
}

function New-SmokeManagedBackup {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root,

        [Parameter(Mandatory = $true)]
        [string]$ProjectName,

        [Parameter(Mandatory = $true)]
        [string]$Timestamp,

        [Parameter(Mandatory = $true)]
        [string]$BackupId,

        [Parameter(Mandatory = $true)]
        [string]$Payload
    )

    $Path = Join-Path $Root "$Timestamp-$ProjectName-$BackupId"
    $null = New-Item -ItemType Directory -Path $Path
    Set-WindowsRestrictedAcl -Path $Path -Directory
    Write-WindowsUtf8File `
        -Path (Join-Path $Path "payload.txt") `
        -Content $Payload
    $CreatedAt = [System.DateTime]::ParseExact(
        $Timestamp,
        "yyyyMMddTHHmmssZ",
        [System.Globalization.CultureInfo]::InvariantCulture,
        [System.Globalization.DateTimeStyles]::AssumeUniversal
    ).ToUniversalTime().ToString("o")
    $Manifest = [ordered]@{
        format_version = 1
        backup_id = $BackupId
        created_at_utc = $CreatedAt
        source_project = $ProjectName
        project_version = "0.9.0"
        git_commit = ("a" * 40)
        database = [ordered]@{
            alembic_revision = "20260804_0025"
        }
    }
    $ManifestPath = Join-Path $Path "manifest.json"
    Write-WindowsUtf8File `
        -Path $ManifestPath `
        -Content (($Manifest | ConvertTo-Json -Depth 6) + "`n")
    Write-WindowsUtf8File `
        -Path (Join-Path $Path "manifest.sha256") `
        -Content "$(Get-WindowsSha256 -Path $ManifestPath)  manifest.json`n"
    return $Path
}

function New-SmokePortableExport {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$ProjectName,

        [Parameter(Mandatory = $true)]
        [string]$ExportId
    )

    $null = New-Item -ItemType Directory -Path $Path
    Set-WindowsRestrictedAcl -Path $Path -Directory
    foreach ($DirectoryName in @("redis", "opensearch")) {
        $null = New-Item `
            -ItemType Directory `
            -Path (Join-Path $Path $DirectoryName)
    }
    [System.IO.File]::WriteAllBytes(
        (Join-Path $Path "redis\redis.rdb"),
        [byte[]](1, 2, 3, 4)
    )
    Write-WindowsUtf8File `
        -Path (Join-Path $Path "opensearch\index.json") `
        -Content "{}`n"
    Write-WindowsUtf8File `
        -Path (Join-Path $Path "opensearch\documents.ndjson") `
        -Content "`n"
    $Artifacts = @()
    foreach (
        $File in @(
            Get-ChildItem -LiteralPath $Path -Recurse -File |
                Sort-Object FullName
        )
    ) {
        $Artifacts += [pscustomobject][ordered]@{
            path = Get-WindowsRelativeArtifactPath `
                -Root $Path `
                -Path $File.FullName
            size_bytes = [int64]$File.Length
            sha256 = Get-WindowsSha256 -Path $File.FullName
        }
    }
    $Manifest = [ordered]@{
        format_version = 1
        export_id = $ExportId
        created_at_utc = [System.DateTime]::UtcNow.ToString("o")
        source_project = $ProjectName
        project_version = "0.9.0"
        git_commit = ("b" * 40)
        redis = [ordered]@{
            image_reference = "redis:7.4-alpine"
            image_id = "sha256:$('1' * 64)"
            server_version = "7.4.1"
            keyspace_info = "# Keyspace"
            artifact_path = "redis/redis.rdb"
        }
        opensearch = [ordered]@{
            image_reference = "opensearchproject/opensearch:2.17.1"
            image_id = "sha256:$('2' * 64)"
            server_version = "2.17.1"
            index_name = "drive_files_v1"
            index_exists = $false
            document_count = 0
            metadata_path = "opensearch/index.json"
            bulk_path = "opensearch/documents.ndjson"
        }
        artifacts = $Artifacts
    }
    $ManifestPath = Join-Path $Path "manifest.json"
    Write-WindowsUtf8File `
        -Path $ManifestPath `
        -Content (($Manifest | ConvertTo-Json -Depth 12) + "`n")
    Write-WindowsUtf8File `
        -Path (Join-Path $Path "manifest.sha256") `
        -Content "$(Get-WindowsSha256 -Path $ManifestPath)  manifest.json`n"
}

$Suffix = [Guid]::NewGuid().ToString("N")
$TempRoot = Join-Path (
    [System.IO.Path]::GetTempPath()
) "enterprise-drive-ops-governance-$Suffix"
$ProjectName = "ops-smoke-$($Suffix.Substring(0, 8))"
try {
    $null = New-Item -ItemType Directory -Path $TempRoot
    Set-WindowsRestrictedAcl -Path $TempRoot -Directory
    $SourceRoot = Join-Path $TempRoot "source"
    $OfflineRoot = Join-Path $TempRoot "offline"
    $RecordRoot = Join-Path $TempRoot "records"
    foreach ($Path in @($SourceRoot, $OfflineRoot, $RecordRoot)) {
        $null = New-Item -ItemType Directory -Path $Path
        Set-WindowsRestrictedAcl -Path $Path -Directory
    }
    $BackupId = ("c" * 32)
    $SourcePath = New-SmokeManagedBackup `
        -Root $SourceRoot `
        -ProjectName $ProjectName `
        -Timestamp "20260804T010203Z" `
        -BackupId $BackupId `
        -Payload "offline-$Suffix"

    function Get-WindowsComposeProjectName {
        param([string[]]$ComposeBaseArguments)
        $null = $ComposeBaseArguments
        return $ProjectName
    }

    $Rotation = Invoke-WindowsOfflineBackupRotation `
        -RepoRoot $RepoRoot `
        -ComposeBaseArguments @("compose") `
        -BackupPath $SourcePath `
        -OfflineBackupDirectory $OfflineRoot `
        -RetentionDays 120 `
        -RetentionCount 12 `
        -ApplyRetention
    Assert-SmokeEqual `
        -Expected "copied" `
        -Actual ([string]$Rotation.copy_status) `
        -Message "Offline backup was not copied."
    Assert-SmokeEqual `
        -Expected $true `
        -Actual (
            Test-Path `
                -LiteralPath ([string]$Rotation.offline_backup_path) `
                -PathType Container
        ) `
        -Message "Offline backup destination is missing."
    Assert-SmokeEqual `
        -Expected (
            Get-WindowsBackupInventoryDigest `
                -Inventory @(
                    Get-WindowsBackupFileInventory -Root $SourcePath
                )
        ) `
        -Actual ([string]$Rotation.source_inventory_sha256) `
        -Message "Offline backup inventory digest changed."

    $PortablePath = Join-Path $TempRoot "portable-export"
    New-SmokePortableExport `
        -Path $PortablePath `
        -ProjectName $ProjectName `
        -ExportId ("d" * 32)
    $PortableManifest = Test-WindowsPortableDataExport `
        -ExportPath $PortablePath
    Assert-SmokeEqual `
        -Expected ("d" * 32) `
        -Actual ([string]$PortableManifest.export_id) `
        -Message "Portable export validation returned the wrong ID."

    function Get-WindowsComposeModel {
        param([string[]]$ComposeBaseArguments)
        $null = $ComposeBaseArguments
        return [pscustomobject][ordered]@{
            name = "ops-target"
        }
    }
    function Get-WindowsCurrentDataVersions {
        param([string[]]$ComposeBaseArguments)
        $null = $ComposeBaseArguments
        return [pscustomobject][ordered]@{
            redis = "7.4.1"
            opensearch = "2.17.1"
        }
    }
    function New-WindowsPortableDataExport {
        param(
            [string]$RepoRoot,
            [string[]]$ComposeBaseArguments,
            [string]$ExportDirectory
        )
        $null = $RepoRoot
        $null = $ComposeBaseArguments
        $null = $ExportDirectory
        return $PortablePath
    }
    $script:ImportCalls = 0
    $script:FailFirstImport = $false
    function Invoke-WindowsPortableDataImportInternal {
        param(
            [string[]]$ComposeBaseArguments,
            [string]$ExportPath,
            [object]$Manifest,
            [switch]$SkipVersionCheck
        )
        $null = $ComposeBaseArguments
        $null = $ExportPath
        $null = $Manifest
        $null = $SkipVersionCheck
        $script:ImportCalls++
        if ($script:FailFirstImport -and $script:ImportCalls -eq 1) {
            throw "simulated migration failure"
        }
        return [pscustomobject][ordered]@{
            redis = "7.4.1"
            opensearch = "2.17.1"
        }
    }

    $Success = Invoke-WindowsPortableDataMigration `
        -RepoRoot $RepoRoot `
        -ComposeBaseArguments @("compose") `
        -ExportPath $PortablePath `
        -RollbackExportDirectory $TempRoot `
        -RecordDirectory $RecordRoot `
        -Mode "apply"
    Assert-SmokeEqual `
        -Expected "succeeded" `
        -Actual ([string]$Success.status) `
        -Message "Portable migration success report is invalid."
    Assert-SmokeEqual `
        -Expected 1 `
        -Actual $script:ImportCalls `
        -Message "Successful migration imported more than once."

    $script:ImportCalls = 0
    $script:FailFirstImport = $true
    $Failure = $null
    try {
        $null = Invoke-WindowsPortableDataMigration `
            -RepoRoot $RepoRoot `
            -ComposeBaseArguments @("compose") `
            -ExportPath $PortablePath `
            -RollbackExportDirectory $TempRoot `
            -RecordDirectory $RecordRoot `
            -Mode "apply"
    }
    catch {
        $Failure = $_
    }
    Assert-SmokeEqual `
        -Expected $true `
        -Actual ($null -ne $Failure) `
        -Message "Failed migration did not report an error."
    Assert-SmokeEqual `
        -Expected 2 `
        -Actual $script:ImportCalls `
        -Message "Failed migration did not execute one rollback import."
    if ($Failure.Exception.Message -notlike "*was rolled back*") {
        throw "Failed migration did not report successful rollback."
    }

    $ManageText = [System.IO.File]::ReadAllText(
        (Join-Path $RepoRoot "deploy\windows\manage.ps1"),
        (New-Object System.Text.UTF8Encoding($false, $true))
    )
    foreach ($Action in @(
        "backup-offline-rotate",
        "data-migration-export",
        "data-migration-apply",
        "data-migration-rollback"
    )) {
        if (-not $ManageText.Contains("`"$Action`"")) {
            throw "manage.ps1 is missing Sprint 12 action '$Action'."
        }
    }

    Write-Output "Sprint 12 governance and migration smoke tests passed."
}
finally {
    if (Test-Path -LiteralPath $TempRoot -PathType Container) {
        Remove-Item -LiteralPath $TempRoot -Recurse -Force
    }
}
