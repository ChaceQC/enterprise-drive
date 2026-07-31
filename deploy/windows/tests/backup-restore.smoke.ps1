[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $Utf8NoBom
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom

$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\.."))
$SubjectPath = Join-Path $RepoRoot "deploy\windows\backup-restore.ps1"
$ManagePath = Join-Path $RepoRoot "deploy\windows\manage.ps1"
$IntegrationPath = Join-Path (
    $RepoRoot
) "deploy\windows\tests\backup-restore.integration.ps1"
foreach ($RequiredPath in @($SubjectPath, $ManagePath, $IntegrationPath)) {
    if (-not (Test-Path -LiteralPath $RequiredPath -PathType Leaf)) {
        throw "Required Windows deployment script does not exist: $RequiredPath"
    }
}

. $SubjectPath

function Invoke-WindowsDocker {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    throw "Unexpected Docker invocation in smoke test: $($Arguments -join ' ')"
}

function Test-WindowsDocker {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    throw "Unexpected Docker probe in smoke test: $($Arguments -join ' ')"
}

function Write-SmokeUtf8File {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Content
    )

    $Parent = Split-Path -Parent $Path
    if (-not [string]::IsNullOrWhiteSpace($Parent)) {
        $null = New-Item -ItemType Directory -Path $Parent -Force
    }
    [System.IO.File]::WriteAllText($Path, $Content, $Utf8NoBom)
}

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

function Assert-SmokeThrows {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Action,

        [string]$MessagePattern = "*"
    )

    $Failure = $null
    try {
        $null = & $Action
    }
    catch {
        $Failure = $_
    }
    if ($null -eq $Failure) {
        throw "Expected the action to throw."
    }
    if ($Failure.Exception.Message -notlike $MessagePattern) {
        throw (
            "Exception message did not match '$MessagePattern': " +
            $Failure.Exception.Message
        )
    }
}

function Get-SmokeImageId {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ServiceName
    )

    $Encoding = New-Object System.Text.UTF8Encoding($false)
    $Sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $Digest = $Sha256.ComputeHash($Encoding.GetBytes($ServiceName))
    }
    finally {
        $Sha256.Dispose()
    }
    return "sha256:$(-join ($Digest | ForEach-Object { $_.ToString('x2') }))"
}

$script:SmokeDefaultServices = @(
    "api",
    "beat",
    "gateway",
    "migration",
    "minio",
    "minio-init",
    "opensearch",
    "postgres",
    "redis",
    "seed",
    "worker-audit",
    "worker-maintenance",
    "worker-permission",
    "worker-preview",
    "worker-search"
)
$script:SmokeExitedServices = @("migration", "minio-init", "seed")
$script:SmokeLogicalVolumes = @(
    "postgres-data",
    "redis-data",
    "minio-data",
    "opensearch-data",
    "tls-certificates"
)

function New-SmokeComposeModel {
    param(
        [string]$ProjectName = "smoke-target",

        [string]$VolumePrefix = "smoke-target"
    )

    $Services = New-Object psobject
    foreach ($ServiceName in $script:SmokeDefaultServices) {
        $Environment = New-Object psobject
        if ($ServiceName -eq "postgres") {
            $Environment | Add-Member NoteProperty "POSTGRES_USER" "smoke-user"
            $Environment | Add-Member NoteProperty "POSTGRES_DB" "smoke-db"
            $Environment | Add-Member NoteProperty "POSTGRES_PASSWORD" (
                "smoke-password"
            )
        }
        if ($ServiceName -eq "api") {
            $Environment | Add-Member NoteProperty "DRIVE_S3_BUCKET" (
                "smoke-bucket"
            )
            $Environment | Add-Member NoteProperty (
                "DRIVE_OPENSEARCH_INDEX_NAME"
            ) "smoke-index"
        }
        if ($ServiceName -eq "gateway") {
            $Environment | Add-Member NoteProperty "DRIVE_TLS_CERT_NAME" (
                "smoke-certificate"
            )
        }
        $Service = [pscustomobject][ordered]@{
            image = "smoke/$ServiceName`:1"
            environment = $Environment
        }
        $Services | Add-Member NoteProperty $ServiceName $Service
    }

    $Volumes = New-Object psobject
    foreach ($LogicalName in $script:SmokeLogicalVolumes) {
        $Volumes | Add-Member NoteProperty $LogicalName (
            [pscustomobject]@{
                name = "$VolumePrefix-$LogicalName"
            }
        )
    }
    return [pscustomobject][ordered]@{
        name = $ProjectName
        services = $Services
        volumes = $Volumes
        networks = [pscustomobject]@{
            backend = [pscustomobject]@{
                name = "$ProjectName-backend"
            }
        }
    }
}

function New-SmokeManifest {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [object[]]$Artifacts,

        [string]$SourceProject = "smoke-source",

        [string]$SourceVolumePrefix = "smoke-source"
    )

    $ServiceStates = @(
        foreach ($ServiceName in $script:SmokeDefaultServices) {
            $State = if ($ServiceName -in $script:SmokeExitedServices) {
                "exited"
            }
            else {
                "running"
            }
            [pscustomobject][ordered]@{
                service = $ServiceName
                state = $State
                health = if ($State -eq "running") {
                    "healthy"
                }
                else {
                    ""
                }
                exit_code = if ($State -eq "exited") {
                    0
                }
                else {
                    $null
                }
                container_id = "container-$ServiceName"
            }
        }
    )
    $Images = @(
        foreach ($ServiceName in $script:SmokeDefaultServices) {
            [pscustomobject][ordered]@{
                service = $ServiceName
                reference = "smoke/$ServiceName`:1"
                id = Get-SmokeImageId -ServiceName $ServiceName
                repo_digests = @()
                created = "2026-07-15T00:00:00Z"
                source = "container"
                container_id = "container-$ServiceName"
            }
        }
    )
    $Volumes = @(
        foreach ($LogicalName in $script:SmokeLogicalVolumes) {
            [pscustomobject][ordered]@{
                logical_name = $LogicalName
                physical_name = "$SourceVolumePrefix-$LogicalName"
                backup_mode = if ($LogicalName -eq "postgres-data") {
                    "pg_dump"
                }
                else {
                    "stopped-volume-tar"
                }
            }
        }
    )
    return [pscustomobject][ordered]@{
        format_version = 1
        backup_id = ("a" * 32)
        created_at_utc = "2026-07-15T00:00:00.0000000Z"
        quiesced_at_utc = "2026-07-15T00:01:00.0000000Z"
        source_project = $SourceProject
        project_version = "0.3.0"
        git_commit = ("b" * 40)
        compose_sha256 = ("0" * 64)
        archive_tool_image = "smoke/postgres:1"
        archive_tool_image_id = Get-SmokeImageId -ServiceName "postgres"
        running_services = @(
            $ServiceStates |
                Where-Object { $_.state -eq "running" } |
                ForEach-Object { $_.service }
        )
        service_states = $ServiceStates
        artifacts = @($Artifacts)
        volumes = $Volumes
        images = $Images
        database = [pscustomobject][ordered]@{
            name = "smoke-db"
            user = "smoke-user"
            server_version = "16.9"
            alembic_revision = "smoke_revision"
            wal_lsn = "0/ABCDEF"
            dump_format = "custom"
        }
        environment = [pscustomobject][ordered]@{
            included = $false
            protection = "skipped"
            certificate_thumbprint = ""
        }
        configuration = [pscustomobject][ordered]@{
            s3_bucket = "smoke-bucket"
            opensearch_index_name = "smoke-index"
            tls_certificate_name = "smoke-certificate"
        }
    }
}

$script:FakeComposeModel = New-SmokeComposeModel

function Get-WindowsComposeModel {
    param(
        [string[]]$ComposeBaseArguments
    )

    $null = $ComposeBaseArguments
    return $script:FakeComposeModel
}

function Write-SmokeManifest {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Directory,

        [Parameter(Mandatory = $true)]
        [object]$Manifest
    )

    $null = New-Item -ItemType Directory -Path $Directory -Force
    $ManifestPath = Join-Path $Directory "manifest.json"
    $Json = $Manifest | ConvertTo-Json -Depth 12
    Write-SmokeUtf8File -Path $ManifestPath -Content ($Json + "`n")
    $Hash = Get-WindowsSha256 -Path $ManifestPath
    Write-SmokeUtf8File `
        -Path (Join-Path $Directory "manifest.sha256") `
        -Content "$Hash  manifest.json`n"
}

$script:PassedCount = 0
$script:Failures = New-Object "System.Collections.Generic.List[string]"

function Invoke-SmokeCase {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [scriptblock]$Body
    )

    try {
        $null = & $Body
        $script:PassedCount += 1
        Write-Host "ok - $Name"
    }
    catch {
        $Message = "$Name`: $($_.Exception.Message)"
        $script:Failures.Add($Message)
        Write-Host "not ok - $Message"
    }
}

$Suffix = [Guid]::NewGuid().ToString("N")
$TestRoot = Join-Path (
    [System.IO.Path]::GetTempPath()
) "enterprise-drive-backup-smoke-$Suffix"
$CertificatesToRemove = New-Object "System.Collections.Generic.List[string]"
$script:MutexJob = $null
$script:RightCertificate = $null
$script:WrongCertificate = $null

$null = New-Item -ItemType Directory -Path $TestRoot

try {
    Invoke-SmokeCase -Name "backup helper resource settings" -Body {
        $SettingNames = @(
            "DRIVE_BACKUP_HELPER_CPU_LIMIT",
            "DRIVE_BACKUP_HELPER_MEMORY_LIMIT",
            "DRIVE_BACKUP_HELPER_PIDS_LIMIT",
            "DRIVE_BACKUP_GZIP_LEVEL",
            "DRIVE_BACKUP_PG_DUMP_COMPRESSION_LEVEL"
        )
        $OriginalValues = @{}
        foreach ($Name in $SettingNames) {
            $OriginalValues[$Name] = [System.Environment]::GetEnvironmentVariable(
                $Name,
                [System.EnvironmentVariableTarget]::Process
            )
            [System.Environment]::SetEnvironmentVariable(
                $Name,
                $null,
                [System.EnvironmentVariableTarget]::Process
            )
        }

        try {
            $Defaults = Get-WindowsBackupHelperSettings
            Assert-SmokeEqual `
                -Expected "0.50" `
                -Actual $Defaults.cpu_limit `
                -Message "The default backup helper CPU limit changed."
            Assert-SmokeEqual `
                -Expected "512m" `
                -Actual $Defaults.memory_limit `
                -Message "The default backup helper memory limit changed."
            Assert-SmokeEqual `
                -Expected "128" `
                -Actual $Defaults.pids_limit `
                -Message "The default backup helper PID limit changed."
            Assert-SmokeEqual `
                -Expected 1 `
                -Actual $Defaults.gzip_level `
                -Message "The default gzip level changed."
            Assert-SmokeEqual `
                -Expected 1 `
                -Actual $Defaults.pg_dump_compression_level `
                -Message "The default pg_dump compression level changed."

            $Arguments = @(Get-WindowsBackupHelperRunArguments)
            Assert-SmokeEqual `
                -Expected (
                    "--cpus 0.50 --memory 512m --memory-swap 512m " +
                    "--pids-limit 128"
                ) `
                -Actual ($Arguments -join " ") `
                -Message "Backup helper Docker limits are incomplete."

            [System.Environment]::SetEnvironmentVariable(
                "DRIVE_BACKUP_HELPER_CPU_LIMIT",
                "0.25",
                [System.EnvironmentVariableTarget]::Process
            )
            [System.Environment]::SetEnvironmentVariable(
                "DRIVE_BACKUP_HELPER_MEMORY_LIMIT",
                "256m",
                [System.EnvironmentVariableTarget]::Process
            )
            [System.Environment]::SetEnvironmentVariable(
                "DRIVE_BACKUP_HELPER_PIDS_LIMIT",
                "64",
                [System.EnvironmentVariableTarget]::Process
            )
            [System.Environment]::SetEnvironmentVariable(
                "DRIVE_BACKUP_GZIP_LEVEL",
                "3",
                [System.EnvironmentVariableTarget]::Process
            )
            [System.Environment]::SetEnvironmentVariable(
                "DRIVE_BACKUP_PG_DUMP_COMPRESSION_LEVEL",
                "2",
                [System.EnvironmentVariableTarget]::Process
            )
            $Overrides = Get-WindowsBackupHelperSettings
            Assert-SmokeEqual `
                -Expected "0.25" `
                -Actual $Overrides.cpu_limit `
                -Message "The backup helper CPU override was ignored."
            Assert-SmokeEqual `
                -Expected "256m" `
                -Actual $Overrides.memory_limit `
                -Message "The backup helper memory override was ignored."
            Assert-SmokeEqual `
                -Expected "64" `
                -Actual $Overrides.pids_limit `
                -Message "The backup helper PID override was ignored."
            Assert-SmokeEqual `
                -Expected 3 `
                -Actual $Overrides.gzip_level `
                -Message "The gzip override was ignored."
            Assert-SmokeEqual `
                -Expected 2 `
                -Actual $Overrides.pg_dump_compression_level `
                -Message "The pg_dump compression override was ignored."

            [System.Environment]::SetEnvironmentVariable(
                "DRIVE_BACKUP_HELPER_CPU_LIMIT",
                "0",
                [System.EnvironmentVariableTarget]::Process
            )
            Assert-SmokeThrows `
                -MessagePattern "*CPU_LIMIT must be between*" `
                -Action { Get-WindowsBackupHelperSettings }
            [System.Environment]::SetEnvironmentVariable(
                "DRIVE_BACKUP_HELPER_CPU_LIMIT",
                "0.25",
                [System.EnvironmentVariableTarget]::Process
            )
            [System.Environment]::SetEnvironmentVariable(
                "DRIVE_BACKUP_HELPER_MEMORY_LIMIT",
                "unbounded",
                [System.EnvironmentVariableTarget]::Process
            )
            Assert-SmokeThrows `
                -MessagePattern "*invalid Docker memory value*" `
                -Action { Get-WindowsBackupHelperSettings }
            [System.Environment]::SetEnvironmentVariable(
                "DRIVE_BACKUP_HELPER_MEMORY_LIMIT",
                "32m",
                [System.EnvironmentVariableTarget]::Process
            )
            Assert-SmokeThrows `
                -MessagePattern "*MEMORY_LIMIT must be between*" `
                -Action { Get-WindowsBackupHelperSettings }
            [System.Environment]::SetEnvironmentVariable(
                "DRIVE_BACKUP_HELPER_MEMORY_LIMIT",
                "8g",
                [System.EnvironmentVariableTarget]::Process
            )
            Assert-SmokeThrows `
                -MessagePattern "*MEMORY_LIMIT must be between*" `
                -Action { Get-WindowsBackupHelperSettings }
            [System.Environment]::SetEnvironmentVariable(
                "DRIVE_BACKUP_HELPER_MEMORY_LIMIT",
                "256m",
                [System.EnvironmentVariableTarget]::Process
            )
            [System.Environment]::SetEnvironmentVariable(
                "DRIVE_BACKUP_HELPER_PIDS_LIMIT",
                "8",
                [System.EnvironmentVariableTarget]::Process
            )
            Assert-SmokeThrows `
                -MessagePattern "*PIDS_LIMIT must be between*" `
                -Action { Get-WindowsBackupHelperSettings }
            [System.Environment]::SetEnvironmentVariable(
                "DRIVE_BACKUP_HELPER_PIDS_LIMIT",
                "64",
                [System.EnvironmentVariableTarget]::Process
            )
            [System.Environment]::SetEnvironmentVariable(
                "DRIVE_BACKUP_GZIP_LEVEL",
                "10",
                [System.EnvironmentVariableTarget]::Process
            )
            Assert-SmokeThrows `
                -MessagePattern "*GZIP_LEVEL must be between*" `
                -Action { Get-WindowsBackupHelperSettings }
            [System.Environment]::SetEnvironmentVariable(
                "DRIVE_BACKUP_GZIP_LEVEL",
                "1",
                [System.EnvironmentVariableTarget]::Process
            )
            [System.Environment]::SetEnvironmentVariable(
                "DRIVE_BACKUP_PG_DUMP_COMPRESSION_LEVEL",
                "-1",
                [System.EnvironmentVariableTarget]::Process
            )
            Assert-SmokeThrows `
                -MessagePattern "*PG_DUMP_COMPRESSION_LEVEL must be between*" `
                -Action { Get-WindowsBackupHelperSettings }
        }
        finally {
            foreach ($Name in $SettingNames) {
                [System.Environment]::SetEnvironmentVariable(
                    $Name,
                    $OriginalValues[$Name],
                    [System.EnvironmentVariableTarget]::Process
                )
            }
        }
    }

    Invoke-SmokeCase -Name "deployment startup never builds implicitly" -Body {
        $StrictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)
        $ManageText = [System.IO.File]::ReadAllText($ManagePath, $StrictUtf8)
        $IntegrationText = [System.IO.File]::ReadAllText(
            $IntegrationPath,
            $StrictUtf8
        )
        Assert-SmokeTrue `
            -Condition $ManageText.Contains('$Arguments += "--no-build"') `
            -Message "manage.ps1 up does not default to --no-build."
        Assert-SmokeTrue `
            -Condition $ManageText.Contains('$Arguments += @("--pull", "never")') `
            -Message "manage.ps1 up can still pull images implicitly."
        Assert-SmokeTrue `
            -Condition (-not $IntegrationText.Contains('[switch]$BuildImages')) `
            -Message "The backup integration still accepts -BuildImages."
        Assert-SmokeTrue `
            -Condition $IntegrationText.Contains(
                "Assert-IntegrationImagesAvailable"
            ) `
            -Message "The backup integration has no local-image preflight."
        Assert-SmokeTrue `
            -Condition $IntegrationText.Contains(
                'COMPOSE_PARALLEL_LIMIT = "1"'
            ) `
            -Message "The backup integration does not serialize Compose work."
        Assert-SmokeTrue `
            -Condition $IntegrationText.Contains(
                'OPENSEARCH_MEMORY_LIMIT = "1280m"'
            ) `
            -Message "The backup integration OpenSearch memory guard is too small."
        Assert-SmokeTrue `
            -Condition $IntegrationText.Contains(
                "Write-IntegrationProjectDiagnostics"
            ) `
            -Message "The backup integration no longer captures failure diagnostics."
    }

    Invoke-SmokeCase -Name "path boundary checks" -Body {
        $Parent = Join-Path $TestRoot "parent"
        $Child = Join-Path $Parent "child\file.txt"
        $Sibling = "$Parent-sibling\file.txt"

        Assert-SmokeTrue `
            -Condition (Test-WindowsPathWithin -Parent $Parent -Candidate $Parent) `
            -Message "A path must be within itself."
        Assert-SmokeTrue `
            -Condition (Test-WindowsPathWithin -Parent $Parent -Candidate $Child) `
            -Message "A descendant path was rejected."
        Assert-SmokeTrue `
            -Condition (-not (Test-WindowsPathWithin `
                -Parent $Parent `
                -Candidate $Sibling)) `
            -Message "A sibling with the same prefix was accepted."
        Assert-SmokeTrue `
            -Condition (-not (Test-WindowsPathWithin `
                -Parent $Parent `
                -Candidate (Split-Path -Parent $Parent))) `
            -Message "A parent path was accepted as a child."

        Assert-SmokeThrows -MessagePattern "*absolute path*" -Action {
            Resolve-WindowsBackupRoot `
                -RepoRoot $RepoRoot `
                -BackupDirectory "relative-backups"
        }
        Assert-SmokeThrows -MessagePattern "*outside the repository*" -Action {
            Resolve-WindowsBackupRoot `
                -RepoRoot $RepoRoot `
                -BackupDirectory (Join-Path $RepoRoot "backup-smoke")
        }
        Assert-SmokeThrows -MessagePattern "*must not contain the repository*" -Action {
            Resolve-WindowsBackupRoot `
                -RepoRoot $RepoRoot `
                -BackupDirectory (Split-Path -Parent $RepoRoot)
        }
        Assert-SmokeThrows -MessagePattern "*volume root*" -Action {
            Resolve-WindowsBackupRoot `
                -RepoRoot $RepoRoot `
                -BackupDirectory (
                    [System.IO.Path]::GetPathRoot($TestRoot)
                )
        }

        $UnsafeExistingRoot = Join-Path $TestRoot "unsafe-existing-root"
        $null = New-Item -ItemType Directory -Path $UnsafeExistingRoot
        Write-SmokeUtf8File `
            -Path (Join-Path $UnsafeExistingRoot "unrelated.txt") `
            -Content "unrelated"
        $UnsafeAclBefore = (Get-Acl -LiteralPath $UnsafeExistingRoot).Sddl
        Assert-SmokeThrows -MessagePattern "*existing nonempty BackupDirectory*" -Action {
            Resolve-WindowsBackupRoot `
                -RepoRoot $RepoRoot `
                -BackupDirectory $UnsafeExistingRoot
        }
        Assert-SmokeEqual `
            -Expected $UnsafeAclBefore `
            -Actual (Get-Acl -LiteralPath $UnsafeExistingRoot).Sddl `
            -Message "A rejected existing backup root had its ACL changed."

        $ExternalRoot = Join-Path $TestRoot "external-backups"
        $Resolved = Resolve-WindowsBackupRoot `
            -RepoRoot $RepoRoot `
            -BackupDirectory $ExternalRoot
        Assert-SmokeEqual `
            -Expected ([System.IO.Path]::GetFullPath($ExternalRoot)) `
            -Actual $Resolved `
            -Message "The external backup root changed unexpectedly."
        Assert-WindowsRestrictedAcl -Path $Resolved
    }

    Invoke-SmokeCase -Name "artifact traversal checks" -Body {
        $BackupRoot = Join-Path $TestRoot "artifact-root"
        $null = New-Item -ItemType Directory -Path $BackupRoot -Force
        $ValidPath = Resolve-WindowsBackupArtifactPath `
            -BackupRoot $BackupRoot `
            -RelativePath "volumes/minio-data.tar.gz"
        Assert-SmokeEqual `
            -Expected (Join-Path $BackupRoot "volumes\minio-data.tar.gz") `
            -Actual $ValidPath `
            -Message "A valid artifact path resolved incorrectly."

        foreach ($InvalidPath in @(
            "../outside.bin",
            "volumes/../../outside.bin",
            "volumes//outside.bin",
            "volumes\outside.bin",
            "/outside.bin",
            "C:/outside.bin"
        )) {
            Assert-SmokeThrows -MessagePattern "*artifact path is invalid*" -Action {
                Resolve-WindowsBackupArtifactPath `
                    -BackupRoot $BackupRoot `
                    -RelativePath $InvalidPath
            }
        }
    }

    Invoke-SmokeCase -Name "manifest checksum corruption" -Body {
        $BackupPath = Join-Path $TestRoot "bad-manifest-hash"
        Write-SmokeManifest `
            -Directory $BackupPath `
            -Manifest (New-SmokeManifest -Artifacts @())
        Write-SmokeUtf8File `
            -Path (Join-Path $BackupPath "manifest.sha256") `
            -Content "$(('f' * 64))  manifest.json`n"

        Assert-SmokeThrows `
            -MessagePattern "*manifest SHA-256 verification failed*" `
            -Action {
                Test-WindowsBackup `
                    -RepoRoot $RepoRoot `
                    -ComposeFile $SubjectPath `
                    -EnvFile $SubjectPath `
                    -ComposeBaseArguments @("compose") `
                    -BackupPath $BackupPath
            }
    }

    Invoke-SmokeCase -Name "manifest JSON corruption" -Body {
        $BackupPath = Join-Path $TestRoot "bad-manifest-json"
        $null = New-Item -ItemType Directory -Path $BackupPath -Force
        $ManifestPath = Join-Path $BackupPath "manifest.json"
        Write-SmokeUtf8File -Path $ManifestPath -Content "{not-json"
        $Hash = Get-WindowsSha256 -Path $ManifestPath
        Write-SmokeUtf8File `
            -Path (Join-Path $BackupPath "manifest.sha256") `
            -Content "$Hash  manifest.json`n"

        Assert-SmokeThrows -Action {
            Test-WindowsBackup `
                -RepoRoot $RepoRoot `
                -ComposeFile $SubjectPath `
                -EnvFile $SubjectPath `
                -ComposeBaseArguments @("compose") `
                -BackupPath $BackupPath
        }
    }

    Invoke-SmokeCase -Name "manifest artifact traversal" -Body {
        $BackupPath = Join-Path $TestRoot "bad-artifact-path"
        $Artifact = [pscustomobject][ordered]@{
            path = "../outside.bin"
            size_bytes = 0
            sha256 = ("0" * 64)
        }
        Write-SmokeManifest `
            -Directory $BackupPath `
            -Manifest (New-SmokeManifest -Artifacts @($Artifact))

        Assert-SmokeThrows -MessagePattern "*artifact path is invalid*" -Action {
            Test-WindowsBackup `
                -RepoRoot $RepoRoot `
                -ComposeFile $SubjectPath `
                -EnvFile $SubjectPath `
                -ComposeBaseArguments @("compose") `
                -BackupPath $BackupPath
        }
    }

    Invoke-SmokeCase -Name "artifact checksum corruption" -Body {
        $BackupPath = Join-Path $TestRoot "bad-artifact-hash"
        $ArtifactPath = Join-Path $BackupPath "probe.bin"
        Write-SmokeUtf8File -Path $ArtifactPath -Content "smoke-data"
        $Artifact = [pscustomobject][ordered]@{
            path = "probe.bin"
            size_bytes = [int64](Get-Item -LiteralPath $ArtifactPath).Length
            sha256 = ("0" * 64)
        }
        Write-SmokeManifest `
            -Directory $BackupPath `
            -Manifest (New-SmokeManifest -Artifacts @($Artifact))

        Assert-SmokeThrows `
            -MessagePattern "*artifact SHA-256 verification failed*" `
            -Action {
                Test-WindowsBackup `
                    -RepoRoot $RepoRoot `
                    -ComposeFile $SubjectPath `
                    -EnvFile $SubjectPath `
                    -ComposeBaseArguments @("compose") `
                    -BackupPath $BackupPath
            }
    }

    Invoke-SmokeCase -Name "manifest nested data rejection" -Body {
        $BackupPath = Join-Path $TestRoot "bad-nested-manifest"
        $Manifest = New-SmokeManifest -Artifacts @()
        $Manifest.configuration.s3_bucket = ""
        Write-SmokeManifest -Directory $BackupPath -Manifest $Manifest

        Assert-SmokeThrows `
            -MessagePattern "*configuration has an empty 's3_bucket'*" `
            -Action {
                Test-WindowsBackup `
                    -RepoRoot $RepoRoot `
                    -ComposeFile $SubjectPath `
                    -EnvFile $SubjectPath `
                    -ComposeBaseArguments @("compose") `
                    -BackupPath $BackupPath
            }
    }

    Invoke-SmokeCase -Name "deployment mutex contention" -Body {
        $ProjectName = "enterprise-drive-mutex-$Suffix"
        $SignalPath = Join-Path $TestRoot "mutex-ready"
        $script:MutexJob = Start-Job -ScriptBlock {
            param($ScriptPath, $Name, $ReadyPath)

            . $ScriptPath
            $Mutex = Enter-WindowsDeploymentMutex `
                -ProjectName $Name `
                -TimeoutSeconds 5
            try {
                $Encoding = New-Object System.Text.UTF8Encoding($false)
                [System.IO.File]::WriteAllText($ReadyPath, "ready", $Encoding)
                Start-Sleep -Seconds 30
            }
            finally {
                Exit-WindowsDeploymentMutex -Mutex $Mutex
            }
        } -ArgumentList $SubjectPath, $ProjectName, $SignalPath

        $Deadline = [System.DateTime]::UtcNow.AddSeconds(15)
        while (
            -not (Test-Path -LiteralPath $SignalPath -PathType Leaf) -and
            [System.DateTime]::UtcNow -lt $Deadline
        ) {
            if ($script:MutexJob.State -notin @("NotStarted", "Running")) {
                break
            }
            Start-Sleep -Milliseconds 100
        }
        if (-not (Test-Path -LiteralPath $SignalPath -PathType Leaf)) {
            $Details = [string]((
                Receive-Job -Job $script:MutexJob -Keep
            ) -join "`n")
            throw "The mutex holder did not become ready. $Details"
        }

        Assert-SmokeThrows `
            -MessagePattern "*Another deployment maintenance operation is active*" `
            -Action {
                Enter-WindowsDeploymentMutex `
                    -ProjectName $ProjectName `
                    -TimeoutSeconds 0
            }
    }

    if ($null -ne $script:MutexJob) {
        Stop-Job -Job $script:MutexJob -ErrorAction SilentlyContinue
        $null = Wait-Job `
            -Job $script:MutexJob `
            -Timeout 10 `
            -ErrorAction SilentlyContinue
        $null = Receive-Job `
            -Job $script:MutexJob `
            -ErrorAction SilentlyContinue
        Remove-Job `
            -Job $script:MutexJob `
            -Force `
            -ErrorAction SilentlyContinue
        $script:MutexJob = $null
    }

    Invoke-SmokeCase -Name "temporary CMS certificate round trip" -Body {
        $script:RightCertificate = New-SelfSignedCertificate `
            -Subject "CN=Enterprise Drive Smoke Right $Suffix" `
            -Type DocumentEncryptionCert `
            -CertStoreLocation "Cert:\CurrentUser\My" `
            -KeyAlgorithm RSA `
            -KeyLength 2048 `
            -NotAfter (Get-Date).AddHours(1)
        $CertificatesToRemove.Add($script:RightCertificate.Thumbprint)
        $script:WrongCertificate = New-SelfSignedCertificate `
            -Subject "CN=Enterprise Drive Smoke Wrong $Suffix" `
            -Type DocumentEncryptionCert `
            -CertStoreLocation "Cert:\CurrentUser\My" `
            -KeyAlgorithm RSA `
            -KeyLength 2048 `
            -NotAfter (Get-Date).AddHours(1)
        $CertificatesToRemove.Add($script:WrongCertificate.Thumbprint)

        $Located = Get-WindowsCmsCertificate `
            -Thumbprint $script:RightCertificate.Thumbprint.ToLowerInvariant()
        Assert-SmokeEqual `
            -Expected $script:RightCertificate.Thumbprint `
            -Actual $Located.Thumbprint `
            -Message "The CMS certificate lookup returned a different certificate."

        $CmsRoot = Join-Path $TestRoot "cms-backup"
        $CmsPath = Join-Path $CmsRoot "secrets\environment.cms"
        $PlainText = "DRIVE_SECRET_KEY=smoke-$Suffix"
        $Protected = Protect-CmsMessage -To $Located -Content $PlainText
        Write-SmokeUtf8File -Path $CmsPath -Content ([string]$Protected)
        $Decrypted = [string](Unprotect-CmsMessage -Path $CmsPath)
        Assert-SmokeEqual `
            -Expected $PlainText `
            -Actual $Decrypted `
            -Message "CMS encryption and decryption did not round trip."
    }

    $script:FakeRestoreManifest = $null
    $script:FakeComposeModel = New-SmokeComposeModel

    function Test-WindowsBackup {
        param(
            [string]$RepoRoot,
            [string]$ComposeFile,
            [string]$EnvFile,
            [string[]]$ComposeBaseArguments,
            [string]$BackupPath
        )

        $null = $RepoRoot
        $null = $ComposeFile
        $null = $EnvFile
        $null = $ComposeBaseArguments
        $null = $BackupPath
        return $script:FakeRestoreManifest
    }

    function Get-WindowsComposeModel {
        param(
            [string[]]$ComposeBaseArguments
        )

        $null = $ComposeBaseArguments
        return $script:FakeComposeModel
    }

    function Get-WindowsBackupVolumeMap {
        param(
            [object]$ComposeModel
        )

        $Map = @{}
        foreach ($LogicalName in $script:SmokeLogicalVolumes) {
            $Map[$LogicalName] = [string](
                $ComposeModel.volumes.$LogicalName.name
            )
        }
        return $Map
    }

    function Get-WindowsModelServiceImage {
        param(
            [object]$ComposeModel,
            [string]$ServiceName
        )

        $null = $ComposeModel
        return "smoke/$ServiceName`:1"
    }

    function Get-WindowsImageInfo {
        param(
            [string]$Image
        )

        $ServiceName = ($Image -split "/")[-1].Split(":")[0]
        return [pscustomobject]@{
            reference = $Image
            id = Get-SmokeImageId -ServiceName $ServiceName
            repo_digests = @()
            created = "2026-07-15T00:00:00Z"
        }
    }

    function Enter-WindowsDeploymentMutex {
        param(
            [string]$ProjectName,
            [int]$TimeoutSeconds = 0
        )

        $null = $ProjectName
        $null = $TimeoutSeconds
        throw "SMOKE_STOP_AFTER_CMS"
    }

    Invoke-SmokeCase -Name "same project restore guard" -Body {
        $script:FakeRestoreManifest = [pscustomobject]@{
            source_project = "same-project"
        }
        $script:FakeComposeModel = New-SmokeComposeModel `
            -ProjectName "same-project"

        Assert-SmokeThrows `
            -MessagePattern "*requires a different Compose project*" `
            -Action {
                Invoke-WindowsRestore `
                    -RepoRoot $RepoRoot `
                    -ComposeFile $SubjectPath `
                    -EnvFile $SubjectPath `
                    -ComposeBaseArguments @("compose") `
                    -BackupPath $TestRoot
            }
    }

    Invoke-SmokeCase -Name "restore CMS output and existing output guard" -Body {
        $CmsRoot = Join-Path $TestRoot "cms-backup"
        $CmsPath = Join-Path $CmsRoot "secrets\environment.cms"
        Assert-SmokeTrue `
            -Condition (Test-Path -LiteralPath $CmsPath -PathType Leaf) `
            -Message "The encrypted environment artifact is missing."

        $CmsArtifact = [pscustomobject]@{
            path = "secrets/environment.cms"
            size_bytes = [int64](Get-Item -LiteralPath $CmsPath).Length
            sha256 = Get-WindowsSha256 -Path $CmsPath
        }
        $script:FakeRestoreManifest = New-SmokeManifest `
            -Artifacts @($CmsArtifact) `
            -SourceProject "source-project"
        $script:FakeRestoreManifest.environment = [pscustomobject][ordered]@{
            included = $true
            protection = "windows-cms"
            certificate_thumbprint = $script:RightCertificate.Thumbprint
        }
        $script:FakeComposeModel = New-SmokeComposeModel `
            -ProjectName "target-project"

        $OutputPath = Join-Path $TestRoot "restore\environment.env"
        $null = New-Item -ItemType Directory -Path (
            Split-Path -Parent $OutputPath
        ) -Force
        Assert-SmokeThrows -MessagePattern "SMOKE_STOP_AFTER_CMS" -Action {
            Invoke-WindowsRestore `
                -RepoRoot $RepoRoot `
                -ComposeFile $SubjectPath `
                -EnvFile $SubjectPath `
                -ComposeBaseArguments @("compose") `
                -BackupPath $CmsRoot `
                -RestoreEnvironmentOutput $OutputPath
        }
        Assert-SmokeTrue `
            -Condition (-not (Test-Path -LiteralPath $OutputPath)) `
            -Message "CMS output was published before restore mutation completed."

        Write-SmokeUtf8File -Path $OutputPath -Content "existing"
        Assert-SmokeThrows -MessagePattern "*already exists*" -Action {
            Invoke-WindowsRestore `
                -RepoRoot $RepoRoot `
                -ComposeFile $SubjectPath `
                -EnvFile $SubjectPath `
                -ComposeBaseArguments @("compose") `
                -BackupPath $CmsRoot `
                -RestoreEnvironmentOutput $OutputPath
        }
    }

    Invoke-SmokeCase -Name "restore CMS wrong certificate guard" -Body {
        $RightPath = (
            "Cert:\CurrentUser\My\" +
            $script:RightCertificate.Thumbprint
        )
        Remove-Item -LiteralPath $RightPath -Force
        $null = $CertificatesToRemove.Remove(
            $script:RightCertificate.Thumbprint
        )

        $WrongOutputPath = Join-Path $TestRoot "restore\wrong-certificate.env"
        Assert-SmokeThrows -Action {
            Invoke-WindowsRestore `
                -RepoRoot $RepoRoot `
                -ComposeFile $SubjectPath `
                -EnvFile $SubjectPath `
                -ComposeBaseArguments @("compose") `
                -BackupPath (Join-Path $TestRoot "cms-backup") `
                -RestoreEnvironmentOutput $WrongOutputPath
        }
        Assert-SmokeTrue `
            -Condition (-not (Test-Path -LiteralPath $WrongOutputPath)) `
            -Message "A CMS payload was decrypted with the wrong certificate."
        Assert-SmokeThrows -MessagePattern "*certificate was not found*" -Action {
            Get-WindowsCmsCertificate `
                -Thumbprint $script:RightCertificate.Thumbprint
        }
    }

    Invoke-SmokeCase -Name "volume archive uses capped fast compression" -Body {
        $script:CapturedHelperCalls = New-Object (
            "System.Collections.Generic.List[string]"
        )

        function Invoke-WindowsDocker {
            param(
                [Parameter(Mandatory = $true)]
                [string[]]$Arguments
            )

            $script:CapturedHelperCalls.Add(($Arguments -join " "))
            return @()
        }

        $ArchiveRoot = Join-Path $TestRoot "archive-helper"
        $null = New-Item -ItemType Directory -Path (
            Join-Path $ArchiveRoot "volumes"
        ) -Force
        Invoke-WindowsVolumeArchive `
            -ArchiveToolImage "postgres:16-bookworm" `
            -VolumeName "smoke-volume" `
            -BackupDirectory $ArchiveRoot `
            -ArchiveRelativePath "volumes/probe.tar.gz" `
            -SkipImmediateVerification
        Assert-SmokeEqual `
            -Expected 1 `
            -Actual $script:CapturedHelperCalls.Count `
            -Message "The archive helper ran an unexpected number of containers."
        $FastCall = [string]$script:CapturedHelperCalls[0]
        Assert-SmokeTrue `
            -Condition $FastCall.StartsWith(
                "run --rm --pull never --cpus 0.50 --memory 512m " +
                "--memory-swap 512m --pids-limit 128"
            ) `
            -Message "The archive helper did not apply resource limits."
        Assert-SmokeTrue `
            -Condition $FastCall.Contains(
                "--use-compress-program='gzip -1'"
            ) `
            -Message "The archive helper did not use the configured gzip level."
        Assert-SmokeTrue `
            -Condition (-not $FastCall.Contains("tar -tzf")) `
            -Message "The normal backup path still re-lists a new archive immediately."

        Invoke-WindowsVolumeArchive `
            -ArchiveToolImage "postgres:16-bookworm" `
            -VolumeName "smoke-volume" `
            -BackupDirectory $ArchiveRoot `
            -ArchiveRelativePath "volumes/rollback.tar.gz"
        $VerifiedCall = [string]$script:CapturedHelperCalls[1]
        Assert-SmokeTrue `
            -Condition $VerifiedCall.Contains("tar -tzf") `
            -Message "Rollback archive creation skipped its immediate verification."
    }

    function Reset-SmokeStateMachine {
        param(
            [string]$ProjectName = "smoke-target",

            [string]$VolumePrefix = "smoke-target"
        )

        $script:StateDockerCalls = New-Object (
            "System.Collections.Generic.List[string]"
        )
        $script:StateDockerProbes = New-Object (
            "System.Collections.Generic.List[string]"
        )
        $script:StateServices = @{}
        $script:StateComposeProject = $ProjectName
        $script:StateComposeModel = New-SmokeComposeModel `
            -ProjectName $ProjectName `
            -VolumePrefix $VolumePrefix
        $script:StateVolumeMap = [ordered]@{}
        foreach ($LogicalName in $script:SmokeLogicalVolumes) {
            $script:StateVolumeMap[$LogicalName] = [string](
                $script:StateComposeModel.volumes.$LogicalName.name
            )
        }
        $script:StateVolumeInspections = @{}
        $script:StateVolumeEmpty = @{}
        $script:StateVolumeAttachments = @{}
        $script:StateContainerLabels = @{}
        $script:StateRollbackArchives = @{}
        $script:StateVolumeInspectionCalls = New-Object (
            "System.Collections.Generic.List[string]"
        )
        foreach ($LogicalName in $script:SmokeLogicalVolumes) {
            $VolumeName = [string]$script:StateVolumeMap[$LogicalName]
            $script:StateVolumeInspections[$VolumeName] = [pscustomobject]@{
                Name = $VolumeName
                Labels = [pscustomobject]@{
                    "com.docker.compose.project" = $ProjectName
                    "com.docker.compose.volume" = $LogicalName
                }
            }
            $script:StateVolumeEmpty[$VolumeName] = $true
            $script:StateVolumeAttachments[$VolumeName] = @()
        }
        $script:StateRestoreManifest = $null
        $script:StateImageIds = @{}
        foreach ($ServiceName in $script:SmokeDefaultServices) {
            $script:StateImageIds[$ServiceName] = Get-SmokeImageId `
                -ServiceName $ServiceName
        }
        $script:StateDockerFailurePattern = ""
        $script:StatePostgresQueryFailure = ""
        $script:StateAlembicRevision = "smoke_revision"
        $script:StateMutexEnterCount = 0
        $script:StateMutexExitCount = 0
        $script:StateMutexSetEnterCount = 0
        $script:StateMutexSetExitCount = 0
        $script:StateMutexSetResources = @()
    }

    function New-SmokeRestoreManifest {
        param(
            [string]$SourceProject = "smoke-source",

            [string]$PostgresImageId = ""
        )

        $Manifest = New-SmokeManifest `
            -Artifacts @() `
            -SourceProject $SourceProject `
            -SourceVolumePrefix "$SourceProject-source"
        $Manifest.database.alembic_revision = $script:StateAlembicRevision
        if (-not [string]::IsNullOrWhiteSpace($PostgresImageId)) {
            $PostgresImage = @(
                $Manifest.images |
                    Where-Object { $_.service -eq "postgres" }
            )[0]
            $PostgresImage.id = $PostgresImageId
            $Manifest.archive_tool_image_id = $PostgresImageId
        }
        return $Manifest
    }

    function Get-SmokeArgumentIndex {
        param(
            [Parameter(Mandatory = $true)]
            [string[]]$Arguments,

            [Parameter(Mandatory = $true)]
            [string]$Value
        )

        for ($Index = 0; $Index -lt $Arguments.Count; $Index += 1) {
            if ($Arguments[$Index] -eq $Value) {
                return $Index
            }
        }
        return -1
    }

    function Invoke-WindowsDocker {
        param(
            [Parameter(Mandatory = $true)]
            [string[]]$Arguments
        )

        $Call = $Arguments -join " "
        $script:StateDockerCalls.Add($Call)
        if (
            -not [string]::IsNullOrWhiteSpace(
                $script:StateDockerFailurePattern
            ) -and
            $Call -like "*$($script:StateDockerFailurePattern)*"
        ) {
            $FailurePattern = $script:StateDockerFailurePattern
            $script:StateDockerFailurePattern = ""
            throw "SMOKE_DOCKER_FAILURE: $FailurePattern"
        }

        if (
            $Arguments.Count -ge 5 -and
            $Arguments[0] -eq "container" -and
            $Arguments[1] -eq "inspect" -and
            $Arguments[3] -eq "{{.Image}}"
        ) {
            $ContainerId = [string]$Arguments[4]
            $ServiceName = $ContainerId.Substring(
                "container-".Length
            )
            return @($script:StateImageIds[$ServiceName])
        }
        if (
            $Arguments.Count -ge 5 -and
            $Arguments[0] -eq "container" -and
            $Arguments[1] -eq "inspect" -and
            $Arguments[3] -eq "{{json .Config.Labels}}"
        ) {
            $ContainerId = [string]$Arguments[4]
            if (-not $script:StateContainerLabels.ContainsKey($ContainerId)) {
                return @("{}")
            }
            return @(
                $script:StateContainerLabels[$ContainerId] |
                    ConvertTo-Json -Compress
            )
        }
        if (
            $Arguments.Count -ge 6 -and
            $Arguments[0] -eq "ps" -and
            $Arguments[1] -eq "--all" -and
            $Arguments[2] -eq "--filter"
        ) {
            $VolumeName = ([string]$Arguments[3]).Substring(
                "volume=".Length
            )
            return @($script:StateVolumeAttachments[$VolumeName])
        }
        if (
            $Arguments.Count -ge 3 -and
            $Arguments[0] -eq "volume" -and
            $Arguments[1] -eq "create"
        ) {
            $VolumeName = [string]$Arguments[-1]
            $ProjectName = ""
            $LogicalName = ""
            foreach ($Argument in $Arguments) {
                if ($Argument -like "com.docker.compose.project=*") {
                    $ProjectName = $Argument.Split("=", 2)[1]
                }
                if ($Argument -like "com.docker.compose.volume=*") {
                    $LogicalName = $Argument.Split("=", 2)[1]
                }
            }
            $script:StateVolumeInspections[$VolumeName] = [pscustomobject]@{
                Name = $VolumeName
                Labels = [pscustomobject]@{
                    "com.docker.compose.project" = $ProjectName
                    "com.docker.compose.volume" = $LogicalName
                }
            }
            $script:StateVolumeEmpty[$VolumeName] = $true
            $script:StateVolumeAttachments[$VolumeName] = @()
            return @($VolumeName)
        }
        if (
            $Arguments.Count -eq 3 -and
            $Arguments[0] -eq "volume" -and
            $Arguments[1] -eq "rm"
        ) {
            $VolumeName = [string]$Arguments[2]
            $script:StateVolumeInspections.Remove($VolumeName)
            $script:StateVolumeEmpty.Remove($VolumeName)
            $script:StateVolumeAttachments.Remove($VolumeName)
            return @($VolumeName)
        }

        $TargetVolumeMatch = [regex]::Match(
            $Call,
            'type=volume,source=(?<name>[^,\s]+),target=/target'
        )
        if (
            $TargetVolumeMatch.Success -and
            $Call -like '*probe=$(find /target*'
        ) {
            $VolumeName = $TargetVolumeMatch.Groups["name"].Value
            if ([bool]$script:StateVolumeEmpty[$VolumeName]) {
                return @("empty")
            }
            return @("nonempty")
        }
        if (
            $TargetVolumeMatch.Success -and
            $Call -like "*find /target -mindepth 1 -xdev -delete*"
        ) {
            $VolumeName = $TargetVolumeMatch.Groups["name"].Value
            $script:StateVolumeEmpty[$VolumeName] = $true
            return @()
        }
        if (
            $TargetVolumeMatch.Success -and
            $Call -like "*tar --numeric-owner -C /target -xzf*"
        ) {
            $VolumeName = $TargetVolumeMatch.Groups["name"].Value
            $script:StateVolumeEmpty[$VolumeName] = $false
            return @()
        }
        $SourceVolumeMatch = [regex]::Match(
            $Call,
            'type=volume,source=(?<name>[^,\s]+),target=/source,readonly'
        )
        if (
            $SourceVolumeMatch.Success -and
            $Call -like (
                "*tar --numeric-owner --use-compress-program='gzip -*" +
                "-C /source -cf*"
            )
        ) {
            $VolumeName = $SourceVolumeMatch.Groups["name"].Value
            $script:StateRollbackArchives[$Call] = $VolumeName
            return @()
        }

        $StopIndex = Get-SmokeArgumentIndex `
            -Arguments $Arguments `
            -Value "stop"
        if ($StopIndex -ge 0) {
            $ServiceIndex = $StopIndex + 1
            if (
                $ServiceIndex -lt $Arguments.Count -and
                $Arguments[$ServiceIndex] -eq "--timeout"
            ) {
                $ServiceIndex += 2
            }
            for (
                $Index = $ServiceIndex;
                $Index -lt $Arguments.Count;
                $Index += 1
            ) {
                $script:StateServices[$Arguments[$Index]] = "exited"
            }
            return @()
        }

        $StartIndex = Get-SmokeArgumentIndex `
            -Arguments $Arguments `
            -Value "start"
        if ($StartIndex -ge 0) {
            for (
                $Index = $StartIndex + 1;
                $Index -lt $Arguments.Count;
                $Index += 1
            ) {
                $script:StateServices[$Arguments[$Index]] = "running"
            }
            return @()
        }

        $UpIndex = Get-SmokeArgumentIndex `
            -Arguments $Arguments `
            -Value "up"
        if ($UpIndex -ge 0) {
            $NoDepsIndex = Get-SmokeArgumentIndex `
                -Arguments $Arguments `
                -Value "--no-deps"
            if ($NoDepsIndex -ge 0) {
                for (
                    $Index = $NoDepsIndex + 1;
                    $Index -lt $Arguments.Count;
                    $Index += 1
                ) {
                    $script:StateServices[$Arguments[$Index]] = "running"
                }
            }
            else {
                foreach ($ServiceName in $script:SmokeDefaultServices) {
                    $script:StateServices[$ServiceName] = if (
                        $ServiceName -in $script:SmokeExitedServices
                    ) {
                        "exited"
                    }
                    else {
                        "running"
                    }
                }
            }
            return @()
        }

        $DownIndex = Get-SmokeArgumentIndex `
            -Arguments $Arguments `
            -Value "down"
        if ($DownIndex -ge 0) {
            $script:StateServices = @{}
        }
        return @()
    }

    function Test-WindowsDocker {
        param(
            [Parameter(Mandatory = $true)]
            [string[]]$Arguments
        )

        $Call = $Arguments -join " "
        $script:StateDockerProbes.Add($Call)
        throw "Unexpected Docker probe in state smoke test: $Call"
    }

    function Get-WindowsComposeModel {
        param(
            [string[]]$ComposeBaseArguments
        )

        $null = $ComposeBaseArguments
        return $script:StateComposeModel
    }

    function Get-WindowsBackupVolumeMap {
        param(
            [object]$ComposeModel
        )

        $null = $ComposeModel
        return $script:StateVolumeMap
    }

    function Get-WindowsVolumeInspection {
        param(
            [string]$VolumeName
        )

        $script:StateVolumeInspectionCalls.Add($VolumeName)
        if ($script:StateVolumeInspections.ContainsKey($VolumeName)) {
            return $script:StateVolumeInspections[$VolumeName]
        }
        return $null
    }

    function Get-WindowsComposeContainers {
        param(
            [string[]]$ComposeBaseArguments
        )

        $null = $ComposeBaseArguments
        return @(
            foreach ($ServiceName in @($script:StateServices.Keys) |
                Sort-Object) {
                $State = [string]$script:StateServices[$ServiceName]
                [pscustomobject]@{
                    Service = $ServiceName
                    State = $State
                    ID = "container-$ServiceName"
                    Health = if ($State -eq "running") {
                        "healthy"
                    }
                    else {
                        ""
                    }
                    ExitCode = 0
                }
            }
        )
    }

    function Get-WindowsModelServiceImage {
        param(
            [object]$ComposeModel,
            [string]$ServiceName
        )

        return [string]$ComposeModel.services.$ServiceName.image
    }

    function Get-WindowsImageInfo {
        param(
            [string]$Image
        )

        $ServiceName = ($Image -split "/")[-1].Split(":")[0]
        return [pscustomobject]@{
            reference = $Image
            id = $script:StateImageIds[$ServiceName]
            repo_digests = @()
            created = "2026-07-15T00:00:00Z"
        }
    }

    function Get-WindowsModelEnvironmentValue {
        param(
            [object]$ComposeModel,
            [string]$ServiceName,
            [string]$Name
        )

        $Environment = $ComposeModel.services.$ServiceName.environment
        $Property = $Environment.PSObject.Properties[$Name]
        if ($null -eq $Property) {
            throw "Unexpected environment lookup: $ServiceName/$Name"
        }
        return [string]$Property.Value
    }

    function Get-WindowsModelBackendNetwork {
        param(
            [object]$ComposeModel
        )

        return [string]$ComposeModel.networks.backend.name
    }

    function Invoke-WindowsPostgresQuery {
        param(
            [string[]]$ComposeBaseArguments,
            [string]$User,
            [string]$Database,
            [string]$Sql
        )

        $null = $ComposeBaseArguments
        $null = $User
        $null = $Database
        if (-not [string]::IsNullOrWhiteSpace(
            $script:StatePostgresQueryFailure
        )) {
            throw $script:StatePostgresQueryFailure
        }
        if ($Sql -like "*version_num*") {
            return $script:StateAlembicRevision
        }
        if ($Sql -like "*server_version*") {
            return "16.9"
        }
        if ($Sql -like "*wal_lsn*") {
            return "0/SMOKE"
        }
        throw "Unexpected PostgreSQL query: $Sql"
    }

    function Test-WindowsBackup {
        param(
            [string]$RepoRoot,
            [string]$ComposeFile,
            [string]$EnvFile,
            [string[]]$ComposeBaseArguments,
            [string]$BackupPath
        )

        $null = $RepoRoot
        $null = $ComposeFile
        $null = $EnvFile
        $null = $ComposeBaseArguments
        $null = $BackupPath
        return $script:StateRestoreManifest
    }

    function Enter-WindowsDeploymentMutex {
        param(
            [string]$ProjectName,
            [int]$TimeoutSeconds = 0
        )

        $null = $TimeoutSeconds
        $script:StateMutexEnterCount += 1
        return [pscustomobject]@{
            project = $ProjectName
        }
    }

    function Exit-WindowsDeploymentMutex {
        param(
            [object]$Mutex
        )

        $null = $Mutex
        $script:StateMutexExitCount += 1
    }

    function Enter-WindowsDeploymentMutexSet {
        param(
            [string[]]$ResourceNames
        )

        $script:StateMutexSetEnterCount += 1
        $script:StateMutexSetResources = @(
            $ResourceNames | Sort-Object -Unique
        )
        return @(
            foreach ($ResourceName in $script:StateMutexSetResources) {
                [pscustomobject]@{
                    resource = $ResourceName
                }
            }
        )
    }

    function Exit-WindowsDeploymentMutexSet {
        param(
            [AllowEmptyCollection()]
            [object[]]$Mutexes
        )

        $null = $Mutexes
        $script:StateMutexSetExitCount += 1
    }

    Invoke-SmokeCase -Name "restricted ACL validation" -Body {
        $AclPath = Join-Path $TestRoot "restricted-acl"
        $null = New-Item -ItemType Directory -Path $AclPath
        Set-WindowsRestrictedAcl -Path $AclPath -Directory
        Assert-WindowsRestrictedAcl -Path $AclPath

        $null = & icacls.exe $AclPath /grant "*S-1-1-0:(R)"
        if ($LASTEXITCODE -ne 0) {
            throw "icacls failed to add the unexpected ACL identity."
        }
        Assert-SmokeThrows `
            -MessagePattern "*unexpected identity*" `
            -Action {
                Assert-WindowsRestrictedAcl -Path $AclPath
            }
    }

    Invoke-SmokeCase -Name "backup failure restores source state" -Body {
        Reset-SmokeStateMachine `
            -ProjectName "backup-source" `
            -VolumePrefix "backup-source"
        foreach ($ServiceName in $script:SmokeDefaultServices) {
            $script:StateServices[$ServiceName] = if (
                $ServiceName -in $script:SmokeExitedServices -or
                $ServiceName -eq "worker-audit"
            ) {
                "exited"
            }
            else {
                "running"
            }
        }
        $script:StatePostgresQueryFailure = "SMOKE_BACKUP_MID_FAILURE"
        $BackupRoot = Join-Path $TestRoot "backup-state-root"
        $ComposeArguments = @(
            "compose",
            "--project-name",
            "backup-source"
        )

        Assert-SmokeThrows `
            -MessagePattern "*SMOKE_BACKUP_MID_FAILURE*" `
            -Action {
                Invoke-WindowsBackup `
                    -RepoRoot $RepoRoot `
                    -ComposeFile (Join-Path $RepoRoot "compose.windows.yml") `
                    -EnvFile (Join-Path $RepoRoot ".env.windows.example") `
                    -ComposeBaseArguments $ComposeArguments `
                    -BackupDirectory $BackupRoot `
                    -SkipEnvironmentBackup `
                    -QuiesceTimeoutSeconds 30
            }

        foreach ($ServiceName in $script:SmokeDefaultServices) {
            $ExpectedState = if (
                $ServiceName -in $script:SmokeExitedServices -or
                $ServiceName -eq "worker-audit"
            ) {
                "exited"
            }
            else {
                "running"
            }
            Assert-SmokeEqual `
                -Expected $ExpectedState `
                -Actual $script:StateServices[$ServiceName] `
                -Message "Backup recovery state changed for $ServiceName."
        }

        $ExpectedCalls = @(
            "compose --project-name backup-source stop --timeout 30 gateway",
            "compose --project-name backup-source stop --timeout 30 beat api",
            (
                "compose --project-name backup-source stop --timeout 30 " +
                "worker-permission worker-preview worker-search " +
                "worker-maintenance"
            ),
            (
                "compose --project-name backup-source stop --timeout 30 " +
                "minio redis opensearch"
            ),
            (
                "compose --project-name backup-source up --detach --no-deps " +
                "--no-build --pull never redis minio opensearch"
            ),
            (
                "compose --project-name backup-source up --detach --no-deps " +
                "--no-build --pull never api"
            ),
            (
                "compose --project-name backup-source up --detach --no-deps " +
                "--no-build --pull never worker-permission worker-preview worker-search " +
                "worker-maintenance beat"
            ),
            (
                "compose --project-name backup-source up --detach --no-deps " +
                "--no-build --pull never gateway"
            )
        )
        $ComposeCalls = @(
            $script:StateDockerCalls |
                Where-Object { $_ -like "compose *" }
        )
        Assert-SmokeEqual `
            -Expected ($ExpectedCalls -join "`n") `
            -Actual ($ComposeCalls -join "`n") `
            -Message "Backup stop and recovery call order changed."
        Assert-SmokeEqual `
            -Expected 1 `
            -Actual $script:StateMutexEnterCount `
            -Message "Backup did not enter the maintenance mutex once."
        Assert-SmokeEqual `
            -Expected 1 `
            -Actual $script:StateMutexExitCount `
            -Message "Backup did not release the maintenance mutex once."
        Assert-SmokeEqual `
            -Expected 1 `
            -Actual $script:StateMutexSetEnterCount `
            -Message "Backup did not enter the physical volume mutex set."
        Assert-SmokeEqual `
            -Expected 1 `
            -Actual $script:StateMutexSetExitCount `
            -Message "Backup did not release the physical volume mutex set."
        Assert-SmokeEqual `
            -Expected 5 `
            -Actual $script:StateMutexSetResources.Count `
            -Message "Backup did not lock all physical volumes."
        Assert-SmokeEqual `
            -Expected 5 `
            -Actual $script:StateVolumeInspectionCalls.Count `
            -Message "Backup did not inspect every source volume."
        Assert-SmokeEqual `
            -Expected 0 `
            -Actual @(
                Get-ChildItem -LiteralPath $BackupRoot -Force
            ).Count `
            -Message "Failed backup staging content was not removed."
    }

    Invoke-SmokeCase -Name "restore rejects nonempty target volume" -Body {
        Reset-SmokeStateMachine -ProjectName "nonempty-target"
        $script:StateRestoreManifest = New-SmokeRestoreManifest
        $NonemptyVolume = [string]$script:StateVolumeMap["postgres-data"]
        $script:StateVolumeEmpty[$NonemptyVolume] = $false

        Assert-SmokeThrows `
            -MessagePattern "*Target volume is not empty*" `
            -Action {
                Invoke-WindowsRestore `
                    -RepoRoot $RepoRoot `
                    -ComposeFile (Join-Path $RepoRoot "compose.windows.yml") `
                    -EnvFile (Join-Path $RepoRoot ".env.windows.example") `
                    -ComposeBaseArguments @(
                        "compose",
                        "--project-name",
                        "nonempty-target"
                    ) `
                    -BackupPath $TestRoot
        }
        $MutationCalls = @(
            $script:StateDockerCalls |
                Where-Object {
                    $_ -like "volume create*" -or
                    $_ -like "volume rm*" -or
                    $_ -like "compose * up *" -or
                    $_ -like "compose * down *" -or
                    $_ -like "*tar --numeric-owner -C /target -xzf*"
                }
        )
        Assert-SmokeEqual `
            -Expected 0 `
            -Actual $MutationCalls.Count `
            -Message "A rejected nonempty target was mutated."
        Assert-SmokeEqual `
            -Expected 1 `
            -Actual $script:StateMutexExitCount `
            -Message "Nonempty target rejection did not release the mutex."
        Assert-SmokeEqual `
            -Expected 1 `
            -Actual $script:StateMutexSetExitCount `
            -Message "Nonempty target rejection did not release volume mutexes."
    }

    Invoke-SmokeCase -Name "restore rejects physical volume overlap" -Body {
        Reset-SmokeStateMachine -ProjectName "overlap-target"
        $script:StateRestoreManifest = New-SmokeRestoreManifest
        $SourcePostgres = @(
            $script:StateRestoreManifest.volumes |
                Where-Object { $_.logical_name -eq "postgres-data" }
        )[0]
        $SourcePostgres.physical_name = [string](
            $script:StateVolumeMap["postgres-data"]
        )

        Assert-SmokeThrows `
            -MessagePattern "*overlaps a source physical volume*" `
            -Action {
                Invoke-WindowsRestore `
                    -RepoRoot $RepoRoot `
                    -ComposeFile (Join-Path $RepoRoot "compose.windows.yml") `
                    -EnvFile (Join-Path $RepoRoot ".env.windows.example") `
                    -ComposeBaseArguments @(
                        "compose",
                        "--project-name",
                        "overlap-target"
                    ) `
                    -BackupPath $TestRoot
            }
        Assert-SmokeEqual `
            -Expected 0 `
            -Actual $script:StateMutexEnterCount `
            -Message "Physical volume overlap acquired the restore mutex."
    }

    Invoke-SmokeCase -Name "restore rejects incorrect volume label" -Body {
        Reset-SmokeStateMachine -ProjectName "label-target"
        $script:StateRestoreManifest = New-SmokeRestoreManifest
        $VolumeName = [string]$script:StateVolumeMap["redis-data"]
        $script:StateVolumeInspections[$VolumeName].Labels = [pscustomobject]@{
            "com.docker.compose.project" = "other-project"
            "com.docker.compose.volume" = "redis-data"
        }

        Assert-SmokeThrows `
            -MessagePattern "*Compose labels do not match: redis-data*" `
            -Action {
                Invoke-WindowsRestore `
                    -RepoRoot $RepoRoot `
                    -ComposeFile (Join-Path $RepoRoot "compose.windows.yml") `
                    -EnvFile (Join-Path $RepoRoot ".env.windows.example") `
                    -ComposeBaseArguments @(
                        "compose",
                        "--project-name",
                        "label-target"
                    ) `
                    -BackupPath $TestRoot
            }
        Assert-SmokeEqual `
            -Expected 0 `
            -Actual @(
                $script:StateDockerCalls |
                    Where-Object {
                        $_ -like "volume create*" -or
                        $_ -like "compose * up *" -or
                        $_ -like "compose * down *"
                    }
            ).Count `
            -Message "Incorrect target volume labels caused a mutation."
    }

    Invoke-SmokeCase -Name "volume attachment project guard" -Body {
        Reset-SmokeStateMachine -ProjectName "attachment-target"
        $VolumeName = [string]$script:StateVolumeMap["minio-data"]
        $ContainerId = "foreign-container"
        $script:StateVolumeAttachments[$VolumeName] = @($ContainerId)
        $script:StateContainerLabels[$ContainerId] = [pscustomobject]@{
            "com.docker.compose.project" = "foreign-project"
        }

        Assert-SmokeThrows `
            -MessagePattern "*attached to a container outside Compose project*" `
            -Action {
                Assert-WindowsVolumeAttachments `
                    -VolumeName $VolumeName `
                    -ProjectName "attachment-target"
            }
    }

    Invoke-SmokeCase -Name "restore rejects archive image ID mismatch" -Body {
        Reset-SmokeStateMachine -ProjectName "image-target"
        $script:StateRestoreManifest = New-SmokeRestoreManifest `
            -PostgresImageId (
                Get-SmokeImageId -ServiceName "archived-postgres"
            )

        Assert-SmokeThrows `
            -MessagePattern "*reference or ID mismatch for postgres*" `
            -Action {
                Invoke-WindowsRestore `
                    -RepoRoot $RepoRoot `
                    -ComposeFile (Join-Path $RepoRoot "compose.windows.yml") `
                    -EnvFile (Join-Path $RepoRoot ".env.windows.example") `
                    -ComposeBaseArguments @(
                        "compose",
                        "--project-name",
                        "image-target"
                    ) `
                    -BackupPath $TestRoot
            }
        Assert-SmokeEqual `
            -Expected 0 `
            -Actual $script:StateMutexEnterCount `
            -Message "Image mismatch acquired the restore mutex."
        Assert-SmokeEqual `
            -Expected 0 `
            -Actual $script:StateDockerCalls.Count `
            -Message "Image mismatch mutated the target."
    }

    Invoke-SmokeCase -Name "restore no-start leaves services stopped" -Body {
        Reset-SmokeStateMachine -ProjectName "no-start-target"
        $script:StateRestoreManifest = New-SmokeRestoreManifest
        $ComposeArguments = @(
            "compose",
            "--project-name",
            "no-start-target"
        )

        $Result = Invoke-WindowsRestore `
            -RepoRoot $RepoRoot `
            -ComposeFile (Join-Path $RepoRoot "compose.windows.yml") `
            -EnvFile (Join-Path $RepoRoot ".env.windows.example") `
            -ComposeBaseArguments $ComposeArguments `
            -BackupPath $TestRoot `
            -NoStartAfterRestore
        Assert-SmokeTrue `
            -Condition ([string]$Result -like "*Restore completed*") `
            -Message "No-start restore did not complete."
        Assert-SmokeEqual `
            -Expected "exited" `
            -Actual $script:StateServices["postgres"] `
            -Message "No-start restore left PostgreSQL running."
        Assert-SmokeEqual `
            -Expected 0 `
            -Actual @(
                $script:StateDockerCalls |
                    Where-Object {
                        $_ -like "*up --detach --remove-orphans --wait*"
                    }
            ).Count `
            -Message "No-start restore launched the full service set."
        Assert-SmokeEqual `
            -Expected 1 `
            -Actual @(
                $script:StateDockerCalls |
                    Where-Object {
                        $_ -eq (
                            "compose --project-name no-start-target " +
                            "stop --timeout 60 postgres"
                        )
                    }
            ).Count `
            -Message "No-start restore did not stop temporary PostgreSQL."
        Assert-SmokeEqual `
            -Expected 1 `
            -Actual $script:StateMutexExitCount `
            -Message "No-start restore did not release the mutex."
        Assert-SmokeEqual `
            -Expected 1 `
            -Actual $script:StateMutexSetExitCount `
            -Message "No-start restore did not release volume mutexes."
    }

    Invoke-SmokeCase -Name "restore publishes restricted CMS output late" -Body {
        Reset-SmokeStateMachine -ProjectName "cms-publish-target"
        $Certificate = New-SelfSignedCertificate `
            -Subject "CN=Enterprise Drive Smoke Publish $Suffix" `
            -Type DocumentEncryptionCert `
            -CertStoreLocation "Cert:\CurrentUser\My" `
            -KeyAlgorithm RSA `
            -KeyLength 2048 `
            -NotAfter (Get-Date).AddHours(1)
        $CertificatesToRemove.Add($Certificate.Thumbprint)

        $BackupRoot = Join-Path $TestRoot "cms-publish-backup"
        $CmsPath = Join-Path $BackupRoot "secrets\environment.cms"
        $PlainText = "DRIVE_SECRET_KEY=published-$Suffix"
        $Protected = Protect-CmsMessage -To $Certificate -Content $PlainText
        Write-SmokeUtf8File -Path $CmsPath -Content ([string]$Protected)
        $CmsArtifact = [pscustomobject]@{
            path = "secrets/environment.cms"
            size_bytes = [int64](Get-Item -LiteralPath $CmsPath).Length
            sha256 = Get-WindowsSha256 -Path $CmsPath
        }
        $script:StateRestoreManifest = New-SmokeRestoreManifest
        $script:StateRestoreManifest.environment = [pscustomobject][ordered]@{
            included = $true
            protection = "windows-cms"
            certificate_thumbprint = $Certificate.Thumbprint
        }
        $script:StateRestoreManifest.artifacts = @($CmsArtifact)

        $OutputParent = Join-Path $TestRoot "cms-publish-output"
        $null = New-Item -ItemType Directory -Path $OutputParent
        $OutputPath = Join-Path $OutputParent "environment.env"
        $Result = Invoke-WindowsRestore `
            -RepoRoot $RepoRoot `
            -ComposeFile (Join-Path $RepoRoot "compose.windows.yml") `
            -EnvFile (Join-Path $RepoRoot ".env.windows.example") `
            -ComposeBaseArguments @(
                "compose",
                "--project-name",
                "cms-publish-target"
            ) `
            -BackupPath $BackupRoot `
            -RestoreEnvironmentOutput $OutputPath `
            -NoStartAfterRestore

        Assert-SmokeTrue `
            -Condition ([string]$Result -like "*Restore completed*") `
            -Message "CMS publish restore did not complete."
        Assert-SmokeEqual `
            -Expected $PlainText `
            -Actual ([System.IO.File]::ReadAllText($OutputPath, $Utf8NoBom)) `
            -Message "Published CMS environment content changed."
        Assert-WindowsRestrictedAcl -Path $OutputPath
    }

    Invoke-SmokeCase -Name "restore preserves a foreign CMS race file" -Body {
        Reset-SmokeStateMachine -ProjectName "cms-race-target"
        $Certificate = New-SelfSignedCertificate `
            -Subject "CN=Enterprise Drive Smoke Race $Suffix" `
            -Type DocumentEncryptionCert `
            -CertStoreLocation "Cert:\CurrentUser\My" `
            -KeyAlgorithm RSA `
            -KeyLength 2048 `
            -NotAfter (Get-Date).AddHours(1)
        $CertificatesToRemove.Add($Certificate.Thumbprint)

        $BackupRoot = Join-Path $TestRoot "cms-race-backup"
        $CmsPath = Join-Path $BackupRoot "secrets\environment.cms"
        $Protected = Protect-CmsMessage `
            -To $Certificate `
            -Content "DRIVE_SECRET_KEY=race-$Suffix"
        Write-SmokeUtf8File -Path $CmsPath -Content ([string]$Protected)
        $script:StateRestoreManifest = New-SmokeRestoreManifest
        $script:StateRestoreManifest.environment = [pscustomobject][ordered]@{
            included = $true
            protection = "windows-cms"
            certificate_thumbprint = $Certificate.Thumbprint
        }
        $script:StateRestoreManifest.artifacts = @(
            [pscustomobject]@{
                path = "secrets/environment.cms"
                size_bytes = [int64](Get-Item -LiteralPath $CmsPath).Length
                sha256 = Get-WindowsSha256 -Path $CmsPath
            }
        )

        $OutputParent = Join-Path $TestRoot "cms-race-output"
        $null = New-Item -ItemType Directory -Path $OutputParent
        $OutputPath = Join-Path $OutputParent "environment.env"
        $ForeignContent = "FOREIGN_FILE=$Suffix"

        function Write-WindowsRestrictedUtf8File {
            param(
                [string]$Path,
                [string]$Content
            )

            $null = $Content
            [System.IO.File]::WriteAllText(
                $Path,
                $ForeignContent,
                $Utf8NoBom
            )
            throw "SMOKE_CMS_PUBLISH_RACE"
        }

        Assert-SmokeThrows -MessagePattern "*SMOKE_CMS_PUBLISH_RACE*" -Action {
            Invoke-WindowsRestore `
                -RepoRoot $RepoRoot `
                -ComposeFile (Join-Path $RepoRoot "compose.windows.yml") `
                -EnvFile (Join-Path $RepoRoot ".env.windows.example") `
                -ComposeBaseArguments @(
                    "compose",
                    "--project-name",
                    "cms-race-target"
                ) `
                -BackupPath $BackupRoot `
                -RestoreEnvironmentOutput $OutputPath `
                -NoStartAfterRestore
        }
        Assert-SmokeTrue `
            -Condition (Test-Path -LiteralPath $OutputPath -PathType Leaf) `
            -Message "Restore failure deleted a file created by another publisher."
        Assert-SmokeEqual `
            -Expected $ForeignContent `
            -Actual ([System.IO.File]::ReadAllText($OutputPath, $Utf8NoBom)) `
            -Message "Restore failure changed the foreign CMS race file."
    }

    Invoke-SmokeCase -Name "restore failure stops target services" -Body {
        Reset-SmokeStateMachine -ProjectName "failure-target"
        $script:StateRestoreManifest = New-SmokeRestoreManifest
        $PreservedLogicalName = "minio-data"
        $PreservedVolume = [string](
            $script:StateVolumeMap[$PreservedLogicalName]
        )
        $script:StateVolumeEmpty[$PreservedVolume] = $false
        foreach (
            $LogicalName in @(
                $script:SmokeLogicalVolumes |
                    Where-Object { $_ -ne $PreservedLogicalName }
            )
        ) {
            $VolumeName = [string]$script:StateVolumeMap[$LogicalName]
            $script:StateVolumeInspections.Remove($VolumeName)
            $script:StateVolumeEmpty.Remove($VolumeName)
            $script:StateVolumeAttachments.Remove($VolumeName)
        }
        $script:StateDockerFailurePattern = "pg_restore --exit-on-error"
        $ComposeArguments = @(
            "compose",
            "--project-name",
            "failure-target"
        )

        Assert-SmokeThrows `
            -MessagePattern "*SMOKE_DOCKER_FAILURE*" `
            -Action {
                Invoke-WindowsRestore `
                    -RepoRoot $RepoRoot `
                    -ComposeFile (Join-Path $RepoRoot "compose.windows.yml") `
                    -EnvFile (Join-Path $RepoRoot ".env.windows.example") `
                    -ComposeBaseArguments $ComposeArguments `
                    -BackupPath $TestRoot `
                    -ForceRestore
            }
        Assert-SmokeEqual `
            -Expected 0 `
            -Actual @(
                $script:StateServices.GetEnumerator() |
                    Where-Object { $_.Value -eq "running" }
            ).Count `
            -Message "Failed restore left target services running."

        $PostgresUpIndex = -1
        $RestoreFailureIndex = -1
        $CleanupDownIndex = -1
        for (
            $Index = 0;
            $Index -lt $script:StateDockerCalls.Count;
            $Index += 1
        ) {
            $Call = $script:StateDockerCalls[$Index]
            if (
                $Call -like (
                    "*up --detach --no-deps --no-build --pull never postgres"
                )
            ) {
                $PostgresUpIndex = $Index
            }
            if ($Call -like "*pg_restore --exit-on-error*") {
                $RestoreFailureIndex = $Index
            }
            if (
                $Call -eq (
                    "compose --project-name failure-target " +
                    "down --remove-orphans --timeout 60"
                )
            ) {
                $CleanupDownIndex = $Index
            }
        }
        Assert-SmokeTrue `
            -Condition (
                $PostgresUpIndex -ge 0 -and
                $RestoreFailureIndex -gt $PostgresUpIndex -and
                $CleanupDownIndex -gt $RestoreFailureIndex
            ) `
            -Message "Restore failure cleanup call order is incorrect."
        Assert-SmokeEqual `
            -Expected 1 `
            -Actual $script:StateMutexExitCount `
            -Message "Failed restore did not release the mutex."
        Assert-SmokeEqual `
            -Expected 1 `
            -Actual $script:StateMutexSetExitCount `
            -Message "Failed restore did not release volume mutexes."
        Assert-SmokeEqual `
            -Expected 4 `
            -Actual @(
                $script:StateDockerCalls |
                    Where-Object { $_ -like "volume rm *" }
            ).Count `
            -Message "Failed restore did not remove every created volume."
        Assert-SmokeEqual `
            -Expected 1 `
            -Actual $script:StateRollbackArchives.Count `
            -Message "Forced restore did not create a rollback archive."
        Assert-SmokeTrue `
            -Condition (
                $script:StateVolumeInspections.ContainsKey($PreservedVolume)
            ) `
            -Message "Failed restore removed the original nonempty volume."
        Assert-SmokeTrue `
            -Condition (-not [bool]$script:StateVolumeEmpty[$PreservedVolume]) `
            -Message "Failed restore did not repopulate the rollback volume."
        foreach (
            $LogicalName in @(
                $script:SmokeLogicalVolumes |
                    Where-Object { $_ -ne $PreservedLogicalName }
            )
        ) {
            $VolumeName = [string]$script:StateVolumeMap[$LogicalName]
            Assert-SmokeTrue `
                -Condition (
                    -not $script:StateVolumeInspections.ContainsKey($VolumeName)
                ) `
                -Message "Failed restore left a created volume: $VolumeName"
        }
        Assert-SmokeEqual `
            -Expected 0 `
            -Actual @(
                $script:StateDockerCalls |
                    Where-Object {
                        $_ -like "*up --detach --remove-orphans --wait*"
                    }
            ).Count `
            -Message "Failed restore launched the full target service set."
    }

    Invoke-SmokeCase -Name "post-commit rollback cleanup never reverts data" -Body {
        Reset-SmokeStateMachine -ProjectName "commit-cleanup-target"
        $script:StateRestoreManifest = New-SmokeRestoreManifest
        $PreservedLogicalName = "minio-data"
        $PreservedVolume = [string](
            $script:StateVolumeMap[$PreservedLogicalName]
        )
        $script:StateVolumeEmpty[$PreservedVolume] = $false
        $script:CommitRollbackPath = $null

        function Remove-WindowsRestoreRollbackRoot {
            param(
                [string]$Path
            )

            $script:CommitRollbackPath = $Path
            throw "SMOKE_ROLLBACK_CLEANUP_FAILURE"
        }

        try {
            Assert-SmokeThrows `
                -MessagePattern (
                    "*Restore completed, but maintenance cleanup failed*" +
                    "SMOKE_ROLLBACK_CLEANUP_FAILURE*"
                ) `
                -Action {
                    Invoke-WindowsRestore `
                        -RepoRoot $RepoRoot `
                        -ComposeFile (
                            Join-Path $RepoRoot "compose.windows.yml"
                        ) `
                        -EnvFile (
                            Join-Path $RepoRoot ".env.windows.example"
                        ) `
                        -ComposeBaseArguments @(
                            "compose",
                            "--project-name",
                            "commit-cleanup-target"
                        ) `
                        -BackupPath $TestRoot `
                        -ForceRestore `
                        -NoStartAfterRestore
                }
            Assert-SmokeTrue `
                -Condition (
                    -not [string]::IsNullOrWhiteSpace(
                        $script:CommitRollbackPath
                    ) -and
                    (Test-Path `
                        -LiteralPath $script:CommitRollbackPath `
                        -PathType Container)
                ) `
                -Message "Post-commit cleanup did not preserve the rollback path."
            Assert-SmokeEqual `
                -Expected 1 `
                -Actual @(
                    $script:StateDockerCalls |
                        Where-Object {
                            $_ -like (
                                "*source=$PreservedVolume,target=/target*" +
                                "find /target -mindepth 1 -xdev -delete*"
                            )
                        }
                ).Count `
                -Message (
                    "Post-commit cleanup failure cleared the restored volume " +
                    "again."
                )
            Assert-SmokeTrue `
                -Condition (
                    -not [bool]$script:StateVolumeEmpty[$PreservedVolume]
                ) `
                -Message "Post-commit cleanup failure reverted restored data."
        }
        finally {
            if (
                -not [string]::IsNullOrWhiteSpace(
                    $script:CommitRollbackPath
                ) -and
                (Test-Path -LiteralPath $script:CommitRollbackPath)
            ) {
                Microsoft.PowerShell.Management\Remove-Item `
                    -LiteralPath $script:CommitRollbackPath `
                    -Recurse `
                    -Force
            }
        }
    }
}
finally {
    if ($null -ne $script:MutexJob) {
        Stop-Job -Job $script:MutexJob -ErrorAction SilentlyContinue
        $null = Wait-Job `
            -Job $script:MutexJob `
            -Timeout 10 `
            -ErrorAction SilentlyContinue
        $null = Receive-Job `
            -Job $script:MutexJob `
            -ErrorAction SilentlyContinue
        Remove-Job `
            -Job $script:MutexJob `
            -Force `
            -ErrorAction SilentlyContinue
    }
    foreach ($Thumbprint in @($CertificatesToRemove)) {
        $CertificatePath = "Cert:\CurrentUser\My\$Thumbprint"
        if (Test-Path -LiteralPath $CertificatePath) {
            Remove-Item -LiteralPath $CertificatePath -Force
        }
    }
    if (Test-Path -LiteralPath $TestRoot) {
        Remove-Item -LiteralPath $TestRoot -Recurse -Force
    }
}

if ($script:Failures.Count -gt 0) {
    throw (
        "Backup and restore smoke tests failed ($($script:Failures.Count)):`n" +
        ($script:Failures -join "`n")
    )
}

Write-Output "Backup and restore smoke tests passed: $script:PassedCount"
