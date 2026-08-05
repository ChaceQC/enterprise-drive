[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet(
        "config",
        "up",
        "down",
        "status",
        "logs",
        "backup",
        "backup-verify",
        "restore",
        "backup-retention",
        "backup-offline-rotate",
        "backup-retention-register",
        "backup-retention-unregister",
        "restore-drill",
        "restore-drill-register",
        "restore-drill-unregister",
        "data-migration-export",
        "data-migration-apply",
        "data-migration-rollback",
        "tls-init",
        "tls-renew",
        "tls-certificates",
        "tls-register-renewal",
        "tls-unregister-renewal",
        "tls-validate-public"
    )]
    [string]$Action = "status",

    [string]$EnvFile = ".env.windows",

    [string]$Service,

    [ValidateRange(1, 10000)]
    [int]$Tail = 200,

    [switch]$Build,

    [switch]$Volumes,

    [switch]$Quiet,

    [switch]$Tls,

    [switch]$Monitoring,

    [string]$BackupDirectory,

    [string]$BackupPath,

    [ValidateRange(0, 3650)]
    [int]$RetentionDays = 0,

    [ValidateRange(0, 1000)]
    [int]$RetentionCount = 0,

    [switch]$ApplyRetention,

    [string]$OfflineBackupDirectory,

    [string]$MigrationDirectory,

    [string]$MigrationPath,

    [string]$MigrationRollbackDirectory,

    [string]$MigrationRecordDirectory,

    [string]$RestoreDrillDirectory,

    [string]$TlsValidationDirectory,

    [ValidatePattern("^[A-Fa-f0-9]{40}$")]
    [string]$ConfigEncryptionCertificateThumbprint,

    [switch]$SkipEnvironmentBackup,

    [ValidatePattern("^[A-Fa-f0-9]{40}$")]
    [string]$BackupSigningCertificateThumbprint,

    [ValidatePattern("^[A-Fa-f0-9]{40}$")]
    [string]$PackageEncryptionCertificateThumbprint,

    [string]$RestoreEnvironmentOutput,

    [switch]$ForceRestore,

    [switch]$NoStartAfterRestore,

    [ValidateRange(30, 3600)]
    [int]$QuiesceTimeoutSeconds = 300,

    [string]$TlsEmail,

    [switch]$TlsStaging,

    [switch]$ForceRenewal,

    [ValidatePattern("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")]
    [string]$TlsRenewalTaskName = "EnterpriseDriveTlsRenewal",

    [ValidatePattern("^(?:[01]\d|2[0-3]):[0-5]\d$")]
    [string]$TlsRenewalAt = "03:17",

    [ValidatePattern("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")]
    [string]$BackupRetentionTaskName = "EnterpriseDriveBackupRetention",

    [ValidatePattern("^(?:[01]\d|2[0-3]):[0-5]\d$")]
    [string]$BackupRetentionAt = "02:13",

    [ValidatePattern("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")]
    [string]$RestoreDrillTaskName = "EnterpriseDriveRestoreDrill",

    [ValidatePattern("^(?:[01]\d|2[0-3]):[0-5]\d$")]
    [string]$RestoreDrillAt = "04:21",

    [ValidateSet(
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday"
    )]
    [string]$RestoreDrillDayOfWeek = "Sunday"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$InvocationParameters = @{}
foreach ($ParameterName in $PSBoundParameters.Keys) {
    $InvocationParameters[$ParameterName] = $PSBoundParameters[$ParameterName]
}

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $Utf8NoBom
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom
$env:PYTHONUTF8 = "1"

$UnregisterTaskParameterName = switch ($Action) {
    "tls-unregister-renewal" { "TlsRenewalTaskName" }
    "backup-retention-unregister" { "BackupRetentionTaskName" }
    "restore-drill-unregister" { "RestoreDrillTaskName" }
    default { $null }
}
if ($null -ne $UnregisterTaskParameterName) {
    foreach ($ParameterName in $InvocationParameters.Keys) {
        if (
            $ParameterName -notin @(
                "Action",
                "EnvFile",
                $UnregisterTaskParameterName
            )
        ) {
            throw "$Action does not accept -$ParameterName."
        }
    }
}

$UnregisterTaskName = switch ($Action) {
    "tls-unregister-renewal" { $TlsRenewalTaskName }
    "backup-retention-unregister" { $BackupRetentionTaskName }
    "restore-drill-unregister" { $RestoreDrillTaskName }
    default { $null }
}
if ($null -ne $UnregisterTaskName) {
    Import-Module ScheduledTasks -ErrorAction Stop
    $ExistingTask = Get-ScheduledTask -TaskPath "\" |
        Where-Object { $_.TaskName -eq $UnregisterTaskName }
    if ($null -ne $ExistingTask) {
        $ExistingTask | Unregister-ScheduledTask -Confirm:$false
    }
    else {
        Write-Output "Scheduled task does not exist: $UnregisterTaskName"
    }
    return
}

$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$ComposeFile = Join-Path $RepoRoot "compose.windows.yml"
$ExampleEnvFile = Join-Path $RepoRoot ".env.windows.example"
$TlsMode = $Tls -or $Action.StartsWith("tls-", [System.StringComparison]::Ordinal)

if (-not [System.IO.Path]::IsPathRooted($EnvFile)) {
    $EnvFile = Join-Path $RepoRoot $EnvFile
}
$EnvFile = [System.IO.Path]::GetFullPath($EnvFile)

if (-not (Test-Path -LiteralPath $ComposeFile -PathType Leaf)) {
    throw "Compose file does not exist: $ComposeFile"
}

if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) {
    if (
        $Action -in @("config", "backup-verify") -and
        (Test-Path -LiteralPath $ExampleEnvFile -PathType Leaf)
    ) {
        $EnvFile = $ExampleEnvFile
    }
    else {
        throw "Environment file does not exist: $EnvFile. Copy .env.windows.example to .env.windows and replace the example secrets."
    }
}

$null = Get-Command docker -ErrorAction Stop

function Read-DotEnvFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $Values = @{}
    $StrictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)
    foreach ($RawLine in [System.IO.File]::ReadAllLines($Path, $StrictUtf8)) {
        $Line = $RawLine.Trim()
        if ([string]::IsNullOrWhiteSpace($Line) -or $Line.StartsWith("#")) {
            continue
        }

        $SeparatorIndex = $Line.IndexOf("=")
        if ($SeparatorIndex -le 0) {
            continue
        }

        $Name = $Line.Substring(0, $SeparatorIndex).Trim()
        $Value = $Line.Substring($SeparatorIndex + 1).Trim()
        if (
            $Value.Length -ge 2 -and
            (
                ($Value.StartsWith('"') -and $Value.EndsWith('"')) -or
                ($Value.StartsWith("'") -and $Value.EndsWith("'"))
            )
        ) {
            $Value = $Value.Substring(1, $Value.Length - 2)
        }
        $Values[$Name] = $Value
    }

    return $Values
}

$EnvValues = Read-DotEnvFile -Path $EnvFile

function Get-ConfigValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [string]$DefaultValue = ""
    )

    $ProcessValue = [System.Environment]::GetEnvironmentVariable(
        $Name,
        [System.EnvironmentVariableTarget]::Process
    )
    if (-not [string]::IsNullOrWhiteSpace($ProcessValue)) {
        return $ProcessValue
    }
    if ($EnvValues.ContainsKey($Name) -and -not [string]::IsNullOrWhiteSpace($EnvValues[$Name])) {
        return [string]$EnvValues[$Name]
    }
    return $DefaultValue
}

function Get-ConfigInteger {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [int]$DefaultValue,

        [Parameter(Mandatory = $true)]
        [int]$Minimum,

        [Parameter(Mandatory = $true)]
        [int]$Maximum
    )

    $Text = Get-ConfigValue `
        -Name $Name `
        -DefaultValue $DefaultValue.ToString(
            [System.Globalization.CultureInfo]::InvariantCulture
        )
    $Value = 0
    if (
        -not [int]::TryParse(
            $Text,
            [System.Globalization.NumberStyles]::Integer,
            [System.Globalization.CultureInfo]::InvariantCulture,
            [ref]$Value
        ) -or
        $Value -lt $Minimum -or
        $Value -gt $Maximum
    ) {
        throw "$Name must be an integer from $Minimum to $Maximum."
    }
    return $Value
}

if ($InvocationParameters.ContainsKey("RetentionDays")) {
    if ($RetentionDays -lt 1) {
        throw "RetentionDays must be from 1 to 3650."
    }
}
else {
    $RetentionDays = Get-ConfigInteger `
        -Name "DRIVE_BACKUP_RETENTION_DAYS" `
        -DefaultValue 35 `
        -Minimum 1 `
        -Maximum 3650
}

if ($InvocationParameters.ContainsKey("RetentionCount")) {
    if ($RetentionCount -lt 1) {
        throw "RetentionCount must be from 1 to 1000."
    }
}
else {
    $RetentionCount = Get-ConfigInteger `
        -Name "DRIVE_BACKUP_RETENTION_COUNT" `
        -DefaultValue 8 `
        -Minimum 1 `
        -Maximum 1000
}

$GovernanceRecordRoot = Get-ConfigValue `
    -Name "DRIVE_GOVERNANCE_RECORD_ROOT" `
    -DefaultValue ""
if (
    [string]::IsNullOrWhiteSpace($RestoreDrillDirectory) -and
    -not [string]::IsNullOrWhiteSpace($GovernanceRecordRoot)
) {
    $RestoreDrillDirectory = Join-Path $GovernanceRecordRoot "restore-drills"
}
if (
    [string]::IsNullOrWhiteSpace($TlsValidationDirectory) -and
    -not [string]::IsNullOrWhiteSpace($GovernanceRecordRoot)
) {
    $TlsValidationDirectory = Join-Path $GovernanceRecordRoot "tls-validations"
}
if (
    [string]::IsNullOrWhiteSpace($MigrationRollbackDirectory) -and
    -not [string]::IsNullOrWhiteSpace($GovernanceRecordRoot)
) {
    $MigrationRollbackDirectory = Join-Path (
        $GovernanceRecordRoot
    ) "data-migration-rollbacks"
}
if (
    [string]::IsNullOrWhiteSpace($MigrationRecordDirectory) -and
    -not [string]::IsNullOrWhiteSpace($GovernanceRecordRoot)
) {
    $MigrationRecordDirectory = Join-Path (
        $GovernanceRecordRoot
    ) "data-migrations"
}

function Set-ProcessEnvironmentValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    [System.Environment]::SetEnvironmentVariable(
        $Name,
        $Value,
        [System.EnvironmentVariableTarget]::Process
    )
}

function Assert-ActionParameters {
    $ScopedParameterNames = @(
        "Service",
        "Tail",
        "Build",
        "Volumes",
        "Quiet",
        "Tls",
        "Monitoring",
        "BackupDirectory",
        "BackupPath",
        "RetentionDays",
        "RetentionCount",
        "ApplyRetention",
        "OfflineBackupDirectory",
        "MigrationDirectory",
        "MigrationPath",
        "MigrationRollbackDirectory",
        "MigrationRecordDirectory",
        "RestoreDrillDirectory",
        "TlsValidationDirectory",
        "ConfigEncryptionCertificateThumbprint",
        "SkipEnvironmentBackup",
        "BackupSigningCertificateThumbprint",
        "PackageEncryptionCertificateThumbprint",
        "RestoreEnvironmentOutput",
        "ForceRestore",
        "NoStartAfterRestore",
        "QuiesceTimeoutSeconds",
        "TlsEmail",
        "TlsStaging",
        "ForceRenewal",
        "TlsRenewalTaskName",
        "TlsRenewalAt",
        "BackupRetentionTaskName",
        "BackupRetentionAt",
        "RestoreDrillTaskName",
        "RestoreDrillAt",
        "RestoreDrillDayOfWeek"
    )

    $AllowedParameterNames = switch ($Action) {
        "config" { @("Quiet", "Tls", "Monitoring") }
        "up" { @("Build", "Tls", "Monitoring") }
        "down" { @("Volumes", "Tls", "Monitoring") }
        "status" { @("Tls", "Monitoring") }
        "logs" { @("Service", "Tail", "Tls", "Monitoring") }
        "backup" {
            @(
                "BackupDirectory",
                "ConfigEncryptionCertificateThumbprint",
                "SkipEnvironmentBackup",
                "BackupSigningCertificateThumbprint",
                "PackageEncryptionCertificateThumbprint",
                "QuiesceTimeoutSeconds"
            )
        }
        "backup-verify" { @("BackupPath") }
        "restore" {
            @(
                "BackupPath",
                "RestoreEnvironmentOutput",
                "ForceRestore",
                "NoStartAfterRestore"
            )
        }
        "backup-retention" {
            @(
                "BackupDirectory",
                "RetentionDays",
                "RetentionCount",
                "ApplyRetention"
            )
        }
        "backup-offline-rotate" {
            @(
                "BackupDirectory",
                "BackupPath",
                "OfflineBackupDirectory",
                "RetentionDays",
                "RetentionCount",
                "ApplyRetention"
            )
        }
        "backup-retention-register" {
            @(
                "BackupDirectory",
                "RetentionDays",
                "RetentionCount",
                "BackupRetentionTaskName",
                "BackupRetentionAt"
            )
        }
        "restore-drill" {
            @(
                "BackupDirectory",
                "BackupPath",
                "RestoreDrillDirectory"
            )
        }
        "restore-drill-register" {
            @(
                "BackupDirectory",
                "RestoreDrillDirectory",
                "RestoreDrillTaskName",
                "RestoreDrillAt",
                "RestoreDrillDayOfWeek"
            )
        }
        "data-migration-export" { @("MigrationDirectory") }
        "data-migration-apply" {
            @(
                "MigrationPath",
                "MigrationRollbackDirectory",
                "MigrationRecordDirectory"
            )
        }
        "data-migration-rollback" {
            @(
                "MigrationPath",
                "MigrationRollbackDirectory",
                "MigrationRecordDirectory"
            )
        }
        "tls-init" { @("Tls", "TlsEmail", "TlsStaging") }
        "tls-renew" { @("Tls", "ForceRenewal") }
        "tls-certificates" { @("Tls") }
        "tls-register-renewal" {
            @("Tls", "TlsRenewalTaskName", "TlsRenewalAt")
        }
        "tls-validate-public" { @("Tls", "TlsValidationDirectory") }
        default { @() }
    }
    foreach ($Name in $ScopedParameterNames) {
        if (
            $InvocationParameters.ContainsKey($Name) -and
            $Name -notin $AllowedParameterNames
        ) {
            throw "$Action does not accept -$Name."
        }
    }

    switch ($Action) {
        "backup" {
            if ([string]::IsNullOrWhiteSpace($BackupDirectory)) {
                throw "backup requires -BackupDirectory."
            }
            if (-not [string]::IsNullOrWhiteSpace($BackupPath)) {
                throw "backup does not accept -BackupPath."
            }
            if (
                -not $SkipEnvironmentBackup -and
                [string]::IsNullOrWhiteSpace($ConfigEncryptionCertificateThumbprint)
            ) {
                throw "backup requires -ConfigEncryptionCertificateThumbprint or -SkipEnvironmentBackup."
            }
            if (
                $SkipEnvironmentBackup -and
                -not [string]::IsNullOrWhiteSpace($ConfigEncryptionCertificateThumbprint)
            ) {
                throw "-SkipEnvironmentBackup cannot be combined with -ConfigEncryptionCertificateThumbprint."
            }
        }
        "backup-verify" {
            if ([string]::IsNullOrWhiteSpace($BackupPath)) {
                throw "backup-verify requires -BackupPath."
            }
        }
        "restore" {
            if ([string]::IsNullOrWhiteSpace($BackupPath)) {
                throw "restore requires -BackupPath."
            }
        }
        "backup-retention" {
            if ([string]::IsNullOrWhiteSpace($BackupDirectory)) {
                throw "backup-retention requires -BackupDirectory."
            }
        }
        "backup-offline-rotate" {
            if (
                [string]::IsNullOrWhiteSpace($BackupPath) -eq
                [string]::IsNullOrWhiteSpace($BackupDirectory)
            ) {
                throw "backup-offline-rotate requires exactly one of -BackupPath or -BackupDirectory."
            }
            if ([string]::IsNullOrWhiteSpace($OfflineBackupDirectory)) {
                throw "backup-offline-rotate requires -OfflineBackupDirectory."
            }
        }
        "backup-retention-register" {
            if ([string]::IsNullOrWhiteSpace($BackupDirectory)) {
                throw "backup-retention-register requires -BackupDirectory."
            }
        }
        "restore-drill" {
            if (
                [string]::IsNullOrWhiteSpace($BackupPath) -eq
                [string]::IsNullOrWhiteSpace($BackupDirectory)
            ) {
                throw "restore-drill requires exactly one of -BackupPath or -BackupDirectory."
            }
            if ([string]::IsNullOrWhiteSpace($RestoreDrillDirectory)) {
                throw (
                    "restore-drill requires -RestoreDrillDirectory or " +
                    "DRIVE_GOVERNANCE_RECORD_ROOT."
                )
            }
        }
        "restore-drill-register" {
            if ([string]::IsNullOrWhiteSpace($BackupDirectory)) {
                throw "restore-drill-register requires -BackupDirectory."
            }
            if ([string]::IsNullOrWhiteSpace($RestoreDrillDirectory)) {
                throw (
                    "restore-drill-register requires -RestoreDrillDirectory or " +
                    "DRIVE_GOVERNANCE_RECORD_ROOT."
                )
            }
        }
        "data-migration-export" {
            if ([string]::IsNullOrWhiteSpace($MigrationDirectory)) {
                throw "data-migration-export requires -MigrationDirectory."
            }
        }
        { $_ -in @("data-migration-apply", "data-migration-rollback") } {
            if ([string]::IsNullOrWhiteSpace($MigrationPath)) {
                throw "$Action requires -MigrationPath."
            }
            if ([string]::IsNullOrWhiteSpace($MigrationRollbackDirectory)) {
                throw (
                    "$Action requires -MigrationRollbackDirectory or " +
                    "DRIVE_GOVERNANCE_RECORD_ROOT."
                )
            }
            if ([string]::IsNullOrWhiteSpace($MigrationRecordDirectory)) {
                throw (
                    "$Action requires -MigrationRecordDirectory or " +
                    "DRIVE_GOVERNANCE_RECORD_ROOT."
                )
            }
        }
        "tls-validate-public" {
            if ([string]::IsNullOrWhiteSpace($TlsValidationDirectory)) {
                throw (
                    "tls-validate-public requires -TlsValidationDirectory or " +
                    "DRIVE_GOVERNANCE_RECORD_ROOT."
                )
            }
        }
    }
}

function Enable-TlsComposeMode {
    param(
        [switch]$Bootstrap
    )

    $TemplatePath = if ($Bootstrap) {
        "./deploy/windows/nginx/acme-bootstrap.conf.template"
    }
    else {
        "./deploy/windows/nginx/tls.conf.template"
    }

    Set-ProcessEnvironmentValue -Name "DRIVE_GATEWAY_TEMPLATE_PATH" -Value $TemplatePath
    Set-ProcessEnvironmentValue -Name "DRIVE_GATEWAY_BIND" -Value (
        Get-ConfigValue -Name "DRIVE_TLS_GATEWAY_BIND" -DefaultValue "0.0.0.0"
    )
    Set-ProcessEnvironmentValue -Name "DRIVE_STORAGE_GATEWAY_BIND" -Value (
        Get-ConfigValue -Name "DRIVE_TLS_GATEWAY_BIND" -DefaultValue "0.0.0.0"
    )
    Set-ProcessEnvironmentValue -Name "DRIVE_GATEWAY_PORT" -Value (
        Get-ConfigValue -Name "DRIVE_TLS_HTTP_PORT" -DefaultValue "80"
    )
    Set-ProcessEnvironmentValue -Name "DRIVE_STORAGE_GATEWAY_PORT" -Value (
        Get-ConfigValue -Name "DRIVE_TLS_HTTPS_PORT" -DefaultValue "443"
    )
    Set-ProcessEnvironmentValue -Name "DRIVE_GATEWAY_HTTP_CONTAINER_PORT" -Value "8080"
    Set-ProcessEnvironmentValue -Name "DRIVE_GATEWAY_SECONDARY_CONTAINER_PORT" -Value "8443"
}

function Assert-PublicDnsName {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    $HostKind = [System.Uri]::CheckHostName($Name)
    if (
        $HostKind -ne [System.UriHostNameType]::Dns -or
        -not $Name.Contains(".") -or
        $Name.Equals("localhost", [System.StringComparison]::OrdinalIgnoreCase) -or
        $Name.EndsWith(".localhost", [System.StringComparison]::OrdinalIgnoreCase)
    ) {
        throw "$Label must use public DNS name syntax. Current value: $Name"
    }
}

function Assert-UrlPasswordMatches {
    param(
        [Parameter(Mandatory = $true)]
        [string]$UrlName,

        [Parameter(Mandatory = $true)]
        [string]$PasswordName
    )

    $UrlText = Get-ConfigValue -Name $UrlName
    $Url = $null
    if (
        -not [System.Uri]::TryCreate(
            $UrlText,
            [System.UriKind]::Absolute,
            [ref]$Url
        ) -or
        [string]::IsNullOrWhiteSpace($Url.UserInfo)
    ) {
        throw "$UrlName must be an absolute URL with encoded credentials."
    }
    $PasswordSeparator = $Url.UserInfo.IndexOf(":")
    if ($PasswordSeparator -lt 0) {
        throw "$UrlName must include a password in its user info."
    }

    try {
        $UrlPassword = [System.Uri]::UnescapeDataString(
            $Url.UserInfo.Substring($PasswordSeparator + 1)
        )
    }
    catch {
        throw "$UrlName contains an invalid percent-encoded password."
    }
    $ExpectedPassword = Get-ConfigValue -Name $PasswordName
    if ($UrlPassword -cne $ExpectedPassword) {
        throw "$UrlName must contain the URL-encoded value of $PasswordName."
    }
}

function Assert-TlsConfiguration {
    param(
        [switch]$RequireEmail,

        [switch]$RequireStandardPorts,

        [switch]$RequirePublicDeployment
    )

    $ApiHost = Get-ConfigValue -Name "DRIVE_SERVER_NAME"
    $StorageHost = Get-ConfigValue -Name "DRIVE_STORAGE_SERVER_NAME"
    Assert-PublicDnsName -Name $ApiHost -Label "DRIVE_SERVER_NAME"
    Assert-PublicDnsName -Name $StorageHost -Label "DRIVE_STORAGE_SERVER_NAME"
    if ($ApiHost.Equals($StorageHost, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "The API and storage DNS names must differ so gateway can route by Host."
    }

    $CertName = Get-ConfigValue -Name "DRIVE_TLS_CERT_NAME" -DefaultValue "enterprise-drive"
    if (
        $CertName -notmatch "^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$" -or
        $CertName.Contains("..")
    ) {
        throw "DRIVE_TLS_CERT_NAME must be 1-64 safe characters, start with a letter or digit, and not contain '..'."
    }

    $HstsMaxAgeText = Get-ConfigValue -Name "DRIVE_TLS_HSTS_MAX_AGE" -DefaultValue "31536000"
    $HstsMaxAge = 0
    if (
        -not [int]::TryParse($HstsMaxAgeText, [ref]$HstsMaxAge) -or
        $HstsMaxAge -lt 0 -or
        $HstsMaxAge -gt 63072000
    ) {
        throw "DRIVE_TLS_HSTS_MAX_AGE must be an integer from 0 to 63072000."
    }

    if ($RequireStandardPorts -or $RequirePublicDeployment) {
        $TlsGatewayBindText = Get-ConfigValue -Name "DRIVE_TLS_GATEWAY_BIND" -DefaultValue "0.0.0.0"
        $TlsGatewayBind = $null
        if (
            -not [System.Net.IPAddress]::TryParse(
                $TlsGatewayBindText,
                [ref]$TlsGatewayBind
            ) -or
            $TlsGatewayBind.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork -or
            [System.Net.IPAddress]::IsLoopback($TlsGatewayBind)
        ) {
            throw "Public TLS mode requires DRIVE_TLS_GATEWAY_BIND to be a non-loopback IPv4 address such as 0.0.0.0."
        }
    }

    if ($RequirePublicDeployment) {
        if ($HstsMaxAge -eq 0) {
            throw "Public production mode requires DRIVE_TLS_HSTS_MAX_AGE greater than 0."
        }

        $PublicS3Endpoint = Get-ConfigValue -Name "DRIVE_S3_PUBLIC_ENDPOINT_URL"
        $PublicS3Uri = $null
        if (
            -not [System.Uri]::TryCreate(
                $PublicS3Endpoint,
                [System.UriKind]::Absolute,
                [ref]$PublicS3Uri
            ) -or
            $PublicS3Uri.Scheme -ne "https" -or
            -not $PublicS3Uri.Host.Equals(
                $StorageHost,
                [System.StringComparison]::OrdinalIgnoreCase
            ) -or
            -not [string]::IsNullOrEmpty($PublicS3Uri.UserInfo) -or
            -not $PublicS3Uri.IsDefaultPort -or
            $PublicS3Uri.AbsolutePath -ne "/" -or
            -not [string]::IsNullOrEmpty($PublicS3Uri.Query) -or
            -not [string]::IsNullOrEmpty($PublicS3Uri.Fragment)
        ) {
            throw "DRIVE_S3_PUBLIC_ENDPOINT_URL must be the HTTPS root URL of the storage DNS name on port 443, without user info."
        }

        $CookieSecure = Get-ConfigValue -Name "DRIVE_SESSION_COOKIE_SECURE"
        if (-not $CookieSecure.Equals("true", [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Public TLS mode requires DRIVE_SESSION_COOKIE_SECURE=true."
        }

        try {
            $TrustedHostsParsed = Get-ConfigValue -Name "DRIVE_TRUSTED_HOSTS" |
                ConvertFrom-Json -ErrorAction Stop
            if ($TrustedHostsParsed -isnot [System.Array]) {
                throw "not-array"
            }
            [string[]]$TrustedHosts = $TrustedHostsParsed
        }
        catch {
            throw "DRIVE_TRUSTED_HOSTS must be a valid JSON array."
        }
        if ($ApiHost -notin $TrustedHosts -or $StorageHost -notin $TrustedHosts) {
            throw "DRIVE_TRUSTED_HOSTS must contain both the API and storage DNS names."
        }
        if (@($TrustedHosts | Where-Object { $_.Contains("*") }).Count -gt 0) {
            throw "Public TLS mode does not allow wildcard DRIVE_TRUSTED_HOSTS entries."
        }

        try {
            $CorsOriginsParsed = Get-ConfigValue -Name "DRIVE_CORS_ORIGINS" |
                ConvertFrom-Json -ErrorAction Stop
            if ($CorsOriginsParsed -isnot [System.Array]) {
                throw "not-array"
            }
            [string[]]$CorsOrigins = $CorsOriginsParsed
        }
        catch {
            throw "DRIVE_CORS_ORIGINS must be a valid JSON array."
        }
        if ($CorsOrigins.Count -eq 0) {
            throw "DRIVE_CORS_ORIGINS must contain at least one HTTPS origin."
        }
        foreach ($Origin in $CorsOrigins) {
            $OriginUri = $null
            if (
                -not [System.Uri]::TryCreate(
                    [string]$Origin,
                    [System.UriKind]::Absolute,
                    [ref]$OriginUri
                ) -or
                $OriginUri.Scheme -ne "https" -or
                -not [string]::IsNullOrEmpty($OriginUri.UserInfo) -or
                $OriginUri.AbsolutePath -ne "/" -or
                -not [string]::IsNullOrEmpty($OriginUri.Query) -or
                -not [string]::IsNullOrEmpty($OriginUri.Fragment)
            ) {
                throw "Every DRIVE_CORS_ORIGINS entry must be an HTTPS origin without user info, a path, query, or fragment."
            }
        }

        [string[]]$CorsOriginTexts = @(
            $CorsOrigins |
                ForEach-Object { [string]$_ } |
                Sort-Object -Unique
        )
        [string[]]$StorageCorsOrigins = @(
            (Get-ConfigValue -Name "DRIVE_S3_CORS_ALLOWED_ORIGINS").Split(",") |
                ForEach-Object { $_.Trim() } |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
                Sort-Object -Unique
        )
        foreach ($Origin in $StorageCorsOrigins) {
            $OriginUri = $null
            if (
                $Origin -eq "*" -or
                -not [System.Uri]::TryCreate(
                    $Origin,
                    [System.UriKind]::Absolute,
                    [ref]$OriginUri
                ) -or
                $OriginUri.Scheme -ne "https" -or
                -not [string]::IsNullOrEmpty($OriginUri.UserInfo) -or
                $OriginUri.AbsolutePath -ne "/" -or
                -not [string]::IsNullOrEmpty($OriginUri.Query) -or
                -not [string]::IsNullOrEmpty($OriginUri.Fragment)
            ) {
                throw "Every DRIVE_S3_CORS_ALLOWED_ORIGINS entry must be an explicit HTTPS origin."
            }
        }
        if ($StorageCorsOrigins.Count -ne $CorsOriginTexts.Count) {
            throw "DRIVE_S3_CORS_ALLOWED_ORIGINS must exactly match DRIVE_CORS_ORIGINS as a comma-separated origin list."
        }
        foreach ($Origin in $CorsOriginTexts) {
            if ($Origin -notin $StorageCorsOrigins) {
                throw "DRIVE_S3_CORS_ALLOWED_ORIGINS must exactly match DRIVE_CORS_ORIGINS as a comma-separated origin list."
            }
        }

        $SecretMinimumLengths = @{
            DRIVE_SECRET_KEY = 32
            POSTGRES_PASSWORD = 16
            REDIS_PASSWORD = 16
            DRIVE_S3_SECRET_ACCESS_KEY = 16
            OPENSEARCH_INITIAL_ADMIN_PASSWORD = 16
            DRIVE_ADMIN_PASSWORD = 16
        }
        foreach ($SecretName in $SecretMinimumLengths.Keys) {
            $SecretValue = Get-ConfigValue -Name $SecretName
            if (
                [string]::IsNullOrWhiteSpace($SecretValue) -or
                $SecretValue.Length -lt $SecretMinimumLengths[$SecretName] -or
                $SecretValue -match "(?i)change[-_ ]?me" -or
                $SecretValue.Contains('$')
            ) {
                throw "$SecretName must be a non-interpolated, non-example value of at least $($SecretMinimumLengths[$SecretName]) characters."
            }
        }
        foreach (
            $UrlName in @(
                "DRIVE_DATABASE_URL",
                "DRIVE_REDIS_URL",
                "DRIVE_CELERY_BROKER_URL",
                "DRIVE_CELERY_RESULT_BACKEND"
            )
        ) {
            $UrlValue = Get-ConfigValue -Name $UrlName
            if (
                [string]::IsNullOrWhiteSpace($UrlValue) -or
                $UrlValue -match "(?i)change[-_ ]?me" -or
                $UrlValue.Contains('$')
            ) {
                throw "$UrlName must be a non-interpolated value that matches the production credentials."
            }
        }
        Assert-UrlPasswordMatches `
            -UrlName "DRIVE_DATABASE_URL" `
            -PasswordName "POSTGRES_PASSWORD"
        foreach (
            $RedisUrlName in @(
                "DRIVE_REDIS_URL",
                "DRIVE_CELERY_BROKER_URL",
                "DRIVE_CELERY_RESULT_BACKEND"
            )
        ) {
            Assert-UrlPasswordMatches `
                -UrlName $RedisUrlName `
                -PasswordName "REDIS_PASSWORD"
        }
    }

    if ($RequireStandardPorts -or $RequireEmail) {
        $TlsHttpPort = Get-ConfigValue -Name "DRIVE_TLS_HTTP_PORT" -DefaultValue "80"
        $TlsHttpsPort = Get-ConfigValue -Name "DRIVE_TLS_HTTPS_PORT" -DefaultValue "443"
        if ($TlsHttpPort -ne "80" -or $TlsHttpsPort -ne "443") {
            throw "ACME HTTP-01 requires DRIVE_TLS_HTTP_PORT=80 and DRIVE_TLS_HTTPS_PORT=443."
        }
    }

    if ($RequireEmail) {
        $Email = if (-not [string]::IsNullOrWhiteSpace($TlsEmail)) {
            $TlsEmail
        }
        else {
            Get-ConfigValue -Name "CERTBOT_EMAIL"
        }
        if ($Email -notmatch "^[^@\s]+@[^@\s]+\.[^@\s]+$") {
            throw "tls-init requires a valid email through -TlsEmail or CERTBOT_EMAIL."
        }
        $EmailDomain = $Email.Substring($Email.LastIndexOf("@") + 1).ToLowerInvariant()
        if (
            $EmailDomain -in @("example.com", "example.org", "example.net", "localhost") -or
            $EmailDomain.EndsWith(".invalid") -or
            $EmailDomain.EndsWith(".test")
        ) {
            throw "tls-init requires a real operational email domain."
        }
    }
}

function Assert-MonitoringConfiguration {
    $AdminUser = Get-ConfigValue -Name "GRAFANA_ADMIN_USER" -DefaultValue "admin"
    if ([string]::IsNullOrWhiteSpace($AdminUser) -or $AdminUser.Length -gt 128) {
        throw "GRAFANA_ADMIN_USER must contain 1-128 characters."
    }

    $AdminPassword = Get-ConfigValue -Name "GRAFANA_ADMIN_PASSWORD"
    if (
        [string]::IsNullOrWhiteSpace($AdminPassword) -or
        $AdminPassword.Length -lt 16 -or
        $AdminPassword -match "(?i)change[-_ ]?me" -or
        $AdminPassword.Contains('$')
    ) {
        throw "Monitoring requires a non-example GRAFANA_ADMIN_PASSWORD of at least 16 characters."
    }

    $RootUrlText = Get-ConfigValue -Name "GRAFANA_ROOT_URL"
    $RootUrl = $null
    if (
        -not [System.Uri]::TryCreate(
            $RootUrlText,
            [System.UriKind]::Absolute,
            [ref]$RootUrl
        ) -or
        $RootUrl.Scheme -notin @("http", "https") -or
        -not [string]::IsNullOrEmpty($RootUrl.UserInfo) -or
        $RootUrl.AbsolutePath -ne "/grafana/" -or
        -not [string]::IsNullOrEmpty($RootUrl.Query) -or
        -not [string]::IsNullOrEmpty($RootUrl.Fragment)
    ) {
        throw "GRAFANA_ROOT_URL must be an HTTP(S) URL ending in /grafana/ without user info, query, or fragment."
    }
    if ($TlsMode) {
        $ApiHost = Get-ConfigValue -Name "DRIVE_SERVER_NAME"
        if (
            $RootUrl.Scheme -ne "https" -or
            -not $RootUrl.Host.Equals(
                $ApiHost,
                [System.StringComparison]::OrdinalIgnoreCase
            ) -or
            -not $RootUrl.IsDefaultPort
        ) {
            throw "TLS monitoring requires GRAFANA_ROOT_URL to use the API HTTPS origin on port 443."
        }
    }

    $WebhookPathText = Get-ConfigValue -Name "ALERTMANAGER_WEBHOOK_URL_FILE"
    if ([string]::IsNullOrWhiteSpace($WebhookPathText)) {
        throw "Monitoring requires ALERTMANAGER_WEBHOOK_URL_FILE."
    }
    $WebhookPath = if ([System.IO.Path]::IsPathRooted($WebhookPathText)) {
        [System.IO.Path]::GetFullPath($WebhookPathText)
    }
    else {
        [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $WebhookPathText))
    }
    $ExampleWebhookPath = [System.IO.Path]::GetFullPath(
        (Join-Path $RepoRoot "deploy\monitoring\secrets\alertmanager-webhook-url.example")
    )
    if ($WebhookPath.Equals(
        $ExampleWebhookPath,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Monitoring requires a non-example Alertmanager webhook URL file."
    }
    if (-not (Test-Path -LiteralPath $WebhookPath -PathType Leaf)) {
        throw "Alertmanager webhook URL file does not exist: $WebhookPath"
    }
    $StrictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)
    $WebhookText = [System.IO.File]::ReadAllText(
        $WebhookPath,
        $StrictUtf8
    ).Trim()
    $WebhookUri = $null
    if (
        -not [System.Uri]::TryCreate(
            $WebhookText,
            [System.UriKind]::Absolute,
            [ref]$WebhookUri
        ) -or
        $WebhookUri.Scheme -notin @("http", "https") -or
        -not [string]::IsNullOrEmpty($WebhookUri.UserInfo) -or
        $WebhookUri.Host -in @("localhost", "127.0.0.1", "::1")
    ) {
        throw "Alertmanager webhook URL file must contain one reachable HTTP(S) URL without user info."
    }
}

if ($TlsMode) {
    Enable-TlsComposeMode
}

$ComposeBaseArguments = @(
    "compose",
    "--project-directory", $RepoRoot,
    "--env-file", $EnvFile,
    "--file", $ComposeFile
)
if ($Monitoring) {
    $ComposeBaseArguments += @("--profile", "monitoring")
}

function Invoke-Compose {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $DockerArguments = @($ComposeBaseArguments + $Arguments)
    & docker @DockerArguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose failed with exit code $LASTEXITCODE"
    }
}

function Assert-DockerEngine {
    & docker info --format "{{.ServerVersion}}" *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Desktop Linux engine is not ready. Start Docker Desktop and retry."
    }
}

function Start-AcmeBootstrapGateway {
    $DockerArguments = @(
        $ComposeBaseArguments +
        @(
            "run",
            "--detach",
            "--no-deps",
            "--pull", "never",
            "--service-ports",
            "gateway"
        )
    )
    $ContainerOutput = & docker @DockerArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to start the temporary ACME bootstrap gateway."
    }
    $ContainerId = [string]($ContainerOutput | Select-Object -Last 1)
    $ContainerId = $ContainerId.Trim()
    if ([string]::IsNullOrWhiteSpace($ContainerId)) {
        throw "The temporary ACME bootstrap gateway did not return a container ID."
    }

    for ($Attempt = 0; $Attempt -lt 45; $Attempt++) {
        $HealthOutput = & docker inspect `
            --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" `
            $ContainerId
        if ($LASTEXITCODE -ne 0) {
            & docker rm --force $ContainerId *> $null
            throw "Failed to inspect the temporary ACME bootstrap gateway."
        }
        $Health = [string](($HealthOutput -join "").Trim())
        if ($Health -eq "healthy") {
            return $ContainerId
        }
        if ($Health -in @("unhealthy", "exited", "dead")) {
            & docker logs --tail 100 $ContainerId
            & docker rm --force $ContainerId *> $null
            throw "The temporary ACME bootstrap gateway entered state: $Health"
        }
        Start-Sleep -Seconds 2
    }

    & docker logs --tail 100 $ContainerId
    & docker rm --force $ContainerId *> $null
    throw "The temporary ACME bootstrap gateway did not become healthy within 90 seconds."
}

function Remove-AcmeBootstrapGateway {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ContainerId
    )

    & docker rm --force $ContainerId *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to remove the temporary ACME bootstrap gateway: $ContainerId"
    }
}

function Test-GatewayRunning {
    $DockerArguments = @($ComposeBaseArguments + @("ps", "--quiet", "gateway"))
    $GatewayId = & docker @DockerArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to query the gateway container status."
    }
    return -not [string]::IsNullOrWhiteSpace(($GatewayId -join ""))
}

function Assert-TlsGatewayReady {
    if (-not (Test-GatewayRunning)) {
        throw "gateway must be running so the ACME HTTP-01 webroot can answer renewal challenges."
    }

    $ApiHost = Get-ConfigValue -Name "DRIVE_SERVER_NAME"
    $StorageHost = Get-ConfigValue -Name "DRIVE_STORAGE_SERVER_NAME"
    $CertName = Get-ConfigValue -Name "DRIVE_TLS_CERT_NAME" -DefaultValue "enterprise-drive"
    $ExpectedCertificate = "/etc/letsencrypt/live/$CertName/fullchain.pem"
    $CheckScript = @(
        "nginx -t >/dev/null 2>&1",
        "grep -Fq '/.well-known/acme-challenge/' /etc/nginx/conf.d/default.conf",
        "grep -Fq 'listen 8443 ssl' /etc/nginx/conf.d/default.conf",
        "grep -Fq 'ssl_certificate $ExpectedCertificate;' /etc/nginx/conf.d/default.conf",
        "grep -Fq 'server_name $ApiHost;' /etc/nginx/conf.d/default.conf",
        "grep -Fq 'server_name $StorageHost;' /etc/nginx/conf.d/default.conf"
    ) -join " && "
    $CheckArguments = @(
        $ComposeBaseArguments +
        @(
            "exec", "--no-TTY",
            "gateway",
            "sh", "-ec",
            $CheckScript
        )
    )
    & docker @CheckArguments
    if ($LASTEXITCODE -ne 0) {
        throw "gateway is not running the public TLS/ACME configuration. Run manage.ps1 up -Tls first."
    }

    foreach ($PortMapping in @(@("8080", "80"), @("8443", "443"))) {
        $PortArguments = @(
            $ComposeBaseArguments +
            @("port", "gateway", $PortMapping[0])
        )
        $PublishedEndpoint = & docker @PortArguments
        if (
            $LASTEXITCODE -ne 0 -or
            [string]::IsNullOrWhiteSpace(($PublishedEndpoint -join "")) -or
            ($PublishedEndpoint -join "") -notmatch ":$($PortMapping[1])$"
        ) {
            throw "gateway container port $($PortMapping[0]) must be published on host port $($PortMapping[1]) for ACME renewal."
        }
    }
}

function Assert-CertificateMatchesDomains {
    param(
        [switch]$AllowExpiring
    )

    $ApiHost = Get-ConfigValue -Name "DRIVE_SERVER_NAME"
    $StorageHost = Get-ConfigValue -Name "DRIVE_STORAGE_SERVER_NAME"
    $CertName = Get-ConfigValue -Name "DRIVE_TLS_CERT_NAME" -DefaultValue "enterprise-drive"
    $CertificatePath = "/etc/letsencrypt/live/$CertName/fullchain.pem"
    $Checks = @("test -r '$CertificatePath'")
    if (-not $AllowExpiring) {
        $Checks += "openssl x509 -in '$CertificatePath' -noout -checkend 86400"
    }
    $Checks += @(
        "openssl x509 -in '$CertificatePath' -noout -checkhost '$ApiHost' >/dev/null",
        "openssl x509 -in '$CertificatePath' -noout -checkhost '$StorageHost' >/dev/null"
    )
    $CheckScript = $Checks -join " && "

    try {
        Invoke-Compose -Arguments @(
            "--profile", "tls-tools",
            "run", "--rm",
            "--pull", "never",
            "--entrypoint", "sh",
            "certbot",
            "-ec", $CheckScript
        )
    }
    catch {
        if ($AllowExpiring) {
            throw "The certificate '$CertName' is missing, unreadable, or does not cover both configured DNS names. Run tls-init to issue or expand it."
        }
        throw "The certificate '$CertName' is missing, expires within 24 hours, or does not cover both configured DNS names. Run tls-init to issue or expand it."
    }
}

function Assert-CertbotRenewalLineage {
    $CertName = Get-ConfigValue -Name "DRIVE_TLS_CERT_NAME" -DefaultValue "enterprise-drive"
    $RenewalPath = "/etc/letsencrypt/renewal/$CertName.conf"
    try {
        Invoke-Compose -Arguments @(
            "--profile", "tls-tools",
            "run", "--rm",
            "--pull", "never",
            "--entrypoint", "sh",
            "certbot",
            "-ec", "test -r '$RenewalPath'"
        )
    }
    catch {
        throw "The Certbot renewal lineage '$CertName' is missing. Run tls-init to create a managed certificate before renewal or task registration."
    }
}

function Invoke-GatewayReload {
    if (-not (Test-GatewayRunning)) {
        Write-Warning "Certificate operation completed, but gateway is not running. The next start will load the latest certificate."
        return
    }

    Invoke-Compose -Arguments @("exec", "--no-TTY", "gateway", "nginx", "-t")
    Invoke-Compose -Arguments @("exec", "--no-TTY", "gateway", "nginx", "-s", "reload")
}

function Register-TlsRenewalTask {
    Assert-TlsConfiguration -RequireStandardPorts -RequirePublicDeployment
    Import-Module ScheduledTasks -ErrorAction Stop

    $PowerShellExecutable = (Get-Process -Id $PID).Path
    $TaskArguments = @(
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$PSCommandPath`"",
        "tls-renew",
        "-Tls",
        "-EnvFile", "`"$EnvFile`""
    ) -join " "
    $TriggerTime = [System.DateTime]::Today.Add(
        [System.TimeSpan]::ParseExact(
            $TlsRenewalAt,
            "hh\:mm",
            [System.Globalization.CultureInfo]::InvariantCulture
        )
    )

    $ScheduledAction = New-ScheduledTaskAction `
        -Execute $PowerShellExecutable `
        -Argument $TaskArguments `
        -WorkingDirectory $RepoRoot
    $Trigger = New-ScheduledTaskTrigger -Daily -At $TriggerTime
    $Settings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -WakeToRun `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Hours 1)

    Register-ScheduledTask `
        -TaskName $TlsRenewalTaskName `
        -Action $ScheduledAction `
        -Trigger $Trigger `
        -Settings $Settings `
        -Description "Enterprise Drive Certbot renewal and Nginx hot reload" `
        -Force
}

$BackupRestoreScript = Join-Path $PSScriptRoot "backup-restore.ps1"
$GovernanceScript = Join-Path $PSScriptRoot "governance.ps1"
$OfflineBackupScript = Join-Path $PSScriptRoot "offline-backup.ps1"
$DataMigrationScript = Join-Path $PSScriptRoot "data-migration.ps1"
foreach ($HelperScript in @(
    $BackupRestoreScript,
    $GovernanceScript,
    $OfflineBackupScript,
    $DataMigrationScript
)) {
    if (-not (Test-Path -LiteralPath $HelperScript -PathType Leaf)) {
        throw "Windows deployment helper does not exist: $HelperScript"
    }
}
. $BackupRestoreScript
. $GovernanceScript
. $OfflineBackupScript
. $DataMigrationScript
Assert-ActionParameters

$DeploymentMutex = $null
Push-Location $RepoRoot
try {
    if ($Action -in @("up", "down", "tls-init", "tls-renew", "tls-register-renewal")) {
        $ComposeProjectName = Get-WindowsComposeProjectName `
            -ComposeBaseArguments $ComposeBaseArguments
        $DeploymentMutex = Enter-WindowsDeploymentMutex `
            -ProjectName $ComposeProjectName
    }

    switch ($Action) {
        "config" {
            if ($TlsMode) {
                Assert-TlsConfiguration -RequireStandardPorts -RequirePublicDeployment
            }
            $Arguments = @()
            if ($TlsMode) {
                $Arguments += @("--profile", "tls-tools")
            }
            $Arguments += "config"
            if ($Quiet) {
                $Arguments += "--quiet"
            }
            Invoke-Compose -Arguments $Arguments
        }
        "up" {
            Assert-DockerEngine
            if ($TlsMode) {
                Assert-TlsConfiguration -RequireStandardPorts -RequirePublicDeployment
                Assert-CertificateMatchesDomains
            }
            if ($Monitoring) {
                Assert-MonitoringConfiguration
            }
            $Arguments = @("up", "--detach", "--remove-orphans")
            if ($Build) {
                $Arguments += "--build"
            }
            else {
                $Arguments += "--no-build"
            }
            $Arguments += @("--pull", "never")
            Invoke-Compose -Arguments $Arguments
            Invoke-Compose -Arguments @("ps", "--all")
        }
        "down" {
            Assert-DockerEngine
            $Arguments = @()
            if ($TlsMode -or $Volumes) {
                $Arguments += @("--profile", "tls-tools")
            }
            $Arguments += @("down", "--remove-orphans")
            if ($Volumes) {
                Write-Warning "This removes database, object, index, Redis, TLS, and monitoring named volumes."
                $Arguments += "--volumes"
            }
            Invoke-Compose -Arguments $Arguments
            if ($Volumes) {
                Import-Module ScheduledTasks -ErrorAction Stop
                foreach ($TaskName in @(
                    $TlsRenewalTaskName,
                    $BackupRetentionTaskName,
                    $RestoreDrillTaskName
                )) {
                    $ExistingTask = Get-ScheduledTask -TaskPath "\" |
                        Where-Object { $_.TaskName -eq $TaskName }
                    if ($null -ne $ExistingTask) {
                        $ExistingTask | Unregister-ScheduledTask -Confirm:$false
                        Write-Warning "Removed deployment scheduled task: $TaskName"
                    }
                }
            }
        }
        "status" {
            Assert-DockerEngine
            Invoke-Compose -Arguments @("ps", "--all")
        }
        "logs" {
            Assert-DockerEngine
            $Arguments = @("logs", "--follow", "--tail", $Tail.ToString())
            if (-not [string]::IsNullOrWhiteSpace($Service)) {
                $Arguments += $Service
            }
            Invoke-Compose -Arguments $Arguments
        }
        "backup" {
            Assert-DockerEngine
            $BackupArguments = @{
                RepoRoot = $RepoRoot
                ComposeFile = $ComposeFile
                EnvFile = $EnvFile
                ComposeBaseArguments = $ComposeBaseArguments
                BackupDirectory = $BackupDirectory
                QuiesceTimeoutSeconds = $QuiesceTimeoutSeconds
                SkipEnvironmentBackup = [bool]$SkipEnvironmentBackup
            }
            if (-not [string]::IsNullOrWhiteSpace($ConfigEncryptionCertificateThumbprint)) {
                $BackupArguments["ConfigEncryptionCertificateThumbprint"] = (
                    $ConfigEncryptionCertificateThumbprint
                )
            }
            if (-not [string]::IsNullOrWhiteSpace($BackupSigningCertificateThumbprint)) {
                $BackupArguments["BackupSigningCertificateThumbprint"] = (
                    $BackupSigningCertificateThumbprint
                )
            }
            if (-not [string]::IsNullOrWhiteSpace($PackageEncryptionCertificateThumbprint)) {
                $BackupArguments["PackageEncryptionCertificateThumbprint"] = (
                    $PackageEncryptionCertificateThumbprint
                )
            }
            Invoke-WindowsBackup @BackupArguments
        }
        "backup-verify" {
            Assert-DockerEngine
            $Manifest = Test-WindowsBackup `
                -RepoRoot $RepoRoot `
                -ComposeFile $ComposeFile `
                -EnvFile $EnvFile `
                -ComposeBaseArguments $ComposeBaseArguments `
                -BackupPath $BackupPath
            Write-Output (
                "Backup verified: {0} ({1})" -f
                $Manifest.backup_id,
                $Manifest.created_at_utc
            )
        }
        "restore" {
            Assert-DockerEngine
            $RestoreArguments = @{
                RepoRoot = $RepoRoot
                ComposeFile = $ComposeFile
                EnvFile = $EnvFile
                ComposeBaseArguments = $ComposeBaseArguments
                BackupPath = $BackupPath
                ForceRestore = [bool]$ForceRestore
                NoStartAfterRestore = [bool]$NoStartAfterRestore
            }
            if (-not [string]::IsNullOrWhiteSpace($RestoreEnvironmentOutput)) {
                $RestoreArguments["RestoreEnvironmentOutput"] = $RestoreEnvironmentOutput
            }
            Invoke-WindowsRestore @RestoreArguments
        }
        "backup-retention" {
            $Result = Invoke-WindowsBackupRetention `
                -RepoRoot $RepoRoot `
                -ComposeBaseArguments $ComposeBaseArguments `
                -BackupDirectory $BackupDirectory `
                -RetentionDays $RetentionDays `
                -RetentionCount $RetentionCount `
                -Apply:$ApplyRetention
            $Result | ConvertTo-Json -Depth 8
        }
        "backup-offline-rotate" {
            $Arguments = @{
                RepoRoot = $RepoRoot
                ComposeBaseArguments = $ComposeBaseArguments
                OfflineBackupDirectory = $OfflineBackupDirectory
                RetentionDays = $RetentionDays
                RetentionCount = $RetentionCount
                ApplyRetention = [bool]$ApplyRetention
            }
            if (-not [string]::IsNullOrWhiteSpace($BackupPath)) {
                $Arguments["BackupPath"] = $BackupPath
            }
            else {
                $Arguments["BackupDirectory"] = $BackupDirectory
            }
            $Result = Invoke-WindowsOfflineBackupRotation @Arguments
            $Result | ConvertTo-Json -Depth 12
        }
        "backup-retention-register" {
            Register-WindowsBackupRetentionTask `
                -RepoRoot $RepoRoot `
                -ManageScript $PSCommandPath `
                -EnvFile $EnvFile `
                -BackupDirectory $BackupDirectory `
                -RetentionDays $RetentionDays `
                -RetentionCount $RetentionCount `
                -TaskName $BackupRetentionTaskName `
                -At $BackupRetentionAt
        }
        "restore-drill" {
            Assert-DockerEngine
            $RestoreDrillArguments = @{
                RepoRoot = $RepoRoot
                ComposeFile = $ComposeFile
                EnvFile = $EnvFile
                ComposeBaseArguments = $ComposeBaseArguments
                RecordDirectory = $RestoreDrillDirectory
            }
            if (-not [string]::IsNullOrWhiteSpace($BackupPath)) {
                $RestoreDrillArguments["BackupPath"] = $BackupPath
            }
            else {
                $RestoreDrillArguments["BackupDirectory"] = $BackupDirectory
            }
            $Result = Invoke-WindowsRestoreDrill @RestoreDrillArguments
            $Result | ConvertTo-Json -Depth 8
        }
        "restore-drill-register" {
            Register-WindowsRestoreDrillTask `
                -RepoRoot $RepoRoot `
                -ManageScript $PSCommandPath `
                -EnvFile $EnvFile `
                -BackupDirectory $BackupDirectory `
                -RecordDirectory $RestoreDrillDirectory `
                -TaskName $RestoreDrillTaskName `
                -At $RestoreDrillAt `
                -DayOfWeek $RestoreDrillDayOfWeek
        }
        "data-migration-export" {
            Assert-DockerEngine
            $ExportPath = New-WindowsPortableDataExport `
                -RepoRoot $RepoRoot `
                -ComposeBaseArguments $ComposeBaseArguments `
                -ExportDirectory $MigrationDirectory
            Write-Output "Portable data export created: $ExportPath"
        }
        "data-migration-apply" {
            Assert-DockerEngine
            $Result = Invoke-WindowsPortableDataMigration `
                -RepoRoot $RepoRoot `
                -ComposeBaseArguments $ComposeBaseArguments `
                -ExportPath $MigrationPath `
                -RollbackExportDirectory $MigrationRollbackDirectory `
                -RecordDirectory $MigrationRecordDirectory `
                -Mode "apply"
            $Result | ConvertTo-Json -Depth 16
        }
        "data-migration-rollback" {
            Assert-DockerEngine
            $Result = Invoke-WindowsPortableDataMigration `
                -RepoRoot $RepoRoot `
                -ComposeBaseArguments $ComposeBaseArguments `
                -ExportPath $MigrationPath `
                -RollbackExportDirectory $MigrationRollbackDirectory `
                -RecordDirectory $MigrationRecordDirectory `
                -Mode "rollback"
            $Result | ConvertTo-Json -Depth 16
        }
        "tls-init" {
            Assert-DockerEngine
            Assert-TlsConfiguration `
                -RequireEmail `
                -RequireStandardPorts `
                -RequirePublicDeployment

            $ApiHost = Get-ConfigValue -Name "DRIVE_SERVER_NAME"
            $StorageHost = Get-ConfigValue -Name "DRIVE_STORAGE_SERVER_NAME"
            $CertName = Get-ConfigValue -Name "DRIVE_TLS_CERT_NAME" -DefaultValue "enterprise-drive"
            if ($TlsStaging) {
                $CertName = "$CertName-staging"
                Set-ProcessEnvironmentValue -Name "DRIVE_TLS_CERT_NAME" -Value $CertName
                Set-ProcessEnvironmentValue -Name "DRIVE_TLS_HSTS_MAX_AGE" -Value "0"
            }
            $Email = if (-not [string]::IsNullOrWhiteSpace($TlsEmail)) {
                $TlsEmail
            }
            else {
                Get-ConfigValue -Name "CERTBOT_EMAIL"
            }

            $GatewayWasRunning = Test-GatewayRunning
            $BootstrapContainerId = $null
            try {
                if ($GatewayWasRunning) {
                    Invoke-Compose -Arguments @("stop", "gateway")
                }

                Enable-TlsComposeMode -Bootstrap
                Invoke-Compose -Arguments @("--profile", "tls-tools", "config", "--quiet")
                $BootstrapContainerId = Start-AcmeBootstrapGateway

                $Arguments = @(
                    "--profile", "tls-tools",
                    "run", "--rm",
                    "--pull", "never",
                    "certbot",
                    "certonly",
                    "--webroot",
                    "--webroot-path", "/var/www/certbot",
                    "--non-interactive",
                    "--agree-tos",
                    "--email", $Email,
                    "--cert-name", $CertName,
                    "--keep-until-expiring",
                    "-d", $ApiHost,
                    "-d", $StorageHost
                )
                if ($TlsStaging) {
                    $Arguments += "--staging"
                }
                Invoke-Compose -Arguments $Arguments
                Assert-CertificateMatchesDomains
                Assert-CertbotRenewalLineage

                Invoke-Compose -Arguments @(
                    "up",
                    "--detach",
                    "--remove-orphans",
                    "--no-build",
                    "--pull", "never",
                    "--wait",
                    "--wait-timeout", "180",
                    "api",
                    "seaweedfs"
                )
                Enable-TlsComposeMode
                Invoke-Compose -Arguments @(
                    "run", "--rm", "--no-deps",
                    "--pull", "never",
                    "gateway",
                    "nginx", "-t"
                )
                Remove-AcmeBootstrapGateway -ContainerId $BootstrapContainerId
                $BootstrapContainerId = $null
            }
            catch {
                $OriginalFailure = $_
                $RecoveryErrors = @()
                if (-not [string]::IsNullOrWhiteSpace($BootstrapContainerId)) {
                    try {
                        Remove-AcmeBootstrapGateway -ContainerId $BootstrapContainerId
                    }
                    catch {
                        $RecoveryErrors += $_.Exception.Message
                    }
                }
                if ($GatewayWasRunning) {
                    try {
                        Invoke-Compose -Arguments @("start", "gateway")
                    }
                    catch {
                        $RecoveryErrors += $_.Exception.Message
                    }
                }
                if ($RecoveryErrors.Count -gt 0) {
                    throw "tls-init failed and gateway recovery also failed: $($RecoveryErrors -join '; '). Original error: $($OriginalFailure.Exception.Message)"
                }
                throw $OriginalFailure
            }

            try {
                Enable-TlsComposeMode
                Invoke-Compose -Arguments @(
                    "up",
                    "--detach",
                    "--force-recreate",
                    "--no-build",
                    "--pull", "never",
                    "--wait",
                    "--wait-timeout", "60",
                    "gateway"
                )
            }
            catch {
                $OriginalFailure = $_
                if ($GatewayWasRunning) {
                    try {
                        Invoke-Compose -Arguments @("start", "gateway")
                    }
                    catch {
                        throw "The issued certificate passed validation, but the TLS gateway update and previous gateway restart both failed. Original error: $($OriginalFailure.Exception.Message). Recovery error: $($_.Exception.Message)"
                    }
                }
                throw $OriginalFailure
            }
            Invoke-Compose -Arguments @("exec", "--no-TTY", "gateway", "nginx", "-t")
        }
        "tls-renew" {
            Assert-DockerEngine
            Assert-TlsConfiguration -RequireStandardPorts
            Assert-CertificateMatchesDomains -AllowExpiring
            Assert-CertbotRenewalLineage
            Assert-TlsGatewayReady
            Invoke-Compose -Arguments @("--profile", "tls-tools", "config", "--quiet")

            $CertName = Get-ConfigValue -Name "DRIVE_TLS_CERT_NAME" -DefaultValue "enterprise-drive"
            $Arguments = @(
                "--profile", "tls-tools",
                "run", "--rm",
                "--pull", "never",
                "certbot",
                "renew",
                "--cert-name", $CertName,
                "--webroot",
                "--webroot-path", "/var/www/certbot",
                "--non-interactive"
            )
            if ($ForceRenewal) {
                $Arguments += "--force-renewal"
            }
            Invoke-Compose -Arguments $Arguments
            Assert-CertificateMatchesDomains
            Invoke-GatewayReload
        }
        "tls-certificates" {
            Assert-DockerEngine
            Assert-TlsConfiguration
            Invoke-Compose -Arguments @(
                "--profile", "tls-tools",
                "run", "--rm",
                "--pull", "never",
                "certbot",
                "certificates"
            )
        }
        "tls-register-renewal" {
            Assert-DockerEngine
            Assert-TlsConfiguration -RequireStandardPorts -RequirePublicDeployment
            Assert-CertificateMatchesDomains
            Assert-CertbotRenewalLineage
            Assert-TlsGatewayReady
            Register-TlsRenewalTask
        }
        "tls-validate-public" {
            Assert-TlsConfiguration `
                -RequireStandardPorts `
                -RequirePublicDeployment
            $Result = Invoke-WindowsPublicTlsValidation `
                -RepoRoot $RepoRoot `
                -ApiHost (
                    Get-ConfigValue -Name "DRIVE_SERVER_NAME"
                ) `
                -StorageHost (
                    Get-ConfigValue -Name "DRIVE_STORAGE_SERVER_NAME"
                ) `
                -RecordDirectory $TlsValidationDirectory
            $Result | ConvertTo-Json -Depth 12
        }
    }
}
finally {
    if ($null -ne $DeploymentMutex) {
        Exit-WindowsDeploymentMutex -Mutex $DeploymentMutex
    }
    Pop-Location
}
