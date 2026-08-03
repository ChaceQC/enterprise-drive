[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $Utf8NoBom
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom

$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\.."))
$BackupRestorePath = Join-Path $RepoRoot "deploy\windows\backup-restore.ps1"
$GovernancePath = Join-Path $RepoRoot "deploy\windows\governance.ps1"
foreach ($RequiredPath in @($BackupRestorePath, $GovernancePath)) {
    if (-not (Test-Path -LiteralPath $RequiredPath -PathType Leaf)) {
        throw "Required governance script does not exist: $RequiredPath"
    }
}

. $BackupRestorePath
. $GovernancePath

function Assert-SmokeTrue {
    param(
        [Parameter(Mandatory = $true)]
        [bool]$Condition,

        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    if (-not $Condition) {
        throw $Message
    }
}

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

function New-SmokeBackup {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root,

        [Parameter(Mandatory = $true)]
        [string]$Timestamp,

        [Parameter(Mandatory = $true)]
        [string]$BackupId,

        [Parameter(Mandatory = $true)]
        [string]$CreatedAtUtc
    )

    $Path = Join-Path $Root "$Timestamp-smoke-project-$BackupId"
    $null = New-Item -ItemType Directory -Path $Path
    Set-WindowsRestrictedAcl -Path $Path -Directory

    $ManifestPath = Join-Path $Path "manifest.json"
    $Manifest = [pscustomobject][ordered]@{
        format_version = 1
        backup_id = $BackupId
        source_project = "smoke-project"
        created_at_utc = $CreatedAtUtc
        project_version = "0.4.0"
        git_commit = "1111111111111111111111111111111111111111"
        database = [pscustomobject][ordered]@{
            alembic_revision = "20260803_0021"
        }
    }
    Write-WindowsUtf8File `
        -Path $ManifestPath `
        -Content (($Manifest | ConvertTo-Json -Depth 8) + "`n")
    $Checksum = Get-WindowsSha256 -Path $ManifestPath
    Write-WindowsUtf8File `
        -Path (Join-Path $Path "manifest.sha256") `
        -Content "$Checksum  manifest.json`n"
    return $Path
}

function Get-WindowsComposeProjectName {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$ComposeBaseArguments
    )

    return "smoke-project"
}

$script:RestoreObservedProject = ""
function Invoke-WindowsRestore {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,

        [Parameter(Mandatory = $true)]
        [string]$ComposeFile,

        [Parameter(Mandatory = $true)]
        [string]$EnvFile,

        [Parameter(Mandatory = $true)]
        [string[]]$ComposeBaseArguments,

        [Parameter(Mandatory = $true)]
        [string]$BackupPath,

        [switch]$NoStartAfterRestore
    )

    $script:RestoreObservedProject = [string]$env:COMPOSE_PROJECT_NAME
    Assert-SmokeTrue `
        -Condition ([bool]$NoStartAfterRestore) `
        -Message "Restore drill must keep the isolated target stopped."
    return "restore-smoke-ok"
}

function Invoke-WindowsDocker {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    return @()
}

$Suffix = [Guid]::NewGuid().ToString("N")
$TempRoot = Join-Path (
    [System.IO.Path]::GetTempPath()
) "enterprise-drive-governance-smoke-$Suffix"
$OriginalProject = [System.Environment]::GetEnvironmentVariable(
    "COMPOSE_PROJECT_NAME",
    [System.EnvironmentVariableTarget]::Process
)

try {
    $BackupRoot = Resolve-WindowsBackupRoot `
        -RepoRoot $RepoRoot `
        -BackupDirectory (Join-Path $TempRoot "backups")
    $OldBackup = New-SmokeBackup `
        -Root $BackupRoot `
        -Timestamp "20200101T000000Z" `
        -BackupId "11111111111111111111111111111111" `
        -CreatedAtUtc "2020-01-01T00:00:00Z"
    $RecentBackup = New-SmokeBackup `
        -Root $BackupRoot `
        -Timestamp "20260803T000000Z" `
        -BackupId "22222222222222222222222222222222" `
        -CreatedAtUtc "2026-08-03T00:00:00Z"

    $RecentRecord = Get-WindowsBackupRecord -BackupPath $RecentBackup
    Assert-SmokeEqual `
        -Expected "22222222222222222222222222222222" `
        -Actual $RecentRecord.backup_id `
        -Message "Backup directory ID validation failed."

    $Retention = Invoke-WindowsBackupRetention `
        -RepoRoot $RepoRoot `
        -ComposeBaseArguments @("compose") `
        -BackupDirectory $BackupRoot `
        -RetentionDays 1 `
        -RetentionCount 1 `
        -Apply
    Assert-SmokeEqual `
        -Expected 1 `
        -Actual $Retention.removed `
        -Message "Retention did not remove exactly one expired backup."
    Assert-SmokeTrue `
        -Condition (-not (Test-Path -LiteralPath $OldBackup)) `
        -Message "Expired backup remains after retention."
    Assert-SmokeTrue `
        -Condition (Test-Path -LiteralPath $RecentBackup -PathType Container) `
        -Message "Newest backup was removed by retention."
    Assert-SmokeTrue `
        -Condition (Test-Path -LiteralPath $Retention.record_path -PathType Leaf) `
        -Message "Retention record was not written."

    $DrillRoot = Join-Path $TempRoot "drill-records"
    $Drill = Invoke-WindowsRestoreDrill `
        -RepoRoot $RepoRoot `
        -ComposeFile (Join-Path $RepoRoot "compose.windows.yml") `
        -EnvFile (Join-Path $RepoRoot ".env.windows.example") `
        -ComposeBaseArguments @("compose") `
        -BackupPath $RecentBackup `
        -RecordDirectory $DrillRoot
    Assert-SmokeEqual `
        -Expected "succeeded" `
        -Actual $Drill.status `
        -Message "Restore drill did not succeed."
    Assert-SmokeTrue `
        -Condition $script:RestoreObservedProject.StartsWith(
            "enterprise-drive-restore-drill-",
            [System.StringComparison]::Ordinal
        ) `
        -Message "Restore drill did not use an isolated Compose project."
    Assert-SmokeTrue `
        -Condition (Test-Path -LiteralPath $Drill.record_path -PathType Leaf) `
        -Message "Restore drill record was not written."
    Assert-SmokeEqual `
        -Expected $OriginalProject `
        -Actual (
            [System.Environment]::GetEnvironmentVariable(
                "COMPOSE_PROJECT_NAME",
                [System.EnvironmentVariableTarget]::Process
            )
        ) `
        -Message "Restore drill did not restore COMPOSE_PROJECT_NAME."

    Assert-SmokeTrue `
        -Condition (-not (
            Test-WindowsPublicIpAddress `
                -Address ([System.Net.IPAddress]::Parse("127.0.0.1"))
        )) `
        -Message "Loopback address was accepted as public."
    Assert-SmokeTrue `
        -Condition (-not (
            Test-WindowsPublicIpAddress `
                -Address ([System.Net.IPAddress]::Parse("198.18.0.1"))
        )) `
        -Message "Benchmark address was accepted as public."
    Assert-SmokeTrue `
        -Condition (-not (
            Test-WindowsPublicIpAddress `
                -Address ([System.Net.IPAddress]::Parse("2001:db8::1"))
        )) `
        -Message "Documentation IPv6 address was accepted as public."
    Assert-SmokeTrue `
        -Condition (
            Test-WindowsPublicIpAddress `
                -Address ([System.Net.IPAddress]::Parse("8.8.8.8"))
        ) `
        -Message "Public IPv4 address was rejected."
}
finally {
    [System.Environment]::SetEnvironmentVariable(
        "COMPOSE_PROJECT_NAME",
        $OriginalProject,
        [System.EnvironmentVariableTarget]::Process
    )
    if (Test-Path -LiteralPath $TempRoot) {
        $ResolvedTempRoot = [System.IO.Path]::GetFullPath($TempRoot)
        $SystemTempRoot = [System.IO.Path]::GetFullPath(
            [System.IO.Path]::GetTempPath()
        )
        if (
            -not (
                Test-WindowsPathWithin `
                    -Parent $SystemTempRoot `
                    -Candidate $ResolvedTempRoot
            ) -or
            -not (
                [System.IO.Path]::GetFileName($ResolvedTempRoot).StartsWith(
                    "enterprise-drive-governance-smoke-",
                    [System.StringComparison]::Ordinal
                )
            )
        ) {
            throw "Refusing to remove an unexpected smoke directory."
        }
        Remove-Item -LiteralPath $ResolvedTempRoot -Recurse -Force
    }
}

Write-Output "Windows governance smoke tests passed."
