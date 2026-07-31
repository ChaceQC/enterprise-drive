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
        "tls-init",
        "tls-renew",
        "tls-certificates",
        "tls-register-renewal",
        "tls-unregister-renewal"
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

    [string]$BackupDirectory,

    [string]$BackupPath,

    [ValidatePattern("^[A-Fa-f0-9]{40}$")]
    [string]$ConfigEncryptionCertificateThumbprint,

    [switch]$SkipEnvironmentBackup,

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
    [string]$TlsRenewalAt = "03:17"
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

if ($Action -eq "tls-unregister-renewal") {
    Import-Module ScheduledTasks -ErrorAction Stop
    $ExistingTask = Get-ScheduledTask -TaskPath "\" |
        Where-Object { $_.TaskName -eq $TlsRenewalTaskName }
    if ($null -ne $ExistingTask) {
        $ExistingTask | Unregister-ScheduledTask -Confirm:$false
    }
    else {
        Write-Output "Scheduled task does not exist: $TlsRenewalTaskName"
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
    $BackupParameterNames = @(
        "BackupDirectory",
        "BackupPath",
        "ConfigEncryptionCertificateThumbprint",
        "SkipEnvironmentBackup",
        "RestoreEnvironmentOutput",
        "ForceRestore",
        "NoStartAfterRestore",
        "QuiesceTimeoutSeconds"
    )

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
            foreach ($Name in @("RestoreEnvironmentOutput", "ForceRestore", "NoStartAfterRestore")) {
                if ($InvocationParameters.ContainsKey($Name)) {
                    throw "backup does not accept -$Name."
                }
            }
        }
        "backup-verify" {
            if ([string]::IsNullOrWhiteSpace($BackupPath)) {
                throw "backup-verify requires -BackupPath."
            }
            foreach ($Name in $BackupParameterNames) {
                if ($Name -ne "BackupPath" -and $InvocationParameters.ContainsKey($Name)) {
                    throw "backup-verify does not accept -$Name."
                }
            }
        }
        "restore" {
            if ([string]::IsNullOrWhiteSpace($BackupPath)) {
                throw "restore requires -BackupPath."
            }
            foreach ($Name in @(
                "BackupDirectory",
                "ConfigEncryptionCertificateThumbprint",
                "SkipEnvironmentBackup",
                "QuiesceTimeoutSeconds"
            )) {
                if ($InvocationParameters.ContainsKey($Name)) {
                    throw "restore does not accept -$Name."
                }
            }
        }
        default {
            foreach ($Name in $BackupParameterNames) {
                if ($InvocationParameters.ContainsKey($Name)) {
                    throw "$Action does not accept -$Name."
                }
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
        [string[]]$MinioCorsOrigins = @(
            (Get-ConfigValue -Name "MINIO_CORS_ALLOWED_ORIGIN").Split(",") |
                ForEach-Object { $_.Trim() } |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
                Sort-Object -Unique
        )
        foreach ($Origin in $MinioCorsOrigins) {
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
                throw "Every MINIO_CORS_ALLOWED_ORIGIN entry must be an explicit HTTPS origin."
            }
        }
        if ($MinioCorsOrigins.Count -ne $CorsOriginTexts.Count) {
            throw "MINIO_CORS_ALLOWED_ORIGIN must exactly match DRIVE_CORS_ORIGINS as a comma-separated origin list."
        }
        foreach ($Origin in $CorsOriginTexts) {
            if ($Origin -notin $MinioCorsOrigins) {
                throw "MINIO_CORS_ALLOWED_ORIGIN must exactly match DRIVE_CORS_ORIGINS as a comma-separated origin list."
            }
        }

        $SecretMinimumLengths = @{
            DRIVE_SECRET_KEY = 32
            POSTGRES_PASSWORD = 16
            REDIS_PASSWORD = 16
            MINIO_ROOT_PASSWORD = 16
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

if ($TlsMode) {
    Enable-TlsComposeMode
}

$ComposeBaseArguments = @(
    "compose",
    "--project-directory", $RepoRoot,
    "--env-file", $EnvFile,
    "--file", $ComposeFile
)

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
if (-not (Test-Path -LiteralPath $BackupRestoreScript -PathType Leaf)) {
    throw "Backup and restore helper does not exist: $BackupRestoreScript"
}
. $BackupRestoreScript
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
                Write-Warning "This removes database, object, index, Redis, and TLS certificate named volumes."
                $Arguments += "--volumes"
            }
            Invoke-Compose -Arguments $Arguments
            if ($Volumes) {
                Import-Module ScheduledTasks -ErrorAction Stop
                $ExistingTask = Get-ScheduledTask -TaskPath "\" |
                    Where-Object { $_.TaskName -eq $TlsRenewalTaskName }
                if ($null -ne $ExistingTask) {
                    $ExistingTask | Unregister-ScheduledTask -Confirm:$false
                    Write-Warning "Removed TLS renewal scheduled task: $TlsRenewalTaskName"
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
                    "minio"
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
    }
}
finally {
    if ($null -ne $DeploymentMutex) {
        Exit-WindowsDeploymentMutex -Mutex $DeploymentMutex
    }
    Pop-Location
}
