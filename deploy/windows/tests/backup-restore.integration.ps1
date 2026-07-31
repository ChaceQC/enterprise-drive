[CmdletBinding()]
param(
    [string]$EnvFile = ".env.windows.example",

    [switch]$PreflightOnly,

    [switch]$FullStackRestore,

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
$ManageScript = Join-Path $RepoRoot "deploy\windows\manage.ps1"
if (-not [System.IO.Path]::IsPathRooted($EnvFile)) {
    $EnvFile = Join-Path $RepoRoot $EnvFile
}
$EnvFile = [System.IO.Path]::GetFullPath($EnvFile)

foreach ($RequiredFile in @($ComposeFile, $ManageScript, $EnvFile)) {
    if (-not (Test-Path -LiteralPath $RequiredFile -PathType Leaf)) {
        throw "Required integration file does not exist: $RequiredFile"
    }
}

$Suffix = [Guid]::NewGuid().ToString("N").Substring(0, 10)
$SourceProject = "enterprise-drive-backup-source-$Suffix"
$TargetProject = "enterprise-drive-backup-target-$Suffix"
$BackupRoot = Join-Path (
    [System.IO.Path]::GetTempPath()
) "enterprise-drive-backup-integration-$Suffix"
$BeforeValue = "before-$Suffix"
$AfterValue = "after-$Suffix"
$ObjectKey = "backup-restore/probe-$Suffix.txt"
$RedisKey = "backup:restore:probe:$Suffix"
$SearchIndex = "backup-probe-$Suffix"
$CertificateName = "backup-restore-$Suffix"
$SourceApiPort = 28080
$SourceStoragePort = 29000
$TargetApiPort = 28081
$TargetStoragePort = 29001
$IntegrationRunningServices = @(
    "gateway",
    "api",
    "worker-audit",
    "worker-permission",
    "worker-preview",
    "worker-search",
    "worker-maintenance",
    "beat",
    "postgres",
    "redis",
    "minio",
    "opensearch"
)
$IntegrationExitedServices = @("migration", "minio-init", "seed")
$DataValidationServices = @("postgres", "redis", "minio", "opensearch")

$EnvironmentNames = @(
    "COMPOSE_PROJECT_NAME",
    "COMPOSE_PROGRESS",
    "COMPOSE_PARALLEL_LIMIT",
    "DRIVE_IMAGE_TAG",
    "NGINX_IMAGE",
    "CERTBOT_IMAGE",
    "POSTGRES_IMAGE",
    "REDIS_IMAGE",
    "MINIO_IMAGE",
    "MINIO_MC_IMAGE",
    "OPENSEARCH_IMAGE",
    "DRIVE_GATEWAY_BIND",
    "DRIVE_GATEWAY_PORT",
    "DRIVE_STORAGE_GATEWAY_BIND",
    "DRIVE_STORAGE_GATEWAY_PORT",
    "DRIVE_GATEWAY_HTTP_CONTAINER_PORT",
    "DRIVE_GATEWAY_SECONDARY_CONTAINER_PORT",
    "DRIVE_GATEWAY_TEMPLATE_PATH",
    "DRIVE_SERVER_NAME",
    "DRIVE_STORAGE_SERVER_NAME",
    "DRIVE_S3_PUBLIC_ENDPOINT_URL",
    "DRIVE_CORS_ORIGINS",
    "DRIVE_TRUSTED_HOSTS",
    "DRIVE_SESSION_COOKIE_SECURE",
    "MINIO_CORS_ALLOWED_ORIGIN",
    "DRIVE_SECRET_KEY",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "DRIVE_DATABASE_URL",
    "REDIS_PASSWORD",
    "DRIVE_REDIS_URL",
    "DRIVE_CELERY_BROKER_URL",
    "DRIVE_CELERY_RESULT_BACKEND",
    "MINIO_ROOT_PASSWORD",
    "MINIO_ROOT_USER",
    "DRIVE_S3_BUCKET",
    "OPENSEARCH_INITIAL_ADMIN_PASSWORD",
    "DRIVE_ADMIN_PASSWORD",
    "CERTBOT_EMAIL",
    "DRIVE_TLS_CERT_NAME",
    "DRIVE_API_WORKERS",
    "AUDIT_WORKER_CONCURRENCY",
    "PERMISSION_WORKER_CONCURRENCY",
    "SEARCH_WORKER_CONCURRENCY",
    "MAINTENANCE_WORKER_CONCURRENCY",
    "PREVIEW_WORKER_CONCURRENCY",
    "PREVIEW_TMPFS_SIZE",
    "OPENSEARCH_JAVA_OPTS",
    "OPENSEARCH_CPU_LIMIT",
    "OPENSEARCH_MEMORY_LIMIT",
    "API_CPU_LIMIT",
    "API_MEMORY_LIMIT",
    "MIGRATION_CPU_LIMIT",
    "MIGRATION_MEMORY_LIMIT",
    "SEED_CPU_LIMIT",
    "SEED_MEMORY_LIMIT",
    "AUDIT_WORKER_CPU_LIMIT",
    "AUDIT_WORKER_MEMORY_LIMIT",
    "PERMISSION_WORKER_CPU_LIMIT",
    "PERMISSION_WORKER_MEMORY_LIMIT",
    "SEARCH_WORKER_CPU_LIMIT",
    "SEARCH_WORKER_MEMORY_LIMIT",
    "MAINTENANCE_WORKER_CPU_LIMIT",
    "MAINTENANCE_WORKER_MEMORY_LIMIT",
    "PREVIEW_WORKER_CPU_LIMIT",
    "PREVIEW_WORKER_MEMORY_LIMIT",
    "BEAT_CPU_LIMIT",
    "BEAT_MEMORY_LIMIT",
    "GATEWAY_CPU_LIMIT",
    "GATEWAY_MEMORY_LIMIT",
    "CERTBOT_CPU_LIMIT",
    "CERTBOT_MEMORY_LIMIT",
    "POSTGRES_CPU_LIMIT",
    "POSTGRES_MEMORY_LIMIT",
    "REDIS_CPU_LIMIT",
    "REDIS_MEMORY_LIMIT",
    "MINIO_CPU_LIMIT",
    "MINIO_MEMORY_LIMIT",
    "MINIO_INIT_CPU_LIMIT",
    "DRIVE_BACKUP_HELPER_CPU_LIMIT",
    "DRIVE_BACKUP_HELPER_MEMORY_LIMIT",
    "DRIVE_BACKUP_HELPER_PIDS_LIMIT",
    "DRIVE_BACKUP_GZIP_LEVEL",
    "DRIVE_BACKUP_PG_DUMP_COMPRESSION_LEVEL",
    "MINIO_INIT_MEMORY_LIMIT"
)
$OriginalEnvironment = @{}
foreach ($Name in $EnvironmentNames) {
    $OriginalEnvironment[$Name] = [System.Environment]::GetEnvironmentVariable(
        $Name,
        [System.EnvironmentVariableTarget]::Process
    )
}

function Set-EnvironmentValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [AllowNull()]
        [string]$Value
    )

    [System.Environment]::SetEnvironmentVariable(
        $Name,
        $Value,
        [System.EnvironmentVariableTarget]::Process
    )
}

function Set-IntegrationEnvironment {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectName,

        [Parameter(Mandatory = $true)]
        [int]$ApiPort,

        [Parameter(Mandatory = $true)]
        [int]$StoragePort
    )

    $Values = @{
        COMPOSE_PROJECT_NAME = $ProjectName
        COMPOSE_PROGRESS = "quiet"
        COMPOSE_PARALLEL_LIMIT = "1"
        DRIVE_IMAGE_TAG = "windows-local"
        NGINX_IMAGE = "nginx:1.27-alpine"
        CERTBOT_IMAGE = "certbot/certbot:v5.6.0"
        POSTGRES_IMAGE = "postgres:16-bookworm"
        REDIS_IMAGE = "redis:7.4-alpine"
        MINIO_IMAGE = (
            "minio/minio:RELEASE.2025-09-07T16-13-09Z@" +
            "sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e"
        )
        MINIO_MC_IMAGE = (
            "minio/mc:RELEASE.2025-08-13T08-35-41Z@" +
            "sha256:a7fe349ef4bd8521fb8497f55c6042871b2ae640607cf99d9bede5e9bdf11727"
        )
        OPENSEARCH_IMAGE = "opensearchproject/opensearch:2.17.1"
        DRIVE_GATEWAY_BIND = "127.0.0.1"
        DRIVE_GATEWAY_PORT = $ApiPort.ToString()
        DRIVE_STORAGE_GATEWAY_BIND = "127.0.0.1"
        DRIVE_STORAGE_GATEWAY_PORT = $StoragePort.ToString()
        DRIVE_GATEWAY_HTTP_CONTAINER_PORT = "8080"
        DRIVE_GATEWAY_SECONDARY_CONTAINER_PORT = "9000"
        DRIVE_GATEWAY_TEMPLATE_PATH = "./deploy/windows/nginx/default.conf.template"
        DRIVE_SERVER_NAME = "localhost"
        DRIVE_STORAGE_SERVER_NAME = "storage.localhost"
        DRIVE_S3_PUBLIC_ENDPOINT_URL = "http://localhost:$StoragePort"
        DRIVE_CORS_ORIGINS = "[`"http://localhost:$ApiPort`"]"
        DRIVE_TRUSTED_HOSTS = "[`"localhost`",`"127.0.0.1`"]"
        DRIVE_SESSION_COOKIE_SECURE = "false"
        MINIO_CORS_ALLOWED_ORIGIN = "http://localhost:$ApiPort"
        DRIVE_SECRET_KEY = "Integration-Secret-Key-2026-0123456789abcdef"
        POSTGRES_DB = "enterprise_drive"
        POSTGRES_USER = "drive"
        POSTGRES_PASSWORD = "Integration-Postgres-Secret-2026"
        DRIVE_DATABASE_URL = (
            "postgresql+asyncpg://drive:Integration-Postgres-Secret-2026@" +
            "postgres:5432/enterprise_drive"
        )
        REDIS_PASSWORD = "Integration-Redis-Secret-2026"
        DRIVE_REDIS_URL = "redis://:Integration-Redis-Secret-2026@redis:6379/0"
        DRIVE_CELERY_BROKER_URL = "redis://:Integration-Redis-Secret-2026@redis:6379/1"
        DRIVE_CELERY_RESULT_BACKEND = (
            "redis://:Integration-Redis-Secret-2026@redis:6379/2"
        )
        MINIO_ROOT_USER = "drive"
        MINIO_ROOT_PASSWORD = "Integration-Minio-Secret-2026"
        DRIVE_S3_BUCKET = "enterprise-drive"
        OPENSEARCH_INITIAL_ADMIN_PASSWORD = "Integration-OpenSearch-Secret-2026!"
        DRIVE_ADMIN_PASSWORD = "Integration-Admin-Secret-2026"
        CERTBOT_EMAIL = "ops@contoso.org"
        DRIVE_TLS_CERT_NAME = $CertificateName
        DRIVE_API_WORKERS = "1"
        AUDIT_WORKER_CONCURRENCY = "1"
        PERMISSION_WORKER_CONCURRENCY = "1"
        SEARCH_WORKER_CONCURRENCY = "1"
        MAINTENANCE_WORKER_CONCURRENCY = "1"
        PREVIEW_WORKER_CONCURRENCY = "1"
        PREVIEW_TMPFS_SIZE = "268435456"
        OPENSEARCH_JAVA_OPTS = "-Xms512m -Xmx512m"
        OPENSEARCH_CPU_LIMIT = "1.00"
        OPENSEARCH_MEMORY_LIMIT = "1280m"
        API_CPU_LIMIT = "0.50"
        API_MEMORY_LIMIT = "512m"
        MIGRATION_CPU_LIMIT = "0.50"
        MIGRATION_MEMORY_LIMIT = "512m"
        SEED_CPU_LIMIT = "0.50"
        SEED_MEMORY_LIMIT = "512m"
        AUDIT_WORKER_CPU_LIMIT = "0.25"
        AUDIT_WORKER_MEMORY_LIMIT = "256m"
        PERMISSION_WORKER_CPU_LIMIT = "0.25"
        PERMISSION_WORKER_MEMORY_LIMIT = "256m"
        SEARCH_WORKER_CPU_LIMIT = "0.50"
        SEARCH_WORKER_MEMORY_LIMIT = "384m"
        MAINTENANCE_WORKER_CPU_LIMIT = "0.25"
        MAINTENANCE_WORKER_MEMORY_LIMIT = "384m"
        PREVIEW_WORKER_CPU_LIMIT = "0.50"
        PREVIEW_WORKER_MEMORY_LIMIT = "768m"
        BEAT_CPU_LIMIT = "0.25"
        BEAT_MEMORY_LIMIT = "256m"
        GATEWAY_CPU_LIMIT = "0.25"
        GATEWAY_MEMORY_LIMIT = "128m"
        CERTBOT_CPU_LIMIT = "0.25"
        CERTBOT_MEMORY_LIMIT = "128m"
        POSTGRES_CPU_LIMIT = "0.75"
        POSTGRES_MEMORY_LIMIT = "768m"
        REDIS_CPU_LIMIT = "0.25"
        REDIS_MEMORY_LIMIT = "256m"
        MINIO_CPU_LIMIT = "0.50"
        MINIO_MEMORY_LIMIT = "512m"
        MINIO_INIT_CPU_LIMIT = "0.25"
        MINIO_INIT_MEMORY_LIMIT = "128m"
        DRIVE_BACKUP_HELPER_CPU_LIMIT = "0.25"
        DRIVE_BACKUP_HELPER_MEMORY_LIMIT = "256m"
        DRIVE_BACKUP_HELPER_PIDS_LIMIT = "64"
        DRIVE_BACKUP_GZIP_LEVEL = "1"
        DRIVE_BACKUP_PG_DUMP_COMPRESSION_LEVEL = "1"
    }

    foreach ($Entry in $Values.GetEnumerator()) {
        Set-EnvironmentValue -Name $Entry.Key -Value ([string]$Entry.Value)
    }
}

function Get-ComposeBaseArguments {
    return @(
        "compose",
        "--project-directory", $RepoRoot,
        "--env-file", $EnvFile,
        "--file", $ComposeFile
    )
}

function Invoke-Docker {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $Output = & docker @Arguments
    $ExitCode = $LASTEXITCODE
    if ($ExitCode -ne 0) {
        throw "docker failed with exit code ${ExitCode}: $($Arguments -join ' ')"
    }
    return $Output
}

function Invoke-Compose {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    return Invoke-Docker -Arguments @((Get-ComposeBaseArguments) + $Arguments)
}

function ConvertFrom-DockerJsonOutput {
    param(
        [AllowNull()]
        [object[]]$Output
    )

    $Text = [string](($Output -join "`n").Trim())
    if ([string]::IsNullOrWhiteSpace($Text)) {
        return @()
    }
    try {
        return @($Text | ConvertFrom-Json)
    }
    catch {
        $Items = @()
        foreach ($Line in @($Output)) {
            if (-not [string]::IsNullOrWhiteSpace([string]$Line)) {
                $Items += ([string]$Line | ConvertFrom-Json)
            }
        }
        return @($Items)
    }
}

function Invoke-IntegrationStage {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,

        [Parameter(Mandatory = $true)]
        [scriptblock]$Operation
    )

    $Stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    Write-Host "[integration:start] $Label"
    try {
        $Result = @(& $Operation)
        Write-Host (
            "[integration:done] {0} ({1:N1}s)" -f
            $Label,
            $Stopwatch.Elapsed.TotalSeconds
        )
        return $Result
    }
    catch {
        Write-Host (
            "[integration:failed] {0} ({1:N1}s): {2}" -f
            $Label,
            $Stopwatch.Elapsed.TotalSeconds,
            $_.Exception.Message
        )
        throw
    }
    finally {
        $Stopwatch.Stop()
    }
}

function Assert-IntegrationImagesAvailable {
    $ModelJson = (
        Invoke-Compose -Arguments @("config", "--format", "json")
    ) -join "`n"
    $Model = $ModelJson | ConvertFrom-Json
    $ImageReferences = @(
        $Model.services.PSObject.Properties |
            ForEach-Object { [string]$_.Value.image } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            Sort-Object -Unique
    )
    if ($ImageReferences.Count -eq 0) {
        throw "The rendered Compose model did not contain service images."
    }

    $MissingImages = New-Object "System.Collections.Generic.List[string]"
    foreach ($ImageReference in $ImageReferences) {
        $PreviousErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "SilentlyContinue"
            $null = & docker image inspect `
                --format "{{.Id}}" `
                $ImageReference 2>&1
            $ImageInspectExitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $PreviousErrorActionPreference
        }
        if ($ImageInspectExitCode -ne 0) {
            $MissingImages.Add($ImageReference)
        }
    }
    if ($MissingImages.Count -gt 0) {
        throw (
            "Integration image preflight failed. Build or pull these images " +
            "before running the test; this script does not build or pull: " +
            ($MissingImages -join ", ")
        )
    }
    Write-Host (
        "[integration] image preflight passed: {0} unique images" -f
        $ImageReferences.Count
    )
}

function Wait-IntegrationServices {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$RunningServices,

        [string[]]$ExitedServices = @(),

        [ValidateRange(10, 900)]
        [int]$TimeoutSeconds = 360
    )

    $Deadline = [System.DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $LastSummary = "no containers"
    do {
        $Rows = @(
            ConvertFrom-DockerJsonOutput -Output @(
                Invoke-Compose -Arguments @(
                    "ps",
                    "--all",
                    "--format", "json"
                )
            )
        )
        $Map = @{}
        foreach ($Row in $Rows) {
            $Map[[string]$Row.Service] = $Row
        }

        $Ready = $true
        foreach ($ServiceName in $RunningServices) {
            if (-not $Map.ContainsKey($ServiceName)) {
                $Ready = $false
                continue
            }
            $Row = $Map[$ServiceName]
            $HealthProperty = $Row.PSObject.Properties["Health"]
            $Health = if ($null -eq $HealthProperty) {
                ""
            }
            else {
                [string]$HealthProperty.Value
            }
            if (
                [string]$Row.State -ne "running" -or
                (
                    -not [string]::IsNullOrWhiteSpace($Health) -and
                    $Health -ne "healthy"
                )
            ) {
                $Ready = $false
            }
        }
        foreach ($ServiceName in $ExitedServices) {
            if (-not $Map.ContainsKey($ServiceName)) {
                $Ready = $false
                continue
            }
            $Row = $Map[$ServiceName]
            $ExitCodeProperty = $Row.PSObject.Properties["ExitCode"]
            $ExitCode = if ($null -eq $ExitCodeProperty) {
                -1
            }
            else {
                [int]$ExitCodeProperty.Value
            }
            if (
                [string]$Row.State -ne "exited" -or
                $ExitCode -ne 0
            ) {
                $Ready = $false
            }
        }
        if ($Ready) {
            return
        }

        $LastSummary = [string](
            @(
                $Rows |
                    Sort-Object Service |
                    ForEach-Object {
                        $HealthProperty = $_.PSObject.Properties["Health"]
                        $ExitCodeProperty = $_.PSObject.Properties["ExitCode"]
                        "{0}={1}/{2}/exit:{3}" -f
                        $_.Service,
                        $_.State,
                        $(if ($null -eq $HealthProperty) {
                            ""
                        }
                        else {
                            $HealthProperty.Value
                        }),
                        $(if ($null -eq $ExitCodeProperty) {
                            ""
                        }
                        else {
                            $ExitCodeProperty.Value
                        })
                    }
            ) -join ", "
        )
        Start-Sleep -Seconds 2
    } while ([System.DateTime]::UtcNow -lt $Deadline)

    throw (
        "Compose services did not reach the expected state within " +
        "$TimeoutSeconds seconds. Last state: $LastSummary"
    )
}

function Get-IntegrationHelperRunArguments {
    return @(
        "run",
        "--rm",
        "--pull", "never",
        "--cpus", "0.25",
        "--memory", "128m",
        "--memory-swap", "128m",
        "--pids-limit", "64"
    )
}

function Invoke-Manage {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $Output = New-Object "System.Collections.Generic.List[string]"
    & powershell.exe `
            -NoProfile `
            -NonInteractive `
            -ExecutionPolicy Bypass `
            -File $ManageScript `
            @Arguments 2>&1 |
        ForEach-Object {
            $Line = [string]$_
            $Output.Add($Line)
            Write-Host $Line
        }
    $ExitCode = $LASTEXITCODE
    if ($ExitCode -ne 0) {
        throw "manage.ps1 failed with exit code $ExitCode."
    }
    return @($Output)
}

function Assert-Equal {
    param(
        [AllowNull()]
        [object]$Actual,

        [AllowNull()]
        [object]$Expected,

        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    if ([string]$Actual -ne [string]$Expected) {
        throw "$Label mismatch. Expected '$Expected', actual '$Actual'."
    }
}

function Assert-RestrictedAcl {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    $Expected = New-Object "System.Collections.Generic.HashSet[string]" (
        [System.StringComparer]::OrdinalIgnoreCase
    )
    foreach ($SidValue in @(
        [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value,
        "S-1-5-18",
        "S-1-5-32-544"
    )) {
        $null = $Expected.Add($SidValue)
    }
    $Acl = Get-Acl -LiteralPath $Path
    if (-not $Acl.AreAccessRulesProtected) {
        throw "$Label ACL inheritance is enabled."
    }
    $Actual = New-Object "System.Collections.Generic.HashSet[string]" (
        [System.StringComparer]::OrdinalIgnoreCase
    )
    foreach (
        $Rule in $Acl.GetAccessRules(
            $true,
            $true,
            [System.Security.Principal.SecurityIdentifier]
        )
    ) {
        if (
            $Rule.AccessControlType -ne
            [System.Security.AccessControl.AccessControlType]::Allow
        ) {
            throw "$Label ACL contains a non-allow rule."
        }
        $null = $Actual.Add([string]$Rule.IdentityReference.Value)
    }
    if (
        $Actual.Count -ne $Expected.Count -or
        @($Expected | Where-Object { -not $Actual.Contains($_) }).Count -gt 0
    ) {
        throw "$Label ACL identity set is invalid."
    }
}

function Assert-Throws {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Operation,

        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    try {
        & $Operation
    }
    catch {
        Write-Output "Expected failure verified: $Label"
        return
    }
    throw "Expected failure did not occur: $Label"
}

function Start-IntegrationProject {
    $null = Invoke-Manage -Arguments @("up", "-EnvFile", $EnvFile)
    Wait-IntegrationServices `
        -RunningServices $IntegrationRunningServices `
        -ExitedServices $IntegrationExitedServices `
        -TimeoutSeconds 360
}

function Set-MinioObject {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    $Script = @(
        'mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null',
        'printf "%s" "$PROBE_VALUE" | mc pipe "local/$MINIO_BUCKET/$PROBE_KEY" >/dev/null'
    ) -join "; "
    $ModelJson = (
        Invoke-Compose -Arguments @("config", "--format", "json")
    ) -join "`n"
    $Model = $ModelJson | ConvertFrom-Json
    $BackendNetwork = [string]$Model.networks.backend.name
    $null = Invoke-Docker -Arguments @(
        (Get-IntegrationHelperRunArguments) +
        @(
            "--network", $BackendNetwork,
            "-e", "PROBE_VALUE=$Value",
            "-e", "PROBE_KEY=$ObjectKey",
            "-e", "MINIO_ROOT_USER=$env:MINIO_ROOT_USER",
            "-e", "MINIO_ROOT_PASSWORD=$env:MINIO_ROOT_PASSWORD",
            "-e", "MINIO_BUCKET=$env:DRIVE_S3_BUCKET",
            "--entrypoint", "/bin/sh",
            $env:MINIO_MC_IMAGE,
            "-ec", $Script
        )
    )
}

function Get-MinioObject {
    $Script = @(
        'mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null',
        'mc cat "local/$MINIO_BUCKET/$PROBE_KEY"'
    ) -join "; "
    $ModelJson = (
        Invoke-Compose -Arguments @("config", "--format", "json")
    ) -join "`n"
    $Model = $ModelJson | ConvertFrom-Json
    $BackendNetwork = [string]$Model.networks.backend.name
    $Output = Invoke-Docker -Arguments @(
        (Get-IntegrationHelperRunArguments) +
        @(
            "--network", $BackendNetwork,
            "-e", "PROBE_KEY=$ObjectKey",
            "-e", "MINIO_ROOT_USER=$env:MINIO_ROOT_USER",
            "-e", "MINIO_ROOT_PASSWORD=$env:MINIO_ROOT_PASSWORD",
            "-e", "MINIO_BUCKET=$env:DRIVE_S3_BUCKET",
            "--entrypoint", "/bin/sh",
            $env:MINIO_MC_IMAGE,
            "-ec", $Script
        )
    )
    return [string](($Output -join "`n").Trim())
}

function Remove-IntegrationProject {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectName,

        [Parameter(Mandatory = $true)]
        [int]$ApiPort,

        [Parameter(Mandatory = $true)]
        [int]$StoragePort
    )

    Set-IntegrationEnvironment `
        -ProjectName $ProjectName `
        -ApiPort $ApiPort `
        -StoragePort $StoragePort
    $null = Invoke-Compose -Arguments @(
        "--profile", "tls-tools",
        "down",
        "--remove-orphans",
        "--volumes",
        "--timeout", "60"
    )
}

function Write-IntegrationProjectDiagnostics {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectName,

        [Parameter(Mandatory = $true)]
        [int]$ApiPort,

        [Parameter(Mandatory = $true)]
        [int]$StoragePort
    )

    Set-IntegrationEnvironment `
        -ProjectName $ProjectName `
        -ApiPort $ApiPort `
        -StoragePort $StoragePort
    Write-Host "[integration:diagnostics] project=$ProjectName"

    try {
        Invoke-Compose -Arguments @("ps", "--all") |
            ForEach-Object { Write-Host $_ }
    }
    catch {
        Write-Warning "Compose status diagnostics failed: $($_.Exception.Message)"
    }

    foreach ($ServiceName in @(
        "opensearch",
        "postgres",
        "redis",
        "minio",
        "migration",
        "minio-init",
        "seed",
        "api"
    )) {
        try {
            $ContainerId = [string](
                (
                    Invoke-Compose -Arguments @(
                        "ps",
                        "--all",
                        "--quiet",
                        $ServiceName
                    )
                ) -join ""
            )
            $ContainerId = $ContainerId.Trim()
            if ([string]::IsNullOrWhiteSpace($ContainerId)) {
                continue
            }

            $State = (
                (
                    Invoke-Docker -Arguments @(
                        "inspect",
                        "--format", "{{json .State}}",
                        $ContainerId
                    )
                ) -join "`n"
            ) | ConvertFrom-Json
            $Health = if ($null -eq $State.Health) {
                ""
            }
            else {
                [string]$State.Health.Status
            }
            if (
                [string]$State.Status -eq "running" -and
                (
                    [string]::IsNullOrWhiteSpace($Health) -or
                    $Health -eq "healthy"
                )
            ) {
                continue
            }

            Write-Host (
                "[integration:diagnostics] service={0} status={1} " +
                "health={2} oom_killed={3} exit_code={4}" -f
                $ServiceName,
                $State.Status,
                $Health,
                $State.OOMKilled,
                $State.ExitCode
            )
            Invoke-Compose -Arguments @(
                    "logs",
                    "--no-color",
                    "--tail", "120",
                    $ServiceName
                ) |
                ForEach-Object { Write-Host $_ }
        }
        catch {
            Write-Warning (
                "Diagnostics failed for service '$ServiceName': " +
                $_.Exception.Message
            )
        }
    }
}

$SourceCreated = $false
$TargetCreated = $false
$CmsCertificate = $null
$RestoredEnvironmentPath = $null
$IntegrationFailure = $null
$CleanupErrors = New-Object "System.Collections.Generic.List[string]"
try {
    Set-IntegrationEnvironment `
        -ProjectName $SourceProject `
        -ApiPort $SourceApiPort `
        -StoragePort $SourceStoragePort
    $null = Invoke-IntegrationStage -Label "local image preflight" -Operation {
        Assert-IntegrationImagesAvailable
    }
    if ($PreflightOnly) {
        Write-Output "Backup and restore integration preflight passed."
        return
    }

    $null = New-Item -ItemType Directory -Path $BackupRoot -Force
    $CmsCertificate = New-SelfSignedCertificate `
        -Subject "CN=Enterprise Drive Backup Integration $Suffix" `
        -Type DocumentEncryptionCert `
        -CertStoreLocation "Cert:\CurrentUser\My" `
        -NotAfter ([System.DateTime]::Now.AddDays(2))

    $SourceCreated = $true
    $null = Invoke-IntegrationStage -Label "source Compose startup" -Operation {
        Start-IntegrationProject
    }

    $CreateProbeSql = @(
        "CREATE TABLE IF NOT EXISTS backup_restore_probe (",
        "  probe_key text PRIMARY KEY,",
        "  probe_value text NOT NULL",
        ");",
        "TRUNCATE TABLE backup_restore_probe;",
        "INSERT INTO backup_restore_probe (probe_key, probe_value)",
        "VALUES ('before', '$BeforeValue');"
    ) -join " "
    $null = Invoke-Compose -Arguments @(
        "exec", "--no-TTY",
        "postgres",
        "psql",
        "-U", "drive",
        "-d", "enterprise_drive",
        "-v", "ON_ERROR_STOP=1",
        "-c", $CreateProbeSql
    )

    Set-MinioObject -Value $BeforeValue
    $null = Invoke-Compose -Arguments @(
        "exec", "--no-TTY",
        "redis",
        "redis-cli",
        "SET", $RedisKey, $BeforeValue
    )

    $null = Invoke-Compose -Arguments @(
        "exec", "--no-TTY",
        "opensearch",
        "curl", "-fsS",
        "-XPUT",
        "http://127.0.0.1:9200/$SearchIndex"
    )

    $TlsScript = @(
        "set -eu",
        "mkdir -p '/etc/letsencrypt/archive/$CertificateName'",
        "mkdir -p '/etc/letsencrypt/live/$CertificateName'",
        "mkdir -p /etc/letsencrypt/renewal",
        (
            "openssl req -x509 -newkey rsa:2048 -nodes -days 30 " +
            "-subj '/CN=localhost' " +
            "-addext 'subjectAltName=DNS:localhost,DNS:storage.localhost' " +
            "-keyout '/etc/letsencrypt/archive/$CertificateName/privkey1.pem' " +
            "-out '/etc/letsencrypt/archive/$CertificateName/fullchain1.pem' " +
            ">/dev/null 2>&1"
        ),
        (
            "ln -sf '../../archive/$CertificateName/privkey1.pem' " +
            "'/etc/letsencrypt/live/$CertificateName/privkey.pem'"
        ),
        (
            "ln -sf '../../archive/$CertificateName/fullchain1.pem' " +
            "'/etc/letsencrypt/live/$CertificateName/fullchain.pem'"
        ),
        (
            "printf '%s\n' 'archive_dir = /etc/letsencrypt/archive/$CertificateName' " +
            "> '/etc/letsencrypt/renewal/$CertificateName.conf'"
        )
    ) -join "; "
    $null = Invoke-Compose -Arguments @(
        "--profile", "tls-tools",
        "run", "--rm", "--no-deps",
        "--pull", "never",
        "--entrypoint", "sh",
        "certbot",
        "-ec", $TlsScript
    )

    $AlembicRevision = Invoke-Compose -Arguments @(
        "exec", "--no-TTY",
        "postgres",
        "psql",
        "-U", "drive",
        "-d", "enterprise_drive",
        "-At",
        "-c", "SELECT version_num FROM alembic_version"
    )
    $AlembicRevision = [string](($AlembicRevision -join "").Trim())
    if ([string]::IsNullOrWhiteSpace($AlembicRevision)) {
        throw "Source Alembic revision is empty."
    }

    $null = Invoke-IntegrationStage `
        -Label "backup and publish-time verification" `
        -Operation {
            Invoke-Manage -Arguments @(
                "backup",
                "-EnvFile", $EnvFile,
                "-BackupDirectory", $BackupRoot,
                "-ConfigEncryptionCertificateThumbprint", $CmsCertificate.Thumbprint,
                "-QuiesceTimeoutSeconds", "300"
            )
        }
    $BackupPath = Get-ChildItem -LiteralPath $BackupRoot -Directory |
        Where-Object { -not $_.Name.StartsWith(".partial-") } |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $BackupPath) {
        throw "Published backup directory was not found under $BackupRoot."
    }
    $BackupPath = $BackupPath.FullName
    Assert-RestrictedAcl -Path $BackupPath -Label "Published backup"

    Write-Host (
        "[integration] duplicate successful backup-verify skipped; " +
        "backup already runs the same full verification before publication."
    )
    $EncryptedEnvironmentPath = Join-Path $BackupPath "secrets\environment.cms"
    if (-not (Test-Path -LiteralPath $EncryptedEnvironmentPath -PathType Leaf)) {
        throw "Encrypted environment artifact is missing."
    }
    $EncryptedEnvironmentText = [System.IO.File]::ReadAllText(
        $EncryptedEnvironmentPath
    )
    if ($EncryptedEnvironmentText.Contains("change-me-postgres-password")) {
        throw "Encrypted environment artifact contains plaintext environment data."
    }

    $CorruptPath = Join-Path $BackupRoot "corrupt-$Suffix"
    Copy-Item -LiteralPath $BackupPath -Destination $CorruptPath -Recurse
    [System.IO.File]::WriteAllText(
        (Join-Path $CorruptPath "manifest.sha256"),
        ("0" * 64) + "  manifest.json`n",
        $Utf8NoBom
    )
    Assert-Throws -Label "corrupted manifest checksum" -Operation {
        $null = Invoke-Manage -Arguments @(
            "backup-verify",
            "-EnvFile", $EnvFile,
            "-BackupPath", $CorruptPath
        )
    }
    Remove-Item -LiteralPath $CorruptPath -Recurse -Force

    $PostBackupSql = @(
        "INSERT INTO backup_restore_probe (probe_key, probe_value)",
        "VALUES ('after', '$AfterValue');"
    ) -join " "
    $null = Invoke-Compose -Arguments @(
        "exec", "--no-TTY",
        "postgres",
        "psql",
        "-U", "drive",
        "-d", "enterprise_drive",
        "-v", "ON_ERROR_STOP=1",
        "-c", $PostBackupSql
    )
    Set-MinioObject -Value $AfterValue
    $null = Invoke-IntegrationStage -Label "source Compose stop" -Operation {
        Invoke-Compose -Arguments @("stop", "--timeout", "120")
    }

    Set-IntegrationEnvironment `
        -ProjectName $TargetProject `
        -ApiPort $TargetApiPort `
        -StoragePort $TargetStoragePort
    $TargetCreated = $true
    $RestoredEnvironmentPath = Join-Path `
        ([System.IO.Path]::GetTempPath()) `
        "enterprise-drive-restored-environment-$Suffix.env"
    $RestoreArguments = @(
        "restore",
        "-EnvFile", $EnvFile,
        "-BackupPath", $BackupPath,
        "-RestoreEnvironmentOutput", $RestoredEnvironmentPath
    )
    if (-not $FullStackRestore) {
        $RestoreArguments += "-NoStartAfterRestore"
    }
    $RestoreLabel = if ($FullStackRestore) {
        "restore with full-stack startup"
    }
    else {
        "restore without full-stack startup"
    }
    $null = Invoke-IntegrationStage `
        -Label $RestoreLabel `
        -Operation {
            Invoke-Manage -Arguments $RestoreArguments
        }
    Assert-RestrictedAcl `
        -Path $RestoredEnvironmentPath `
        -Label "Restored environment"

    if (-not $FullStackRestore) {
        $null = Invoke-IntegrationStage `
            -Label "restored data-service startup" `
            -Operation {
                $null = Invoke-Compose -Arguments @(
                    @(
                        "up",
                        "--detach",
                        "--no-deps",
                        "--no-build",
                        "--pull", "never"
                    ) +
                    $DataValidationServices
                )
                Wait-IntegrationServices `
                    -RunningServices $DataValidationServices `
                    -TimeoutSeconds 240
            }
    }

    $DatabaseProbe = Invoke-Compose -Arguments @(
        "exec", "--no-TTY",
        "postgres",
        "psql",
        "-U", "drive",
        "-d", "enterprise_drive",
        "-At",
        "-c", (
            "SELECT string_agg(probe_key || ':' || probe_value, ',' ORDER BY probe_key) " +
            "FROM backup_restore_probe"
        )
    )
    Assert-Equal `
        -Actual (($DatabaseProbe -join "").Trim()) `
        -Expected "before:$BeforeValue" `
        -Label "PostgreSQL restore point"

    Assert-Equal `
        -Actual (Get-MinioObject) `
        -Expected $BeforeValue `
        -Label "MinIO restore point"

    $RedisProbe = Invoke-Compose -Arguments @(
        "exec", "--no-TTY",
        "redis",
        "redis-cli",
        "--raw",
        "GET", $RedisKey
    )
    Assert-Equal `
        -Actual (($RedisProbe -join "").Trim()) `
        -Expected $BeforeValue `
        -Label "Redis restore point"

    $SearchProbe = Invoke-Compose -Arguments @(
        "exec", "--no-TTY",
        "opensearch",
        "curl", "-fsS",
        "http://127.0.0.1:9200/_cat/indices/${SearchIndex}?h=index"
    )
    Assert-Equal `
        -Actual (($SearchProbe -join "").Trim()) `
        -Expected $SearchIndex `
        -Label "OpenSearch restore point"

    $TargetAlembicRevision = Invoke-Compose -Arguments @(
        "exec", "--no-TTY",
        "postgres",
        "psql",
        "-U", "drive",
        "-d", "enterprise_drive",
        "-At",
        "-c", "SELECT version_num FROM alembic_version"
    )
    Assert-Equal `
        -Actual (($TargetAlembicRevision -join "").Trim()) `
        -Expected $AlembicRevision `
        -Label "Alembic revision"

    $TlsVerifyScript = @(
        "test -L '/etc/letsencrypt/live/$CertificateName/fullchain.pem'",
        "test -L '/etc/letsencrypt/live/$CertificateName/privkey.pem'",
        "test -r '/etc/letsencrypt/renewal/$CertificateName.conf'",
        (
            "openssl x509 " +
            "-in '/etc/letsencrypt/live/$CertificateName/fullchain.pem' " +
            "-noout -checkhost localhost >/dev/null"
        ),
        (
            "openssl x509 " +
            "-in '/etc/letsencrypt/live/$CertificateName/fullchain.pem' " +
            "-noout -checkhost storage.localhost >/dev/null"
        )
    ) -join " && "
    $null = Invoke-Compose -Arguments @(
        "--profile", "tls-tools",
        "run", "--rm", "--no-deps",
        "--pull", "never",
        "--entrypoint", "sh",
        "certbot",
        "-ec", $TlsVerifyScript
    )

    if ($FullStackRestore) {
        $Health = Invoke-WebRequest `
            -UseBasicParsing `
            -Uri "http://127.0.0.1:$TargetApiPort/healthz" `
            -TimeoutSec 30
        $Ready = Invoke-WebRequest `
            -UseBasicParsing `
            -Uri "http://127.0.0.1:$TargetApiPort/readyz" `
            -TimeoutSec 30
        Assert-Equal `
            -Actual $Health.StatusCode `
            -Expected 200 `
            -Label "healthz status"
        Assert-Equal `
            -Actual $Ready.StatusCode `
            -Expected 200 `
            -Label "readyz status"
    }

    $StrictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)
    $OriginalEnvironmentText = [System.IO.File]::ReadAllText(
        $EnvFile,
        $StrictUtf8
    ).TrimEnd("`r", "`n")
    $RestoredEnvironmentText = [System.IO.File]::ReadAllText(
        $RestoredEnvironmentPath,
        $StrictUtf8
    ).TrimEnd("`r", "`n")
    Assert-Equal `
        -Actual $RestoredEnvironmentText `
        -Expected $OriginalEnvironmentText `
        -Label "CMS environment restore"

    $ComposeJson = (
        Invoke-Compose -Arguments @("config", "--format", "json")
    ) -join "`n"
    $ComposeModel = $ComposeJson | ConvertFrom-Json
    $PublishedServices = @(
        $ComposeModel.services.PSObject.Properties |
            Where-Object {
                $PortsProperty = $_.Value.PSObject.Properties["ports"]
                $null -ne $PortsProperty -and
                @($PortsProperty.Value).Count -gt 0
            } |
            ForEach-Object { $_.Name }
    )
    Assert-Equal `
        -Actual ($PublishedServices -join ",") `
        -Expected "gateway" `
        -Label "published service boundary"

    $ComposePsOutput = @(
        Invoke-Compose -Arguments @("ps", "--format", "json")
    )
    $ComposePs = @(
        ConvertFrom-DockerJsonOutput -Output $ComposePsOutput
    )
    $RunningServices = @(
        $ComposePs |
            Where-Object { $_.State -eq "running" } |
            ForEach-Object { $_.Service }
    )
    $ExpectedRunningServices = if ($FullStackRestore) {
        $IntegrationRunningServices
    }
    else {
        $DataValidationServices
    }
    foreach ($RequiredService in $ExpectedRunningServices) {
        if ($RequiredService -notin $RunningServices) {
            throw "Restored service is not running: $RequiredService"
        }
    }

    Assert-Throws -Label "restore into a running target project" -Operation {
        $null = Invoke-Manage -Arguments @(
            "restore",
            "-EnvFile", $EnvFile,
            "-BackupPath", $BackupPath,
            "-NoStartAfterRestore"
        )
    }

    Write-Output "Backup and restore integration passed."
    Write-Output "Source project: $SourceProject"
    Write-Output "Target project: $TargetProject"
    Write-Output "Backup path: $BackupPath"
}
catch {
    $IntegrationFailure = $_
    try {
        if ($TargetCreated) {
            Write-IntegrationProjectDiagnostics `
                -ProjectName $TargetProject `
                -ApiPort $TargetApiPort `
                -StoragePort $TargetStoragePort
        }
        elseif ($SourceCreated) {
            Write-IntegrationProjectDiagnostics `
                -ProjectName $SourceProject `
                -ApiPort $SourceApiPort `
                -StoragePort $SourceStoragePort
        }
    }
    catch {
        Write-Warning "Integration diagnostics failed: $($_.Exception.Message)"
    }
}
finally {
    if ($SourceCreated) {
        try {
            Remove-IntegrationProject `
                -ProjectName $SourceProject `
                -ApiPort $SourceApiPort `
                -StoragePort $SourceStoragePort
        }
        catch {
            $CleanupErrors.Add(
                "source project cleanup failed: $($_.Exception.Message)"
            )
        }
    }
    if ($TargetCreated) {
        try {
            Remove-IntegrationProject `
                -ProjectName $TargetProject `
                -ApiPort $TargetApiPort `
                -StoragePort $TargetStoragePort
        }
        catch {
            $CleanupErrors.Add(
                "target project cleanup failed: $($_.Exception.Message)"
            )
        }
    }

    if (-not $KeepArtifacts -and (Test-Path -LiteralPath $BackupRoot)) {
        try {
            $ResolvedBackupRoot = [System.IO.Path]::GetFullPath($BackupRoot)
            $ResolvedTempRoot = [System.IO.Path]::GetFullPath(
                [System.IO.Path]::GetTempPath()
            ).TrimEnd(
                [System.IO.Path]::DirectorySeparatorChar,
                [System.IO.Path]::AltDirectorySeparatorChar
            )
            $TempPrefix = (
                $ResolvedTempRoot +
                [System.IO.Path]::DirectorySeparatorChar
            )
            if (
                -not $ResolvedBackupRoot.StartsWith(
                    $TempPrefix,
                    [System.StringComparison]::OrdinalIgnoreCase
                )
            ) {
                throw "Refusing to remove integration artifacts outside the temp root."
            }
            $BackupRootItem = Get-Item -LiteralPath $ResolvedBackupRoot -Force
            if (
                (
                    $BackupRootItem.Attributes -band
                    [System.IO.FileAttributes]::ReparsePoint
                ) -ne 0
            ) {
                throw "Refusing to remove a reparse-point integration directory."
            }
            Remove-Item -LiteralPath $ResolvedBackupRoot -Recurse -Force
        }
        catch {
            $CleanupErrors.Add(
                "backup artifact cleanup failed: $($_.Exception.Message)"
            )
        }
    }

    if (
        $null -ne $RestoredEnvironmentPath -and
        (Test-Path -LiteralPath $RestoredEnvironmentPath -PathType Leaf)
    ) {
        try {
            Remove-Item -LiteralPath $RestoredEnvironmentPath -Force
        }
        catch {
            $CleanupErrors.Add(
                "restored environment cleanup failed: $($_.Exception.Message)"
            )
        }
    }

    if ($null -ne $CmsCertificate) {
        try {
            $CertificatePath = "Cert:\CurrentUser\My\$($CmsCertificate.Thumbprint)"
            if (Test-Path -LiteralPath $CertificatePath) {
                Remove-Item -LiteralPath $CertificatePath -Force
            }
        }
        catch {
            $CleanupErrors.Add(
                "CMS certificate cleanup failed: $($_.Exception.Message)"
            )
        }
    }

    foreach ($Name in $EnvironmentNames) {
        try {
            Set-EnvironmentValue -Name $Name -Value $OriginalEnvironment[$Name]
        }
        catch {
            $CleanupErrors.Add(
                "environment restoration failed for '$Name': " +
                $_.Exception.Message
            )
        }
    }
}

if ($null -ne $IntegrationFailure) {
    if ($CleanupErrors.Count -gt 0) {
        throw (
            "Integration failed and cleanup also failed: " +
            "$($CleanupErrors -join '; '). Original error: " +
            $IntegrationFailure.Exception.Message
        )
    }
    throw $IntegrationFailure
}
if ($CleanupErrors.Count -gt 0) {
    throw "Integration cleanup failed: $($CleanupErrors -join '; ')"
}
