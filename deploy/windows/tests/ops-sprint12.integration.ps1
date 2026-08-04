[CmdletBinding()]
param(
    [switch]$PreflightOnly,

    [switch]$KeepArtifacts
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $Utf8NoBom
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom

$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\.."))
$ComposeFile = Join-Path $RepoRoot "compose.windows.yml"
$EnvFile = Join-Path $RepoRoot ".env.windows.example"
. (Join-Path $RepoRoot "deploy\windows\backup-restore.ps1")
. (Join-Path $RepoRoot "deploy\windows\governance.ps1")
. (Join-Path $RepoRoot "deploy\windows\data-migration.ps1")

function New-ComposeArguments {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectName
    )

    return @(
        "compose",
        "--project-name", $ProjectName,
        "--env-file", $EnvFile,
        "--file", $ComposeFile
    )
}

function Remove-IntegrationProject {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$ComposeBaseArguments
    )

    try {
        $null = Invoke-WindowsDocker -Arguments @(
            $ComposeBaseArguments +
            @(
                "down",
                "--remove-orphans",
                "--volumes",
                "--timeout", "60"
            )
        )
    }
    catch {
        Write-Warning "Integration project cleanup failed: $($_.Exception.Message)"
    }
}

function Assert-IntegrationEqual {
    param(
        [AllowNull()]
        [object]$Expected,

        [AllowNull()]
        [object]$Actual,

        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    if ($Expected -ne $Actual) {
        throw "$Label expected '$Expected', received '$Actual'."
    }
}

if (-not (Test-WindowsDocker -Arguments @("info"))) {
    throw "Docker Engine is not available for Sprint 12 OPS integration."
}

$Suffix = [Guid]::NewGuid().ToString("N").Substring(0, 10)
$SourceProject = "enterprise-drive-ops-source-$Suffix"
$TargetProject = "enterprise-drive-ops-target-$Suffix"
$SourceArguments = New-ComposeArguments -ProjectName $SourceProject
$TargetArguments = New-ComposeArguments -ProjectName $TargetProject
$SourceModel = Get-WindowsComposeModel `
    -ComposeBaseArguments $SourceArguments
foreach ($ServiceName in @("redis", "opensearch")) {
    $Image = Get-WindowsModelServiceImage `
        -ComposeModel $SourceModel `
        -ServiceName $ServiceName
    if (-not (Test-WindowsDocker -Arguments @("image", "inspect", $Image))) {
        throw "Required local image is missing for '$ServiceName': $Image"
    }
}
if ($PreflightOnly) {
    Write-Output "Sprint 12 OPS integration preflight passed."
    return
}

$TestRoot = Join-Path (
    [System.IO.Path]::GetTempPath()
) "enterprise-drive-ops-integration-$Suffix"
$ExportRoot = Join-Path $TestRoot "exports"
$RollbackRoot = Join-Path $TestRoot "rollbacks"
$RecordRoot = Join-Path $TestRoot "records"
$SourceKey = "ops:migration:source:$Suffix"
$TargetKey = "ops:migration:target:$Suffix"
$SourceValue = "source-$Suffix"
$TargetValue = "target-$Suffix"
$IndexName = [string](
    Get-WindowsModelEnvironmentValue `
        -ComposeModel $SourceModel `
        -ServiceName "api" `
        -Name "DRIVE_OPENSEARCH_INDEX_NAME"
)
$EncodedIndex = [System.Uri]::EscapeDataString($IndexName)
$SourceStarted = $false
$TargetStarted = $false
try {
    $null = New-Item -ItemType Directory -Path $TestRoot
    Set-WindowsRestrictedAcl -Path $TestRoot -Directory
    foreach ($Path in @($ExportRoot, $RollbackRoot, $RecordRoot)) {
        $null = New-Item -ItemType Directory -Path $Path
        Set-WindowsRestrictedAcl -Path $Path -Directory
    }

    $null = Invoke-WindowsDocker -Arguments @(
        $SourceArguments +
        @(
            "up",
            "--detach",
            "--no-build",
            "--pull", "never",
            "redis",
            "opensearch"
        )
    )
    $SourceStarted = $true
    Wait-WindowsComposeServices `
        -ComposeBaseArguments $SourceArguments `
        -Services @("redis", "opensearch") `
        -TimeoutSeconds 360
    $null = Invoke-WindowsDocker -Arguments @(
        $SourceArguments +
        @(
            "exec", "--no-TTY",
            "redis",
            "redis-cli",
            "SET",
            $SourceKey,
            $SourceValue
        )
    )
    $null = Invoke-WindowsOpenSearchRequest `
        -ComposeBaseArguments $SourceArguments `
        -Method DELETE `
        -Path "/$EncodedIndex" `
        -ExpectedStatus @(200, 404)
    $null = Invoke-WindowsOpenSearchRequest `
        -ComposeBaseArguments $SourceArguments `
        -Method PUT `
        -Path "/$EncodedIndex" `
        -Body '{"mappings":{"properties":{"value":{"type":"keyword"}}}}'
    $null = Invoke-WindowsOpenSearchRequest `
        -ComposeBaseArguments $SourceArguments `
        -Method PUT `
        -Path "/$EncodedIndex/_doc/source?refresh=true" `
        -Body "{`"value`":`"$SourceValue`"}" `
        -ExpectedStatus @(200, 201)
    $SourceExportPath = New-WindowsPortableDataExport `
        -RepoRoot $RepoRoot `
        -ComposeBaseArguments $SourceArguments `
        -ExportDirectory $ExportRoot

    $null = Invoke-WindowsDocker -Arguments @(
        $TargetArguments +
        @(
            "up",
            "--detach",
            "--no-build",
            "--pull", "never",
            "redis",
            "opensearch"
        )
    )
    $TargetStarted = $true
    Wait-WindowsComposeServices `
        -ComposeBaseArguments $TargetArguments `
        -Services @("redis", "opensearch") `
        -TimeoutSeconds 360
    $null = Invoke-WindowsDocker -Arguments @(
        $TargetArguments +
        @(
            "exec", "--no-TTY",
            "redis",
            "redis-cli",
            "SET",
            $TargetKey,
            $TargetValue
        )
    )
    $null = Invoke-WindowsOpenSearchRequest `
        -ComposeBaseArguments $TargetArguments `
        -Method DELETE `
        -Path "/$EncodedIndex" `
        -ExpectedStatus @(200, 404)
    $null = Invoke-WindowsOpenSearchRequest `
        -ComposeBaseArguments $TargetArguments `
        -Method PUT `
        -Path "/$EncodedIndex" `
        -Body '{"mappings":{"properties":{"value":{"type":"keyword"}}}}'
    $null = Invoke-WindowsOpenSearchRequest `
        -ComposeBaseArguments $TargetArguments `
        -Method PUT `
        -Path "/$EncodedIndex/_doc/target?refresh=true" `
        -Body "{`"value`":`"$TargetValue`"}" `
        -ExpectedStatus @(200, 201)

    $Migration = Invoke-WindowsPortableDataMigration `
        -RepoRoot $RepoRoot `
        -ComposeBaseArguments $TargetArguments `
        -ExportPath $SourceExportPath `
        -RollbackExportDirectory $RollbackRoot `
        -RecordDirectory $RecordRoot `
        -Mode "apply"
    Assert-IntegrationEqual `
        -Expected "succeeded" `
        -Actual ([string]$Migration.status) `
        -Label "migration status"
    $MigratedRedis = @(
        Invoke-WindowsDocker -Arguments @(
            $TargetArguments +
            @(
                "exec", "--no-TTY",
                "redis",
                "redis-cli",
                "--raw",
                "GET",
                $SourceKey
            )
        )
    ) -join ""
    Assert-IntegrationEqual `
        -Expected $SourceValue `
        -Actual $MigratedRedis.Trim() `
        -Label "migrated Redis value"
    $MigratedDocument = Invoke-WindowsOpenSearchRequest `
        -ComposeBaseArguments $TargetArguments `
        -Method GET `
        -Path "/$EncodedIndex/_doc/source"
    $MigratedObject = $MigratedDocument.body |
        ConvertFrom-Json -ErrorAction Stop
    Assert-IntegrationEqual `
        -Expected $SourceValue `
        -Actual ([string]$MigratedObject._source.value) `
        -Label "migrated OpenSearch document"

    $Rollback = Invoke-WindowsPortableDataMigration `
        -RepoRoot $RepoRoot `
        -ComposeBaseArguments $TargetArguments `
        -ExportPath ([string]$Migration.rollback_export_path) `
        -RollbackExportDirectory $RollbackRoot `
        -RecordDirectory $RecordRoot `
        -Mode "rollback"
    Assert-IntegrationEqual `
        -Expected "succeeded" `
        -Actual ([string]$Rollback.status) `
        -Label "rollback status"
    $RolledBackRedis = @(
        Invoke-WindowsDocker -Arguments @(
            $TargetArguments +
            @(
                "exec", "--no-TTY",
                "redis",
                "redis-cli",
                "--raw",
                "GET",
                $TargetKey
            )
        )
    ) -join ""
    Assert-IntegrationEqual `
        -Expected $TargetValue `
        -Actual $RolledBackRedis.Trim() `
        -Label "rolled-back Redis value"
    $RolledBackDocument = Invoke-WindowsOpenSearchRequest `
        -ComposeBaseArguments $TargetArguments `
        -Method GET `
        -Path "/$EncodedIndex/_doc/target"
    $RolledBackObject = $RolledBackDocument.body |
        ConvertFrom-Json -ErrorAction Stop
    Assert-IntegrationEqual `
        -Expected $TargetValue `
        -Actual ([string]$RolledBackObject._source.value) `
        -Label "rolled-back OpenSearch document"

    Write-Output "Sprint 12 OPS integration passed."
}
finally {
    if ($TargetStarted) {
        Remove-IntegrationProject -ComposeBaseArguments $TargetArguments
    }
    if ($SourceStarted) {
        Remove-IntegrationProject -ComposeBaseArguments $SourceArguments
    }
    if (-not $KeepArtifacts -and (Test-Path -LiteralPath $TestRoot)) {
        Remove-Item -LiteralPath $TestRoot -Recurse -Force
    }
    elseif ($KeepArtifacts) {
        Write-Output "Sprint 12 OPS integration artifacts: $TestRoot"
    }
}
