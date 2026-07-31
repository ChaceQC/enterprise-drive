function Get-WindowsRedactedDockerArguments {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    return @(
        foreach ($Argument in $Arguments) {
            $Match = [regex]::Match(
                $Argument,
                (
                    "^(?<name>(?:PGPASSWORD|[^=]*(?:PASSWORD|SECRET|TOKEN)|" +
                    "DRIVE_(?:DATABASE|REDIS|CELERY_[^=]+)_URL))="
                ),
                [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
            )
            if ($Match.Success) {
                "$($Match.Groups["name"].Value)=<redacted>"
            }
            else {
                $Argument
            }
        }
    )
}

function Invoke-WindowsDocker {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $Output = @(& docker @Arguments)
    $ExitCode = $LASTEXITCODE
    if ($ExitCode -ne 0) {
        $RedactedArguments = Get-WindowsRedactedDockerArguments `
            -Arguments $Arguments
        throw "docker failed with exit code ${ExitCode}: $($RedactedArguments -join ' ')"
    }
    return $Output
}

function Test-WindowsDocker {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $ExitCode = 1
    $PreviousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "SilentlyContinue"
        & docker @Arguments 1> $null 2> $null
        $ExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }
    return $ExitCode -eq 0
}

function Get-WindowsBackupSetting {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [string]$DefaultValue
    )

    $ConfigGetter = Get-Command `
        -Name "Get-ConfigValue" `
        -CommandType Function `
        -ErrorAction SilentlyContinue
    if ($null -ne $ConfigGetter) {
        return [string](
            Get-ConfigValue -Name $Name -DefaultValue $DefaultValue
        )
    }

    $Value = [System.Environment]::GetEnvironmentVariable(
        $Name,
        [System.EnvironmentVariableTarget]::Process
    )
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $DefaultValue
    }
    return [string]$Value
}

function Get-WindowsBackupHelperSettings {
    $CpuText = Get-WindowsBackupSetting `
        -Name "DRIVE_BACKUP_HELPER_CPU_LIMIT" `
        -DefaultValue "0.50"
    $CpuValue = 0.0
    if (
        -not [double]::TryParse(
            $CpuText,
            [System.Globalization.NumberStyles]::Float,
            [System.Globalization.CultureInfo]::InvariantCulture,
            [ref]$CpuValue
        ) -or
        $CpuValue -lt 0.10 -or
        $CpuValue -gt 4.00
    ) {
        throw "DRIVE_BACKUP_HELPER_CPU_LIMIT must be between 0.10 and 4.00."
    }

    $MemoryLimit = Get-WindowsBackupSetting `
        -Name "DRIVE_BACKUP_HELPER_MEMORY_LIMIT" `
        -DefaultValue "512m"
    $MemoryMatch = [regex]::Match(
        $MemoryLimit,
        "^(?<value>[1-9][0-9]*)(?<unit>[kKmMgG]?)[bB]?$"
    )
    if (-not $MemoryMatch.Success) {
        throw "DRIVE_BACKUP_HELPER_MEMORY_LIMIT has an invalid Docker memory value."
    }
    $MemoryNumber = 0L
    if (
        -not [long]::TryParse(
            $MemoryMatch.Groups["value"].Value,
            [System.Globalization.NumberStyles]::None,
            [System.Globalization.CultureInfo]::InvariantCulture,
            [ref]$MemoryNumber
        )
    ) {
        throw "DRIVE_BACKUP_HELPER_MEMORY_LIMIT is too large."
    }
    $MemoryMultiplier = switch (
        $MemoryMatch.Groups["unit"].Value.ToLowerInvariant()
    ) {
        "k" { 1KB }
        "m" { 1MB }
        "g" { 1GB }
        default { 1 }
    }
    if (
        $MemoryNumber -gt ([long]::MaxValue / $MemoryMultiplier)
    ) {
        throw "DRIVE_BACKUP_HELPER_MEMORY_LIMIT is too large."
    }
    $MemoryBytes = $MemoryNumber * $MemoryMultiplier
    if ($MemoryBytes -lt 64MB -or $MemoryBytes -gt 4GB) {
        throw "DRIVE_BACKUP_HELPER_MEMORY_LIMIT must be between 64m and 4g."
    }

    $PidsText = Get-WindowsBackupSetting `
        -Name "DRIVE_BACKUP_HELPER_PIDS_LIMIT" `
        -DefaultValue "128"
    $PidsLimit = 0
    if (
        -not [int]::TryParse($PidsText, [ref]$PidsLimit) -or
        $PidsLimit -lt 32 -or
        $PidsLimit -gt 4096
    ) {
        throw "DRIVE_BACKUP_HELPER_PIDS_LIMIT must be between 32 and 4096."
    }

    $GzipText = Get-WindowsBackupSetting `
        -Name "DRIVE_BACKUP_GZIP_LEVEL" `
        -DefaultValue "1"
    $GzipLevel = 0
    if (
        -not [int]::TryParse($GzipText, [ref]$GzipLevel) -or
        $GzipLevel -lt 1 -or
        $GzipLevel -gt 9
    ) {
        throw "DRIVE_BACKUP_GZIP_LEVEL must be between 1 and 9."
    }

    $PgDumpText = Get-WindowsBackupSetting `
        -Name "DRIVE_BACKUP_PG_DUMP_COMPRESSION_LEVEL" `
        -DefaultValue "1"
    $PgDumpCompressionLevel = 0
    if (
        -not [int]::TryParse($PgDumpText, [ref]$PgDumpCompressionLevel) -or
        $PgDumpCompressionLevel -lt 0 -or
        $PgDumpCompressionLevel -gt 9
    ) {
        throw "DRIVE_BACKUP_PG_DUMP_COMPRESSION_LEVEL must be between 0 and 9."
    }

    return [pscustomobject][ordered]@{
        cpu_limit = $CpuValue.ToString(
            "0.00",
            [System.Globalization.CultureInfo]::InvariantCulture
        )
        memory_limit = $MemoryLimit.ToLowerInvariant()
        pids_limit = $PidsLimit.ToString(
            [System.Globalization.CultureInfo]::InvariantCulture
        )
        gzip_level = $GzipLevel
        pg_dump_compression_level = $PgDumpCompressionLevel
    }
}

function Get-WindowsBackupHelperRunArguments {
    $Settings = Get-WindowsBackupHelperSettings
    return @(
        "--cpus", [string]$Settings.cpu_limit,
        "--memory", [string]$Settings.memory_limit,
        "--memory-swap", [string]$Settings.memory_limit,
        "--pids-limit", [string]$Settings.pids_limit
    )
}

function Invoke-WindowsBackupHelperContainer {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $DockerArguments = @("run", "--rm", "--pull", "never") +
        @(Get-WindowsBackupHelperRunArguments) +
        @($Arguments)
    return Invoke-WindowsDocker -Arguments $DockerArguments
}

function Get-WindowsComposeModel {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$ComposeBaseArguments
    )

    $Json = (
        Invoke-WindowsDocker -Arguments @(
            $ComposeBaseArguments + @("config", "--format", "json")
        )
    ) -join "`n"
    if ([string]::IsNullOrWhiteSpace($Json)) {
        throw "docker compose config returned an empty model."
    }
    return $Json | ConvertFrom-Json
}

function Get-WindowsComposeProjectName {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$ComposeBaseArguments
    )

    $Model = Get-WindowsComposeModel -ComposeBaseArguments $ComposeBaseArguments
    if (
        $null -eq $Model.PSObject.Properties["name"] -or
        [string]::IsNullOrWhiteSpace([string]$Model.name)
    ) {
        throw "The rendered Compose model does not contain a project name."
    }
    return [string]$Model.name
}

function ConvertFrom-WindowsDockerJson {
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

function Get-WindowsComposeContainers {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$ComposeBaseArguments
    )

    $Output = Invoke-WindowsDocker -Arguments @(
        $ComposeBaseArguments + @("ps", "--all", "--format", "json")
    )
    return @(
        ConvertFrom-WindowsDockerJson -Output @($Output)
    )
}

function Get-WindowsComposeRunningServices {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$ComposeBaseArguments
    )

    return @(
        Get-WindowsComposeContainers -ComposeBaseArguments $ComposeBaseArguments |
            Where-Object { [string]$_.State -eq "running" } |
            ForEach-Object { [string]$_.Service } |
            Sort-Object -Unique
    )
}

function Get-WindowsComposeDefaultServiceNames {
    param(
        [Parameter(Mandatory = $true)]
        [object]$ComposeModel
    )

    $Services = Get-WindowsModelPropertyValue `
        -Object $ComposeModel `
        -Name "services" `
        -Label "Compose model"
    return @(
        $Services.PSObject.Properties |
            Where-Object {
                $ProfilesProperty = $_.Value.PSObject.Properties["profiles"]
                $null -eq $ProfilesProperty -or
                @($ProfilesProperty.Value).Count -eq 0
            } |
            ForEach-Object { [string]$_.Name } |
            Sort-Object -Unique
    )
}

function Get-WindowsComposeServiceStateRecords {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Containers
    )

    $Records = @()
    foreach ($Container in @($Containers)) {
        foreach ($PropertyName in @("Service", "State")) {
            if ($null -eq $Container.PSObject.Properties[$PropertyName]) {
                throw "Compose container record is missing '$PropertyName'."
            }
        }
        $ServiceName = [string]$Container.Service
        $State = [string]$Container.State
        if (
            [string]::IsNullOrWhiteSpace($ServiceName) -or
            [string]::IsNullOrWhiteSpace($State)
        ) {
            throw "Compose container record has an empty service or state."
        }
        $IdProperty = $Container.PSObject.Properties["ID"]
        if ($null -eq $IdProperty) {
            $IdProperty = $Container.PSObject.Properties["Id"]
        }
        if (
            $null -eq $IdProperty -or
            [string]::IsNullOrWhiteSpace([string]$IdProperty.Value)
        ) {
            throw "Compose container record is missing its container ID."
        }
        $HealthProperty = $Container.PSObject.Properties["Health"]
        $ExitCodeProperty = $Container.PSObject.Properties["ExitCode"]
        $Records += [pscustomobject][ordered]@{
            service = $ServiceName
            state = $State
            health = if ($null -eq $HealthProperty) {
                ""
            }
            else {
                [string]$HealthProperty.Value
            }
            exit_code = if ($null -eq $ExitCodeProperty) {
                $null
            }
            else {
                [int]$ExitCodeProperty.Value
            }
            container_id = [string]$IdProperty.Value
        }
    }
    return @($Records | Sort-Object service)
}

function Get-WindowsComposeContainerImageId {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Container
    )

    $IdProperty = $Container.PSObject.Properties["ID"]
    if ($null -eq $IdProperty) {
        $IdProperty = $Container.PSObject.Properties["Id"]
    }
    if (
        $null -eq $IdProperty -or
        [string]::IsNullOrWhiteSpace([string]$IdProperty.Value)
    ) {
        throw "Compose container record is missing its container ID."
    }
    $ContainerId = [string]$IdProperty.Value
    $ImageId = (
        Invoke-WindowsDocker -Arguments @(
            "container",
            "inspect",
            "--format",
            "{{.Image}}",
            $ContainerId
        )
    ) -join ""
    $ImageId = $ImageId.Trim()
    if ([string]::IsNullOrWhiteSpace($ImageId)) {
        throw "Container image inspect returned no image ID: $ContainerId"
    }
    return $ImageId
}

function Get-WindowsComposeImageRecords {
    param(
        [Parameter(Mandatory = $true)]
        [object]$ComposeModel,

        [Parameter(Mandatory = $true)]
        [object[]]$Containers
    )

    $Records = @()
    foreach (
        $ServiceName in @(
            Get-WindowsComposeDefaultServiceNames -ComposeModel $ComposeModel
        )
    ) {
        $ImageReference = Get-WindowsModelServiceImage `
            -ComposeModel $ComposeModel `
            -ServiceName $ServiceName
        $ImageInfo = Get-WindowsImageInfo -Image $ImageReference
        $ServiceContainers = @(
            $Containers |
                Where-Object { [string]$_.Service -eq $ServiceName }
        )
        if ($ServiceContainers.Count -ne 1) {
            throw "Compose service '$ServiceName' must have exactly one container."
        }
        $ContainerImageId = Get-WindowsComposeContainerImageId `
            -Container $ServiceContainers[0]
        if ($ContainerImageId -notmatch "^sha256:[0-9a-f]{64}$") {
            throw "Compose service '$ServiceName' has an invalid container image ID."
        }
        if ([string]$ContainerImageId -ne [string]$ImageInfo.id) {
            throw (
                "Compose service '$ServiceName' container image ID does not " +
                "match its current image reference."
            )
        }
        $ContainerIdProperty = $ServiceContainers[0].PSObject.Properties["ID"]
        if ($null -eq $ContainerIdProperty) {
            $ContainerIdProperty = $ServiceContainers[0].PSObject.Properties["Id"]
        }
        $Records += [pscustomobject][ordered]@{
            service = $ServiceName
            reference = $ImageInfo.reference
            id = $ContainerImageId
            repo_digests = @($ImageInfo.repo_digests)
            created = $ImageInfo.created
            source = "container"
            container_id = [string]$ContainerIdProperty.Value
        }
    }
    return @($Records)
}

function Get-WindowsDeploymentMutexName {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectName
    )

    $Encoding = New-Object System.Text.UTF8Encoding($false)
    $Sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $Digest = $Sha256.ComputeHash($Encoding.GetBytes($ProjectName))
    }
    finally {
        $Sha256.Dispose()
    }
    $Hex = -join ($Digest | ForEach-Object { $_.ToString("x2") })
    return "Global\EnterpriseDrive.Windows.Maintenance.$($Hex.Substring(0, 32))"
}

function Enter-WindowsDeploymentMutex {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectName,

        [ValidateRange(0, 86400)]
        [int]$TimeoutSeconds = 0
    )

    $Name = Get-WindowsDeploymentMutexName -ProjectName $ProjectName
    $CreatedNew = $false
    $Mutex = New-Object System.Threading.Mutex($false, $Name, [ref]$CreatedNew)
    $Acquired = $false
    try {
        try {
            $Acquired = $Mutex.WaitOne(
                [System.TimeSpan]::FromSeconds($TimeoutSeconds)
            )
        }
        catch [System.Threading.AbandonedMutexException] {
            $Acquired = $true
        }
        if (-not $Acquired) {
            throw "Another deployment maintenance operation is active for resource '$ProjectName'."
        }
        return $Mutex
    }
    catch {
        $Mutex.Dispose()
        throw
    }
}

function Exit-WindowsDeploymentMutex {
    param(
        [Parameter(Mandatory = $true)]
        [System.Threading.Mutex]$Mutex
    )

    try {
        $Mutex.ReleaseMutex()
    }
    finally {
        $Mutex.Dispose()
    }
}

function Enter-WindowsDeploymentMutexSet {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$ResourceNames
    )

    $Mutexes = New-Object "System.Collections.Generic.List[System.Threading.Mutex]"
    try {
        foreach ($ResourceName in @($ResourceNames | Sort-Object -Unique)) {
            $Mutexes.Add(
                (Enter-WindowsDeploymentMutex -ProjectName $ResourceName)
            )
        }
    }
    catch {
        for ($Index = $Mutexes.Count - 1; $Index -ge 0; $Index -= 1) {
            try {
                Exit-WindowsDeploymentMutex -Mutex $Mutexes[$Index]
            }
            catch {
                Write-Warning (
                    "Failed to release a maintenance mutex after acquisition failure: " +
                    $_.Exception.Message
                )
            }
        }
        throw
    }
    return @($Mutexes)
}

function Exit-WindowsDeploymentMutexSet {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [System.Threading.Mutex[]]$Mutexes
    )

    $Errors = New-Object "System.Collections.Generic.List[string]"
    for ($Index = $Mutexes.Count - 1; $Index -ge 0; $Index -= 1) {
        try {
            Exit-WindowsDeploymentMutex -Mutex $Mutexes[$Index]
        }
        catch {
            $Errors.Add($_.Exception.Message)
        }
    }
    if ($Errors.Count -gt 0) {
        throw "Maintenance mutex release failed: $($Errors -join '; ')"
    }
}

function Get-WindowsModelPropertyValue {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Object,

        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    $Property = $Object.PSObject.Properties[$Name]
    if ($null -eq $Property) {
        throw "$Label is missing '$Name'."
    }
    return $Property.Value
}

function Get-WindowsBackupVolumeMap {
    param(
        [Parameter(Mandatory = $true)]
        [object]$ComposeModel
    )

    $Volumes = Get-WindowsModelPropertyValue `
        -Object $ComposeModel `
        -Name "volumes" `
        -Label "Compose model"
    $Map = @{}
    foreach ($LogicalName in @(
        "postgres-data",
        "redis-data",
        "minio-data",
        "opensearch-data",
        "tls-certificates"
    )) {
        $Volume = Get-WindowsModelPropertyValue `
            -Object $Volumes `
            -Name $LogicalName `
            -Label "Compose volumes"
        $PhysicalName = Get-WindowsModelPropertyValue `
            -Object $Volume `
            -Name "name" `
            -Label "Compose volume '$LogicalName'"
        if ([string]::IsNullOrWhiteSpace([string]$PhysicalName)) {
            throw "Compose volume '$LogicalName' has an empty physical name."
        }
        $Map[$LogicalName] = [string]$PhysicalName
    }
    return $Map
}

function Get-WindowsModelService {
    param(
        [Parameter(Mandatory = $true)]
        [object]$ComposeModel,

        [Parameter(Mandatory = $true)]
        [string]$ServiceName
    )

    $Services = Get-WindowsModelPropertyValue `
        -Object $ComposeModel `
        -Name "services" `
        -Label "Compose model"
    return Get-WindowsModelPropertyValue `
        -Object $Services `
        -Name $ServiceName `
        -Label "Compose services"
}

function Get-WindowsModelServiceImage {
    param(
        [Parameter(Mandatory = $true)]
        [object]$ComposeModel,

        [Parameter(Mandatory = $true)]
        [string]$ServiceName
    )

    $Service = Get-WindowsModelService `
        -ComposeModel $ComposeModel `
        -ServiceName $ServiceName
    $Image = Get-WindowsModelPropertyValue `
        -Object $Service `
        -Name "image" `
        -Label "Compose service '$ServiceName'"
    if ([string]::IsNullOrWhiteSpace([string]$Image)) {
        throw "Compose service '$ServiceName' has an empty image."
    }
    return [string]$Image
}

function Get-WindowsModelBackendNetwork {
    param(
        [Parameter(Mandatory = $true)]
        [object]$ComposeModel
    )

    $Networks = Get-WindowsModelPropertyValue `
        -Object $ComposeModel `
        -Name "networks" `
        -Label "Compose model"
    $Backend = Get-WindowsModelPropertyValue `
        -Object $Networks `
        -Name "backend" `
        -Label "Compose networks"
    $Name = Get-WindowsModelPropertyValue `
        -Object $Backend `
        -Name "name" `
        -Label "Compose backend network"
    if ([string]::IsNullOrWhiteSpace([string]$Name)) {
        throw "Compose backend network has an empty physical name."
    }
    return [string]$Name
}

function Get-WindowsModelEnvironmentValue {
    param(
        [Parameter(Mandatory = $true)]
        [object]$ComposeModel,

        [Parameter(Mandatory = $true)]
        [string]$ServiceName,

        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $Service = Get-WindowsModelService `
        -ComposeModel $ComposeModel `
        -ServiceName $ServiceName
    $Environment = Get-WindowsModelPropertyValue `
        -Object $Service `
        -Name "environment" `
        -Label "Compose service '$ServiceName'"
    $Value = Get-WindowsModelPropertyValue `
        -Object $Environment `
        -Name $Name `
        -Label "Compose service '$ServiceName' environment"
    return [string]$Value
}

function Get-WindowsImageInfo {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Image
    )

    $Json = (
        Invoke-WindowsDocker -Arguments @(
            "image", "inspect", "--format", "{{json .}}", $Image
        )
    ) -join "`n"
    if ([string]::IsNullOrWhiteSpace($Json)) {
        throw "docker image inspect returned no data for '$Image'."
    }
    $Inspect = $Json | ConvertFrom-Json
    return [pscustomobject][ordered]@{
        reference = $Image
        id = [string]$Inspect.Id
        repo_digests = @($Inspect.RepoDigests)
        created = [string]$Inspect.Created
    }
}

function Get-WindowsProjectVersion {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    $Path = Join-Path $RepoRoot "backend\pyproject.toml"
    $StrictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)
    $Text = [System.IO.File]::ReadAllText($Path, $StrictUtf8)
    $Match = [regex]::Match(
        $Text,
        '(?m)^version\s*=\s*"(?<version>[0-9]+\.[0-9]+\.[0-9]+)"\s*$'
    )
    if (-not $Match.Success) {
        throw "Project version was not found in backend/pyproject.toml."
    }
    return $Match.Groups["version"].Value
}

function Get-WindowsGitCommit {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    $Output = @(& git -C $RepoRoot rev-parse HEAD)
    $ExitCode = $LASTEXITCODE
    if ($ExitCode -ne 0) {
        throw "git rev-parse failed with exit code $ExitCode."
    }
    return [string](($Output -join "").Trim())
}

function Get-WindowsSha256 {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $Stream = [System.IO.File]::OpenRead($Path)
    $Sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $Digest = $Sha256.ComputeHash($Stream)
    }
    finally {
        $Sha256.Dispose()
        $Stream.Dispose()
    }
    return -join ($Digest | ForEach-Object { $_.ToString("x2") })
}

function Write-WindowsUtf8File {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$Content
    )

    $Encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $Encoding)
}

function Assert-WindowsNoReparsePoint {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    $CurrentPath = [System.IO.Path]::GetFullPath($Path)
    while (-not (Test-Path -LiteralPath $CurrentPath)) {
        $ParentPath = [System.IO.Path]::GetDirectoryName($CurrentPath)
        if ([string]::IsNullOrWhiteSpace($ParentPath)) {
            break
        }
        $CurrentPath = $ParentPath
    }

    while (-not [string]::IsNullOrWhiteSpace($CurrentPath)) {
        if (Test-Path -LiteralPath $CurrentPath) {
            $Item = Get-Item -LiteralPath $CurrentPath -Force
            if (
                ($Item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne
                0
            ) {
                throw "$Label contains an NTFS reparse point: $CurrentPath"
            }
        }
        $ParentPath = [System.IO.Path]::GetDirectoryName($CurrentPath)
        if (
            [string]::IsNullOrWhiteSpace($ParentPath) -or
            $ParentPath -eq $CurrentPath
        ) {
            break
        }
        $CurrentPath = $ParentPath
    }
}

function Set-WindowsRestrictedAcl {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [switch]$Directory
    )

    $CurrentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    $SystemSid = New-Object System.Security.Principal.SecurityIdentifier(
        "S-1-5-18"
    )
    $AdministratorsSid = New-Object System.Security.Principal.SecurityIdentifier(
        "S-1-5-32-544"
    )
    $Security = if ($Directory) {
        New-Object System.Security.AccessControl.DirectorySecurity
    }
    else {
        New-Object System.Security.AccessControl.FileSecurity
    }
    $Security.SetOwner($CurrentSid)
    $Security.SetAccessRuleProtection($true, $false)
    $Inheritance = if ($Directory) {
        (
            [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
            [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
        )
    }
    else {
        [System.Security.AccessControl.InheritanceFlags]::None
    }
    foreach ($Sid in @($CurrentSid, $SystemSid, $AdministratorsSid)) {
        $Rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            $Sid,
            [System.Security.AccessControl.FileSystemRights]::FullControl,
            $Inheritance,
            [System.Security.AccessControl.PropagationFlags]::None,
            [System.Security.AccessControl.AccessControlType]::Allow
        )
        $null = $Security.AddAccessRule($Rule)
    }
    if ($Directory) {
        [System.IO.Directory]::SetAccessControl($Path, $Security)
    }
    else {
        [System.IO.File]::SetAccessControl($Path, $Security)
    }
    Assert-WindowsRestrictedAcl -Path $Path
}

function Assert-WindowsRestrictedAcl {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $CurrentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    $AllowedSids = New-Object "System.Collections.Generic.HashSet[string]" (
        [System.StringComparer]::OrdinalIgnoreCase
    )
    foreach ($SidValue in @(
        $CurrentSid.Value,
        "S-1-5-18",
        "S-1-5-32-544"
    )) {
        $null = $AllowedSids.Add($SidValue)
    }

    $Acl = Get-Acl -LiteralPath $Path
    if (-not $Acl.AreAccessRulesProtected) {
        throw "Restricted ACL inheritance is not disabled: $Path"
    }
    $OwnerSid = if ([string]$Acl.Owner -match "^S-\d(?:-\d+)+$") {
        New-Object System.Security.Principal.SecurityIdentifier([string]$Acl.Owner)
    }
    else {
        (
            New-Object System.Security.Principal.NTAccount([string]$Acl.Owner)
        ).Translate([System.Security.Principal.SecurityIdentifier])
    }
    if ([string]$OwnerSid.Value -ne [string]$CurrentSid.Value) {
        throw "Restricted ACL owner does not match the current user: $Path"
    }

    $SeenAllow = New-Object "System.Collections.Generic.HashSet[string]" (
        [System.StringComparer]::OrdinalIgnoreCase
    )
    $Rules = $Acl.GetAccessRules(
        $true,
        $true,
        [System.Security.Principal.SecurityIdentifier]
    )
    foreach ($Rule in $Rules) {
        $SidValue = [string]$Rule.IdentityReference.Value
        if (-not $AllowedSids.Contains($SidValue)) {
            throw "Restricted ACL contains an unexpected identity '$SidValue': $Path"
        }
        if (
            $Rule.AccessControlType -ne
            [System.Security.AccessControl.AccessControlType]::Allow
        ) {
            throw "Restricted ACL contains a non-allow rule for '$SidValue': $Path"
        }
        if (
            (
                $Rule.FileSystemRights -band
                [System.Security.AccessControl.FileSystemRights]::FullControl
            ) -ne [System.Security.AccessControl.FileSystemRights]::FullControl
        ) {
            throw "Restricted ACL does not grant FullControl to '$SidValue': $Path"
        }
        $null = $SeenAllow.Add($SidValue)
    }
    foreach ($SidValue in $AllowedSids) {
        if (-not $SeenAllow.Contains($SidValue)) {
            throw "Restricted ACL is missing '$SidValue': $Path"
        }
    }
}

function Write-WindowsRestrictedUtf8File {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$Content
    )

    $OutputPath = [System.IO.Path]::GetFullPath($Path)
    $ParentPath = [System.IO.Path]::GetDirectoryName($OutputPath)
    if (
        [string]::IsNullOrWhiteSpace($ParentPath) -or
        -not (Test-Path -LiteralPath $ParentPath -PathType Container)
    ) {
        throw "The restricted output parent directory does not exist: $ParentPath"
    }
    Assert-WindowsNoReparsePoint -Path $ParentPath -Label "Restricted output path"
    $TemporaryPath = Join-Path $ParentPath (
        ".partial-" + [Guid]::NewGuid().ToString("N")
    )
    $Published = $false
    try {
        [System.IO.File]::WriteAllBytes($TemporaryPath, [byte[]]@())
        Set-WindowsRestrictedAcl -Path $TemporaryPath
        Write-WindowsUtf8File -Path $TemporaryPath -Content $Content
        Assert-WindowsRestrictedAcl -Path $TemporaryPath
        Assert-WindowsNoReparsePoint `
            -Path $TemporaryPath `
            -Label "Restricted output temporary path"
        [System.IO.File]::Move($TemporaryPath, $OutputPath)
        $Published = $true
        Assert-WindowsRestrictedAcl -Path $OutputPath
        Assert-WindowsNoReparsePoint `
            -Path $OutputPath `
            -Label "Restricted output path"
    }
    catch {
        $OriginalFailure = $_
        if ($Published -and (Test-Path -LiteralPath $OutputPath -PathType Leaf)) {
            try {
                Remove-Item -LiteralPath $OutputPath -Force
            }
            catch {
                throw (
                    "Restricted output publication and cleanup failed. " +
                    "Publication error: $($OriginalFailure.Exception.Message). " +
                    "Cleanup error: $($_.Exception.Message)"
                )
            }
        }
        throw $OriginalFailure
    }
    finally {
        if (Test-Path -LiteralPath $TemporaryPath) {
            Remove-Item -LiteralPath $TemporaryPath -Force
        }
    }
}

function Test-WindowsPathWithin {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Parent,

        [Parameter(Mandatory = $true)]
        [string]$Candidate
    )

    $ParentPath = [System.IO.Path]::GetFullPath($Parent).TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
    $CandidatePath = [System.IO.Path]::GetFullPath($Candidate)
    if ($CandidatePath.Equals(
        $ParentPath,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        return $true
    }
    $Prefix = $ParentPath + [System.IO.Path]::DirectorySeparatorChar
    return $CandidatePath.StartsWith(
        $Prefix,
        [System.StringComparison]::OrdinalIgnoreCase
    )
}

function Resolve-WindowsBackupRoot {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,

        [Parameter(Mandatory = $true)]
        [string]$BackupDirectory
    )

    if (-not [System.IO.Path]::IsPathRooted($BackupDirectory)) {
        throw "BackupDirectory must be an absolute path outside the repository."
    }
    $RepositoryPath = [System.IO.Path]::GetFullPath($RepoRoot)
    $Root = [System.IO.Path]::GetFullPath($BackupDirectory)
    $VolumeRoot = [System.IO.Path]::GetPathRoot($Root)
    if (
        $Root.TrimEnd(
            [System.IO.Path]::DirectorySeparatorChar,
            [System.IO.Path]::AltDirectorySeparatorChar
        ).Equals(
            $VolumeRoot.TrimEnd(
                [System.IO.Path]::DirectorySeparatorChar,
                [System.IO.Path]::AltDirectorySeparatorChar
            ),
            [System.StringComparison]::OrdinalIgnoreCase
        )
    ) {
        throw "BackupDirectory must not be a volume root."
    }
    if (
        (Test-WindowsPathWithin -Parent $RepositoryPath -Candidate $Root) -or
        (Test-WindowsPathWithin -Parent $Root -Candidate $RepositoryPath)
    ) {
        throw "BackupDirectory must be outside the repository and must not contain the repository."
    }
    $RootExists = Test-Path -LiteralPath $Root
    if ($RootExists -and -not (Test-Path -LiteralPath $Root -PathType Container)) {
        throw "BackupDirectory must be a directory: $Root"
    }
    if ($RootExists) {
        Assert-WindowsNoReparsePoint -Path $Root -Label "BackupDirectory"
        $ExistingEntries = @(
            Get-ChildItem -LiteralPath $Root -Force -ErrorAction Stop
        )
        if ($ExistingEntries.Count -gt 0) {
            try {
                Assert-WindowsRestrictedAcl -Path $Root
            }
            catch {
                throw (
                    "An existing nonempty BackupDirectory must already use the " +
                    "restricted ACL: $Root. $($_.Exception.Message)"
                )
            }
        }
    }
    else {
        $null = New-Item -ItemType Directory -Path $Root
    }
    Assert-WindowsNoReparsePoint -Path $Root -Label "BackupDirectory"
    Set-WindowsRestrictedAcl -Path $Root -Directory
    Assert-WindowsRestrictedAcl -Path $Root
    return $Root
}

function Remove-WindowsRestoreRollbackRoot {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $RollbackPath = [System.IO.Path]::GetFullPath($Path)
    if (-not (Test-Path -LiteralPath $RollbackPath -PathType Container)) {
        return
    }
    $TempRoot = [System.IO.Path]::GetFullPath(
        [System.IO.Path]::GetTempPath()
    )
    if (
        $RollbackPath.Equals(
            $TempRoot,
            [System.StringComparison]::OrdinalIgnoreCase
        ) -or
        -not (
            Test-WindowsPathWithin `
                -Parent $TempRoot `
                -Candidate $RollbackPath
        ) -or
        -not (
            [System.IO.Path]::GetFileName($RollbackPath).StartsWith(
                "enterprise-drive-restore-rollback-",
                [System.StringComparison]::OrdinalIgnoreCase
            )
        )
    ) {
        throw "Refusing to remove an invalid restore rollback path: $RollbackPath"
    }
    Assert-WindowsNoReparsePoint `
        -Path $RollbackPath `
        -Label "Restore rollback cleanup"
    Remove-Item -LiteralPath $RollbackPath -Recurse -Force
}

function Resolve-WindowsBackupArtifactPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$BackupRoot,

        [Parameter(Mandatory = $true)]
        [string]$RelativePath
    )

    if (
        [string]::IsNullOrWhiteSpace($RelativePath) -or
        [System.IO.Path]::IsPathRooted($RelativePath) -or
        $RelativePath.Contains("\") -or
        $RelativePath.Contains(":")
    ) {
        throw "Backup artifact path is invalid: '$RelativePath'."
    }
    foreach ($Segment in $RelativePath.Split("/")) {
        if (
            [string]::IsNullOrWhiteSpace($Segment) -or
            $Segment -eq "." -or
            $Segment -eq ".."
        ) {
            throw "Backup artifact path is invalid: '$RelativePath'."
        }
    }
    $Path = [System.IO.Path]::GetFullPath(
        (Join-Path $BackupRoot ($RelativePath.Replace(
            "/",
            [System.IO.Path]::DirectorySeparatorChar
        )))
    )
    if (-not (Test-WindowsPathWithin -Parent $BackupRoot -Candidate $Path)) {
        throw "Backup artifact escapes the backup directory: '$RelativePath'."
    }
    return $Path
}

function Get-WindowsRelativeArtifactPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root,

        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $RootPath = [System.IO.Path]::GetFullPath($Root).TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
    $PathValue = [System.IO.Path]::GetFullPath($Path)
    if (-not (Test-WindowsPathWithin -Parent $RootPath -Candidate $PathValue)) {
        throw "File is outside the backup staging directory: $PathValue"
    }
    $Relative = $PathValue.Substring($RootPath.Length).TrimStart(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
    return $Relative.Replace(
        [System.IO.Path]::DirectorySeparatorChar,
        "/"
    )
}

function Get-WindowsCmsCertificate {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Thumbprint
    )

    $Path = "Cert:\CurrentUser\My\$($Thumbprint.ToUpperInvariant())"
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Document encryption certificate was not found: $Thumbprint"
    }
    return Get-Item -LiteralPath $Path
}

function Invoke-WindowsPostgresQuery {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$ComposeBaseArguments,

        [Parameter(Mandatory = $true)]
        [string]$User,

        [Parameter(Mandatory = $true)]
        [string]$Database,

        [Parameter(Mandatory = $true)]
        [string]$Sql
    )

    $Output = Invoke-WindowsDocker -Arguments @(
        $ComposeBaseArguments +
        @(
            "exec", "--no-TTY",
            "postgres",
            "psql",
            "-U", $User,
            "-d", $Database,
            "-At",
            "-v", "ON_ERROR_STOP=1",
            "-c", $Sql
        )
    )
    return [string](($Output -join "`n").Trim())
}

function Wait-WindowsComposeServices {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$ComposeBaseArguments,

        [Parameter(Mandatory = $true)]
        [string[]]$Services,

        [ValidateRange(1, 3600)]
        [int]$TimeoutSeconds = 180
    )

    if ($Services.Count -eq 0) {
        return
    }
    $Deadline = [System.DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $Containers = @(
            Get-WindowsComposeContainers -ComposeBaseArguments $ComposeBaseArguments
        )
        $Ready = $true
        foreach ($ServiceName in $Services) {
            $Container = @(
                $Containers |
                    Where-Object { [string]$_.Service -eq $ServiceName }
            ) | Select-Object -First 1
            if ($null -eq $Container -or [string]$Container.State -ne "running") {
                $Ready = $false
                break
            }
            if (
                $null -ne $Container.PSObject.Properties["Health"] -and
                -not [string]::IsNullOrWhiteSpace([string]$Container.Health) -and
                [string]$Container.Health -ne "healthy"
            ) {
                $Ready = $false
                break
            }
        }
        if ($Ready) {
            return
        }
        Start-Sleep -Seconds 2
    } while ([System.DateTime]::UtcNow -lt $Deadline)

    throw "Services did not become ready within $TimeoutSeconds seconds: $($Services -join ', ')."
}

function Stop-WindowsComposeServices {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$ComposeBaseArguments,

        [Parameter(Mandatory = $true)]
        [string[]]$RunningServices,

        [Parameter(Mandatory = $true)]
        [string[]]$RequestedServices,

        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [System.Collections.Generic.List[string]]$StoppedServices,

        [ValidateRange(30, 3600)]
        [int]$TimeoutSeconds
    )

    $Services = @(
        $RequestedServices |
            Where-Object { $_ -in $RunningServices }
    )
    if ($Services.Count -eq 0) {
        return
    }
    foreach ($ServiceName in $Services) {
        if (-not $StoppedServices.Contains($ServiceName)) {
            $StoppedServices.Add($ServiceName)
        }
    }
    $null = Invoke-WindowsDocker -Arguments @(
        $ComposeBaseArguments +
        @("stop", "--timeout", $TimeoutSeconds.ToString()) +
        $Services
    )

    $Containers = @(
        Get-WindowsComposeContainers -ComposeBaseArguments $ComposeBaseArguments
    )
    foreach ($ServiceName in $Services) {
        $Container = @(
            $Containers |
                Where-Object { [string]$_.Service -eq $ServiceName }
        ) | Select-Object -First 1
        if ($null -eq $Container -or [string]$Container.State -ne "exited") {
            throw "Service did not stop cleanly: $ServiceName"
        }
        if (
            $null -ne $Container.PSObject.Properties["ExitCode"] -and
            [int]$Container.ExitCode -eq 137
        ) {
            throw "Service was force-killed after the quiesce timeout: $ServiceName"
        }
    }
}

function Restore-WindowsSourceServiceState {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$ComposeBaseArguments,

        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [object[]]$OriginalServiceStates
    )

    $ExpectedRunning = @(
        $OriginalServiceStates |
            Where-Object { [string]$_.state -eq "running" } |
            ForEach-Object { [string]$_.service } |
            Sort-Object -Unique
    )
    $ExpectedExited = @(
        $OriginalServiceStates |
            Where-Object { [string]$_.state -eq "exited" } |
            ForEach-Object { [string]$_.service } |
            Sort-Object -Unique
    )
    $RecoveryErrors = New-Object "System.Collections.Generic.List[string]"
    foreach ($Group in @(
        @("postgres"),
        @("redis", "minio", "opensearch"),
        @("api"),
        @(
            "worker-audit",
            "worker-permission",
            "worker-preview",
            "worker-search",
            "worker-maintenance",
            "beat"
        ),
        @("gateway")
    )) {
        try {
            $CurrentRunning = @(
                Get-WindowsComposeRunningServices `
                    -ComposeBaseArguments $ComposeBaseArguments
            )
            $Services = @(
                $Group |
                    Where-Object {
                        $_ -in $ExpectedRunning -and
                        $_ -notin $CurrentRunning
                    }
            )
            if ($Services.Count -eq 0) {
                continue
            }
            $null = Invoke-WindowsDocker -Arguments @(
                $ComposeBaseArguments +
                @(
                    "up",
                    "--detach",
                    "--no-deps",
                    "--no-build",
                    "--pull", "never"
                ) +
                $Services
            )
            Wait-WindowsComposeServices `
                -ComposeBaseArguments $ComposeBaseArguments `
                -Services $Services `
                -TimeoutSeconds 180
        }
        catch {
            $RecoveryErrors.Add(
                "$($Group -join ', '): $($_.Exception.Message)"
            )
        }
    }

    try {
        $CurrentRunning = @(
            Get-WindowsComposeRunningServices `
                -ComposeBaseArguments $ComposeBaseArguments
        )
        $UnexpectedRunning = @(
            $ExpectedExited |
                Where-Object { $_ -in $CurrentRunning }
        )
        if ($UnexpectedRunning.Count -gt 0) {
            $null = Invoke-WindowsDocker -Arguments @(
                $ComposeBaseArguments +
                @("stop", "--timeout", "60") +
                $UnexpectedRunning
            )
        }
    }
    catch {
        $RecoveryErrors.Add(
            "unexpected service stop failed: $($_.Exception.Message)"
        )
    }

    try {
        $FinalContainers = @(
            Get-WindowsComposeContainers `
                -ComposeBaseArguments $ComposeBaseArguments
        )
        $FinalMap = @{}
        foreach ($Container in $FinalContainers) {
            $ServiceName = [string]$Container.Service
            if ($FinalMap.ContainsKey($ServiceName)) {
                $RecoveryErrors.Add(
                    "service has multiple containers after recovery: $ServiceName"
                )
                continue
            }
            $FinalMap[$ServiceName] = $Container
        }
        foreach ($StateRecord in $OriginalServiceStates) {
            $ServiceName = [string]$StateRecord.service
            $ExpectedState = [string]$StateRecord.state
            if (
                -not $FinalMap.ContainsKey($ServiceName) -or
                [string]$FinalMap[$ServiceName].State -ne $ExpectedState
            ) {
                $RecoveryErrors.Add(
                    "service state mismatch after recovery: $ServiceName"
                )
                continue
            }
            if (
                $ExpectedState -eq "running" -and
                $null -ne $FinalMap[$ServiceName].PSObject.Properties["Health"] -and
                -not [string]::IsNullOrWhiteSpace(
                    [string]$FinalMap[$ServiceName].Health
                ) -and
                [string]$FinalMap[$ServiceName].Health -ne "healthy"
            ) {
                $RecoveryErrors.Add(
                    "service health mismatch after recovery: $ServiceName"
                )
            }
        }
    }
    catch {
        $RecoveryErrors.Add("final state check failed: $($_.Exception.Message)")
    }
    if ($RecoveryErrors.Count -gt 0) {
        throw "Source service recovery failed: $($RecoveryErrors -join '; ')"
    }
}

function Invoke-WindowsVolumeArchive {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ArchiveToolImage,

        [Parameter(Mandatory = $true)]
        [string]$VolumeName,

        [Parameter(Mandatory = $true)]
        [string]$BackupDirectory,

        [Parameter(Mandatory = $true)]
        [string]$ArchiveRelativePath,

        [switch]$SkipImmediateVerification
    )

    $ArchivePath = Resolve-WindowsBackupArtifactPath `
        -BackupRoot $BackupDirectory `
        -RelativePath $ArchiveRelativePath
    $null = New-Item -ItemType Directory -Path (
        Split-Path -Parent $ArchivePath
    ) -Force
    $Bind = "type=bind,source=$BackupDirectory,target=/backup"
    $Volume = "type=volume,source=$VolumeName,target=/source,readonly"
    $ScriptPath = "/backup/$ArchiveRelativePath"
    $Settings = Get-WindowsBackupHelperSettings
    $ArchiveCommand = (
        "tar --numeric-owner --use-compress-program='gzip " +
        "-$($Settings.gzip_level)' -C /source -cf '$ScriptPath' ."
    )
    if (-not $SkipImmediateVerification) {
        $ArchiveCommand += "; tar -tzf '$ScriptPath' >/dev/null"
    }
    $null = Invoke-WindowsBackupHelperContainer -Arguments @(
        "--network", "none",
        "--entrypoint", "sh",
        "--mount", $Volume,
        "--mount", $Bind,
        $ArchiveToolImage,
        "-ec",
        $ArchiveCommand
    )
}

function Get-WindowsVolumeInspection {
    param(
        [Parameter(Mandatory = $true)]
        [string]$VolumeName
    )

    $Output = @()
    $ExitCode = 1
    $PreviousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $Output = @(
            & docker volume inspect --format "{{json .}}" $VolumeName 2>&1
        )
        $ExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }
    $Text = [string](($Output | ForEach-Object { [string]$_ }) -join "`n")
    if ($ExitCode -eq 0) {
        if ([string]::IsNullOrWhiteSpace($Text)) {
            throw "docker volume inspect returned no data: $VolumeName"
        }
        return $Text | ConvertFrom-Json
    }
    if ($Text -match "(?i)no such volume") {
        return $null
    }
    throw "docker volume inspect failed for '$VolumeName': $Text"
}

function Get-WindowsVolumeAttachedContainerIds {
    param(
        [Parameter(Mandatory = $true)]
        [string]$VolumeName
    )

    return @(
        Invoke-WindowsDocker -Arguments @(
            "ps",
            "--all",
            "--filter",
            "volume=$VolumeName",
            "--format",
            "{{.ID}}"
        ) |
            ForEach-Object { ([string]$_).Trim() } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            Sort-Object -Unique
    )
}

function Assert-WindowsVolumeAttachments {
    param(
        [Parameter(Mandatory = $true)]
        [string]$VolumeName,

        [Parameter(Mandatory = $true)]
        [string]$ProjectName
    )

    foreach (
        $ContainerId in @(
            Get-WindowsVolumeAttachedContainerIds -VolumeName $VolumeName
        )
    ) {
        $LabelsJson = (
            Invoke-WindowsDocker -Arguments @(
                "container",
                "inspect",
                "--format",
                "{{json .Config.Labels}}",
                $ContainerId
            )
        ) -join "`n"
        if ([string]::IsNullOrWhiteSpace($LabelsJson)) {
            throw "Attached container has no labels: $ContainerId"
        }
        $Labels = $LabelsJson | ConvertFrom-Json
        $ProjectProperty = $Labels.PSObject.Properties[
            "com.docker.compose.project"
        ]
        if (
            $null -eq $ProjectProperty -or
            [string]$ProjectProperty.Value -ne $ProjectName
        ) {
            throw (
                "Volume '$VolumeName' is attached to a container outside " +
                "Compose project '$ProjectName'."
            )
        }
    }
}

function Assert-WindowsVolumeLabels {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Inspection,

        [Parameter(Mandatory = $true)]
        [string]$ProjectName,

        [Parameter(Mandatory = $true)]
        [string]$LogicalName
    )

    $LabelsProperty = $Inspection.PSObject.Properties["Labels"]
    if ($null -eq $LabelsProperty -or $null -eq $LabelsProperty.Value) {
        throw "Existing target volume has no Compose labels: $LogicalName"
    }
    $ProjectProperty = $LabelsProperty.Value.PSObject.Properties[
        "com.docker.compose.project"
    ]
    $VolumeProperty = $LabelsProperty.Value.PSObject.Properties[
        "com.docker.compose.volume"
    ]
    if (
        $null -eq $ProjectProperty -or
        [string]$ProjectProperty.Value -ne $ProjectName -or
        $null -eq $VolumeProperty -or
        [string]$VolumeProperty.Value -ne $LogicalName
    ) {
        throw "Existing target volume Compose labels do not match: $LogicalName"
    }
}

function Test-WindowsVolumeEmpty {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ArchiveToolImage,

        [Parameter(Mandatory = $true)]
        [string]$VolumeName
    )

    $Output = Invoke-WindowsBackupHelperContainer -Arguments @(
        "--network", "none",
        "--entrypoint", "sh",
        "--mount", "type=volume,source=$VolumeName,target=/target",
        $ArchiveToolImage,
        "-ec",
        (
            "probe=`$(find /target -mindepth 1 -printf x -quit) || exit 42; " +
            "case x`$probe in xx) printf 'nonempty' ;; " +
            "x) printf 'empty' ;; *) exit 43 ;; esac"
        )
    )
    $State = [string](($Output -join "").Trim())
    if ($State -eq "empty") {
        return $true
    }
    if ($State -eq "nonempty") {
        return $false
    }
    throw "Volume emptiness probe returned an invalid result: $VolumeName"
}

function Clear-WindowsVolume {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ArchiveToolImage,

        [Parameter(Mandatory = $true)]
        [string]$VolumeName
    )

    $null = Invoke-WindowsBackupHelperContainer -Arguments @(
        "--network", "none",
        "--entrypoint", "sh",
        "--mount", "type=volume,source=$VolumeName,target=/target",
        $ArchiveToolImage,
        "-ec",
        "find /target -mindepth 1 -xdev -delete"
    )
}

function Restore-WindowsVolumeArchive {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ArchiveToolImage,

        [Parameter(Mandatory = $true)]
        [string]$VolumeName,

        [Parameter(Mandatory = $true)]
        [string]$BackupDirectory,

        [Parameter(Mandatory = $true)]
        [string]$ArchiveRelativePath
    )

    $null = Resolve-WindowsBackupArtifactPath `
        -BackupRoot $BackupDirectory `
        -RelativePath $ArchiveRelativePath
    $null = Invoke-WindowsBackupHelperContainer -Arguments @(
        "--network", "none",
        "--entrypoint", "sh",
        "--mount", "type=volume,source=$VolumeName,target=/target",
        "--mount", "type=bind,source=$BackupDirectory,target=/backup,readonly",
        $ArchiveToolImage,
        "-ec",
        "tar --numeric-owner -C /target -xzf '/backup/$ArchiveRelativePath'"
    )
}

function Get-WindowsManifestArtifact {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Manifest,

        [Parameter(Mandatory = $true)]
        [string]$RelativePath
    )

    $Artifacts = Get-WindowsModelPropertyValue `
        -Object $Manifest `
        -Name "artifacts" `
        -Label "Backup manifest"
    $ArtifactMatches = @(
        $Artifacts |
            Where-Object { [string]$_.path -eq $RelativePath }
    )
    if ($ArtifactMatches.Count -ne 1) {
        throw "Backup manifest must contain exactly one '$RelativePath' artifact."
    }
    return $ArtifactMatches[0]
}

function Assert-WindowsObjectProperties {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Object,

        [Parameter(Mandatory = $true)]
        [string[]]$Names,

        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    foreach ($Name in $Names) {
        if ($null -eq $Object.PSObject.Properties[$Name]) {
            throw "$Label is missing '$Name'."
        }
    }
}

function Assert-WindowsNonEmptyProperty {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Object,

        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    Assert-WindowsObjectProperties `
        -Object $Object `
        -Names @($Name) `
        -Label $Label
    if ([string]::IsNullOrWhiteSpace([string]$Object.$Name)) {
        throw "$Label has an empty '$Name'."
    }
}

function Get-WindowsManifestVolumeMap {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Manifest
    )

    $ExpectedModes = [ordered]@{
        "postgres-data" = "pg_dump"
        "redis-data" = "stopped-volume-tar"
        "minio-data" = "stopped-volume-tar"
        "opensearch-data" = "stopped-volume-tar"
        "tls-certificates" = "stopped-volume-tar"
    }
    $Map = @{}
    $PhysicalNames = New-Object "System.Collections.Generic.HashSet[string]" (
        [System.StringComparer]::OrdinalIgnoreCase
    )
    foreach ($Volume in @($Manifest.volumes)) {
        Assert-WindowsObjectProperties `
            -Object $Volume `
            -Names @("logical_name", "physical_name", "backup_mode") `
            -Label "Backup manifest volume"
        $LogicalName = [string]$Volume.logical_name
        $PhysicalName = [string]$Volume.physical_name
        $BackupMode = [string]$Volume.backup_mode
        if (
            [string]::IsNullOrWhiteSpace($LogicalName) -or
            [string]::IsNullOrWhiteSpace($PhysicalName)
        ) {
            throw "Backup manifest volume has an empty logical or physical name."
        }
        if (-not $ExpectedModes.Contains($LogicalName)) {
            throw "Backup manifest contains an unexpected volume: $LogicalName"
        }
        if ($Map.ContainsKey($LogicalName)) {
            throw "Backup manifest contains a duplicate volume: $LogicalName"
        }
        if (-not $PhysicalNames.Add($PhysicalName)) {
            throw "Backup manifest reuses a physical volume name: $PhysicalName"
        }
        if ($BackupMode -ne [string]$ExpectedModes[$LogicalName]) {
            throw "Backup manifest volume mode is invalid: $LogicalName"
        }
        $Map[$LogicalName] = $Volume
    }
    foreach ($LogicalName in $ExpectedModes.Keys) {
        if (-not $Map.ContainsKey($LogicalName)) {
            throw "Backup manifest volume is missing: $LogicalName"
        }
    }
    if ($Map.Count -ne $ExpectedModes.Count) {
        throw "Backup manifest volume set is invalid."
    }
    return $Map
}

function Get-WindowsManifestImageMap {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Manifest,

        [Parameter(Mandatory = $true)]
        [string[]]$ExpectedServices
    )

    $Expected = New-Object "System.Collections.Generic.HashSet[string]" (
        [System.StringComparer]::OrdinalIgnoreCase
    )
    foreach ($ServiceName in $ExpectedServices) {
        $null = $Expected.Add($ServiceName)
    }
    $Map = @{}
    foreach ($Image in @($Manifest.images)) {
        Assert-WindowsObjectProperties `
            -Object $Image `
            -Names @(
                "service",
                "reference",
                "id",
                "repo_digests",
                "created",
                "source",
                "container_id"
            ) `
            -Label "Backup manifest image"
        $ServiceName = [string]$Image.service
        if (-not $Expected.Contains($ServiceName)) {
            throw "Backup manifest contains an unexpected image service: $ServiceName"
        }
        if ($Map.ContainsKey($ServiceName)) {
            throw "Backup manifest contains a duplicate image service: $ServiceName"
        }
        foreach ($PropertyName in @(
            "reference",
            "id",
            "created",
            "source",
            "container_id"
        )) {
            if ([string]::IsNullOrWhiteSpace([string]$Image.$PropertyName)) {
                throw "Backup manifest image '$ServiceName' has an empty '$PropertyName'."
            }
        }
        if ([string]$Image.id -notmatch "^sha256:[0-9a-f]{64}$") {
            throw "Backup manifest image ID is invalid: $ServiceName"
        }
        if ($Image.repo_digests -isnot [System.Array]) {
            throw "Backup manifest image repo_digests must be an array: $ServiceName"
        }
        if ([string]$Image.source -ne "container") {
            throw "Backup manifest image source is invalid: $ServiceName"
        }
        $Map[$ServiceName] = $Image
    }
    foreach ($ServiceName in $ExpectedServices) {
        if (-not $Map.ContainsKey($ServiceName)) {
            throw "Backup manifest image is missing: $ServiceName"
        }
    }
    if ($Map.Count -ne $Expected.Count) {
        throw "Backup manifest image service set is invalid."
    }
    return $Map
}

function Assert-WindowsManifestNestedData {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Manifest,

        [Parameter(Mandatory = $true)]
        [string[]]$ExpectedImageServices
    )

    foreach ($CollectionName in @(
        "artifacts",
        "volumes",
        "images",
        "running_services",
        "service_states"
    )) {
        if ($Manifest.$CollectionName -isnot [System.Array]) {
            throw "Backup manifest '$CollectionName' must be an array."
        }
    }
    foreach ($PropertyName in @(
        "backup_id",
        "created_at_utc",
        "quiesced_at_utc",
        "source_project",
        "project_version",
        "git_commit",
        "compose_sha256",
        "archive_tool_image",
        "archive_tool_image_id"
    )) {
        Assert-WindowsNonEmptyProperty `
            -Object $Manifest `
            -Name $PropertyName `
            -Label "Backup manifest"
    }
    if ([string]$Manifest.backup_id -notmatch "^[0-9a-f]{32}$") {
        throw "Backup manifest ID is invalid."
    }
    if ([string]$Manifest.project_version -notmatch "^[0-9]+\.[0-9]+\.[0-9]+$") {
        throw "Backup manifest project version is invalid."
    }
    if ([string]$Manifest.compose_sha256 -notmatch "^[0-9a-f]{64}$") {
        throw "Backup manifest Compose SHA-256 is invalid."
    }
    if ([string]$Manifest.git_commit -notmatch "^[0-9a-f]{40,64}$") {
        throw "Backup manifest Git commit is invalid."
    }
    if ([string]$Manifest.archive_tool_image_id -notmatch "^sha256:[0-9a-f]{64}$") {
        throw "Backup manifest archive tool image ID is invalid."
    }
    foreach ($TimestampName in @("created_at_utc", "quiesced_at_utc")) {
        $ParsedTimestamp = [System.DateTime]::MinValue
        if (
            [string]$Manifest.$TimestampName -notmatch "(?:Z|\+00:00)$" -or
            -not [System.DateTime]::TryParse(
                [string]$Manifest.$TimestampName,
                [System.Globalization.CultureInfo]::InvariantCulture,
                [System.Globalization.DateTimeStyles]::RoundtripKind,
                [ref]$ParsedTimestamp
            )
        ) {
            throw "Backup manifest timestamp is invalid: $TimestampName"
        }
    }

    Assert-WindowsObjectProperties `
        -Object $Manifest.database `
        -Names @(
            "name",
            "user",
            "server_version",
            "alembic_revision",
            "wal_lsn",
            "dump_format"
        ) `
        -Label "Backup manifest database"
    foreach ($PropertyName in @(
        "name",
        "user",
        "server_version",
        "alembic_revision",
        "wal_lsn",
        "dump_format"
    )) {
        if ([string]::IsNullOrWhiteSpace([string]$Manifest.database.$PropertyName)) {
            throw "Backup manifest database has an empty '$PropertyName'."
        }
    }
    if ([string]$Manifest.database.dump_format -ne "custom") {
        throw "Backup manifest database dump format is unsupported."
    }
    if ([string]$Manifest.database.wal_lsn -notmatch "^[0-9A-F]+/[0-9A-F]+$") {
        throw "Backup manifest database WAL LSN is invalid."
    }

    Assert-WindowsObjectProperties `
        -Object $Manifest.environment `
        -Names @("included", "protection", "certificate_thumbprint") `
        -Label "Backup manifest environment"
    if ($Manifest.environment.included -isnot [bool]) {
        throw "Backup manifest environment included flag must be Boolean."
    }
    if ([bool]$Manifest.environment.included) {
        if ([string]$Manifest.environment.protection -ne "windows-cms") {
            throw "Backup manifest environment protection is invalid."
        }
        if (
            [string]$Manifest.environment.certificate_thumbprint -notmatch
            "^[A-Fa-f0-9]{40}$"
        ) {
            throw "Backup manifest environment certificate thumbprint is invalid."
        }
    }
    elseif (
        [string]$Manifest.environment.protection -ne "skipped" -or
        -not [string]::IsNullOrWhiteSpace(
            [string]$Manifest.environment.certificate_thumbprint
        )
    ) {
        throw "Backup manifest skipped environment metadata is invalid."
    }

    Assert-WindowsObjectProperties `
        -Object $Manifest.configuration `
        -Names @("s3_bucket", "opensearch_index_name", "tls_certificate_name") `
        -Label "Backup manifest configuration"
    foreach ($PropertyName in @(
        "s3_bucket",
        "opensearch_index_name",
        "tls_certificate_name"
    )) {
        if (
            [string]::IsNullOrWhiteSpace(
                [string]$Manifest.configuration.$PropertyName
            )
        ) {
            throw "Backup manifest configuration has an empty '$PropertyName'."
        }
    }

    $ServiceStateMap = @{}
    foreach ($StateRecord in @($Manifest.service_states)) {
        Assert-WindowsObjectProperties `
            -Object $StateRecord `
            -Names @(
                "service",
                "state",
                "health",
                "exit_code",
                "container_id"
            ) `
            -Label "Backup manifest service state"
        $ServiceName = [string]$StateRecord.service
        $State = [string]$StateRecord.state
        if ($ServiceName -notin $ExpectedImageServices) {
            throw "Backup manifest service state is unexpected: $ServiceName"
        }
        if ($State -notin @("running", "exited")) {
            throw "Backup manifest service state is invalid: $ServiceName"
        }
        if ([string]::IsNullOrWhiteSpace([string]$StateRecord.container_id)) {
            throw "Backup manifest service state has an empty container ID: $ServiceName"
        }
        if (
            $State -eq "running" -and
            -not [string]::IsNullOrWhiteSpace([string]$StateRecord.health) -and
            [string]$StateRecord.health -ne "healthy"
        ) {
            throw "Backup manifest service health is invalid: $ServiceName"
        }
        if ($ServiceStateMap.ContainsKey($ServiceName)) {
            throw "Backup manifest service state is duplicated: $ServiceName"
        }
        $ServiceStateMap[$ServiceName] = $State
    }
    foreach ($ServiceName in $ExpectedImageServices) {
        if (-not $ServiceStateMap.ContainsKey($ServiceName)) {
            throw "Backup manifest service state is missing: $ServiceName"
        }
    }
    if ($ServiceStateMap.Count -ne $ExpectedImageServices.Count) {
        throw "Backup manifest service state set is invalid."
    }
    if (
        -not $ServiceStateMap.ContainsKey("postgres") -or
        [string]$ServiceStateMap["postgres"] -ne "running"
    ) {
        throw "Backup manifest must record PostgreSQL as running."
    }
    $RunningServiceSet = New-Object "System.Collections.Generic.HashSet[string]" (
        [System.StringComparer]::OrdinalIgnoreCase
    )
    foreach ($ServiceName in @($Manifest.running_services)) {
        if (
            [string]::IsNullOrWhiteSpace([string]$ServiceName) -or
            -not $RunningServiceSet.Add([string]$ServiceName)
        ) {
            throw "Backup manifest running service set is invalid."
        }
    }
    foreach ($ServiceName in $ExpectedImageServices) {
        $ExpectedRunning = [string]$ServiceStateMap[$ServiceName] -eq "running"
        if ($RunningServiceSet.Contains($ServiceName) -ne $ExpectedRunning) {
            throw "Backup manifest running service state mismatch: $ServiceName"
        }
    }

    $null = Get-WindowsManifestVolumeMap -Manifest $Manifest
    $null = Get-WindowsManifestImageMap `
        -Manifest $Manifest `
        -ExpectedServices $ExpectedImageServices
}

function Test-WindowsTarArchiveEntries {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ArchiveToolImage,

        [Parameter(Mandatory = $true)]
        [string]$BackupDirectory,

        [Parameter(Mandatory = $true)]
        [string]$RelativePath
    )

    $TemporaryVolume = (
        "enterprise-drive-archive-verify-" +
        [Guid]::NewGuid().ToString("N")
    )
    $TemporaryVolumeCreated = $false
    $OriginalFailure = $null
    $CleanupFailure = $null
    try {
        $Output = Invoke-WindowsBackupHelperContainer -Arguments @(
            "--network", "none",
            "--read-only",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--entrypoint", "sh",
            "--mount", "type=bind,source=$BackupDirectory,target=/backup,readonly",
            $ArchiveToolImage,
            "-ec",
            "tar -tzf '/backup/$RelativePath'"
        )
        foreach ($RawEntry in @($Output)) {
            $Entry = ([string]$RawEntry).Replace("\", "/")
            while ($Entry.StartsWith("./")) {
                $Entry = $Entry.Substring(2)
            }
            if ([string]::IsNullOrWhiteSpace($Entry)) {
                continue
            }
            if ($Entry.StartsWith("/")) {
                throw "Tar archive contains an absolute path: $RelativePath"
            }
            foreach ($Segment in $Entry.Split("/")) {
                if ($Segment -eq "..") {
                    throw "Tar archive contains a parent traversal entry: $RelativePath"
                }
            }
        }

        $null = Invoke-WindowsDocker -Arguments @(
            "volume",
            "create",
            "--label",
            "enterprise-drive.archive-verification=true",
            $TemporaryVolume
        )
        $TemporaryVolumeCreated = $true
        $ScanScript = @(
            "set -eu",
            (
                "if tar -tvzf '/backup/$RelativePath' | " +
                "grep -F ' link to ' >/dev/null; then exit 44; fi"
            ),
            (
                "tar --no-same-owner --no-same-permissions " +
                "-C /target -xzf '/backup/$RelativePath'"
            ),
            (
                "if find /target -xdev " +
                "\( -type b -o -type c -o -type p -o -type s \) " +
                "-print -quit | grep -q .; then exit 45; fi"
            ),
            (
                "if find /target -xdev -type l ! -exec test -e {} \; " +
                "-print -quit | grep -q .; then exit 46; fi"
            ),
            (
                "if find /target -xdev -type l -exec readlink -f {} \; | " +
                "grep -Ev '^/target(/|`$)' | grep -q .; then exit 47; fi"
            )
        ) -join "; "
        $null = Invoke-WindowsBackupHelperContainer -Arguments @(
            "--network", "none",
            "--read-only",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--entrypoint", "sh",
            "--mount", "type=bind,source=$BackupDirectory,target=/backup,readonly",
            "--mount", "type=volume,source=$TemporaryVolume,target=/target",
            $ArchiveToolImage,
            "-ec",
            $ScanScript
        )
    }
    catch {
        $OriginalFailure = $_
    }
    finally {
        if ($TemporaryVolumeCreated) {
            try {
                $null = Invoke-WindowsDocker -Arguments @(
                    "volume",
                    "rm",
                    $TemporaryVolume
                )
            }
            catch {
                $CleanupFailure = $_
            }
        }
    }
    if ($null -ne $OriginalFailure) {
        if ($null -ne $CleanupFailure) {
            throw (
                "Tar archive verification and temporary volume cleanup failed. " +
                "Verification error: $($OriginalFailure.Exception.Message). " +
                "Cleanup error: $($CleanupFailure.Exception.Message)"
            )
        }
        throw $OriginalFailure
    }
    if ($null -ne $CleanupFailure) {
        throw $CleanupFailure
    }
}

function Test-WindowsBackup {
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
        [string]$BackupPath
    )

    $null = $EnvFile

    $VerifyStopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    $Root = [System.IO.Path]::GetFullPath($BackupPath)
    Write-Host "[backup-verify:start] $Root"
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
        throw "Backup directory does not exist: $Root"
    }
    Assert-WindowsNoReparsePoint -Path $Root -Label "Backup directory"
    $ManifestPath = Join-Path $Root "manifest.json"
    $ManifestChecksumPath = Join-Path $Root "manifest.sha256"
    if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
        throw "Backup manifest is missing: $ManifestPath"
    }
    if (-not (Test-Path -LiteralPath $ManifestChecksumPath -PathType Leaf)) {
        throw "Backup manifest checksum is missing: $ManifestChecksumPath"
    }
    Assert-WindowsNoReparsePoint -Path $ManifestPath -Label "Backup manifest"
    Assert-WindowsNoReparsePoint `
        -Path $ManifestChecksumPath `
        -Label "Backup manifest checksum"

    $StrictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)
    $ChecksumText = [System.IO.File]::ReadAllText(
        $ManifestChecksumPath,
        $StrictUtf8
    ).Trim()
    $ChecksumMatch = [regex]::Match(
        $ChecksumText,
        '^(?<hash>[0-9a-f]{64})\s+manifest\.json$'
    )
    if (-not $ChecksumMatch.Success) {
        throw "manifest.sha256 has an invalid format."
    }
    $ActualManifestHash = Get-WindowsSha256 -Path $ManifestPath
    if ($ActualManifestHash -ne $ChecksumMatch.Groups["hash"].Value) {
        throw "Backup manifest SHA-256 verification failed."
    }

    $ManifestText = [System.IO.File]::ReadAllText($ManifestPath, $StrictUtf8)
    $Manifest = $ManifestText | ConvertFrom-Json
    foreach ($RequiredProperty in @(
        "format_version",
        "backup_id",
        "created_at_utc",
        "quiesced_at_utc",
        "source_project",
        "project_version",
        "git_commit",
        "compose_sha256",
        "archive_tool_image",
        "archive_tool_image_id",
        "running_services",
        "service_states",
        "artifacts",
        "volumes",
        "images",
        "database",
        "environment",
        "configuration"
    )) {
        if ($null -eq $Manifest.PSObject.Properties[$RequiredProperty]) {
            throw "Backup manifest is missing '$RequiredProperty'."
        }
    }
    if (
        $Manifest.format_version -isnot [int] -and
        $Manifest.format_version -isnot [long]
    ) {
        throw "Backup format version must be an integer."
    }
    if ([int64]$Manifest.format_version -ne 1) {
        throw "Unsupported backup format version: $($Manifest.format_version)"
    }

    $CurrentComposeModel = Get-WindowsComposeModel `
        -ComposeBaseArguments $ComposeBaseArguments
    $ExpectedImageServices = @(
        Get-WindowsComposeDefaultServiceNames `
            -ComposeModel $CurrentComposeModel
    )
    Assert-WindowsManifestNestedData `
        -Manifest $Manifest `
        -ExpectedImageServices $ExpectedImageServices

    $SeenPaths = New-Object "System.Collections.Generic.HashSet[string]" (
        [System.StringComparer]::OrdinalIgnoreCase
    )
    foreach ($Artifact in @($Manifest.artifacts)) {
        foreach ($PropertyName in @("path", "size_bytes", "sha256")) {
            if ($null -eq $Artifact.PSObject.Properties[$PropertyName]) {
                throw "Backup artifact is missing '$PropertyName'."
            }
        }
        if (
            (
                $Artifact.size_bytes -isnot [int] -and
                $Artifact.size_bytes -isnot [long]
            ) -or
            [int64]$Artifact.size_bytes -lt 0
        ) {
            throw "Backup artifact has an invalid size."
        }
        if ([string]$Artifact.sha256 -notmatch "^[0-9a-f]{64}$") {
            throw "Backup artifact has an invalid SHA-256."
        }
        $RelativePath = [string]$Artifact.path
        if (-not $SeenPaths.Add($RelativePath)) {
            throw "Backup manifest contains a duplicate artifact path: $RelativePath"
        }
        if (
            [int64]$Artifact.size_bytes -lt 0 -or
            [string]$Artifact.sha256 -notmatch "^[0-9a-f]{64}$"
        ) {
            throw "Backup artifact metadata is invalid: $RelativePath"
        }
        $ArtifactPath = Resolve-WindowsBackupArtifactPath `
            -BackupRoot $Root `
            -RelativePath $RelativePath
        if (-not (Test-Path -LiteralPath $ArtifactPath -PathType Leaf)) {
            throw "Backup artifact is missing: $RelativePath"
        }
        Assert-WindowsNoReparsePoint `
            -Path $ArtifactPath `
            -Label "Backup artifact '$RelativePath'"
        $File = Get-Item -LiteralPath $ArtifactPath
        if ([int64]$File.Length -ne [int64]$Artifact.size_bytes) {
            throw "Backup artifact size verification failed: $RelativePath"
        }
        if ((Get-WindowsSha256 -Path $ArtifactPath) -ne [string]$Artifact.sha256) {
            throw "Backup artifact SHA-256 verification failed: $RelativePath"
        }
    }

    foreach ($RequiredArtifact in @(
        "postgres/postgres.dump",
        "volumes/minio-data.tar.gz",
        "volumes/redis-data.tar.gz",
        "volumes/opensearch-data.tar.gz",
        "volumes/tls-certificates.tar.gz",
        "config/compose.windows.yml",
        "config/nginx/acme-bootstrap.conf.template",
        "config/nginx/default.conf.template",
        "config/nginx/tls.conf.template"
    )) {
        $null = Get-WindowsManifestArtifact `
            -Manifest $Manifest `
            -RelativePath $RequiredArtifact
    }
    if ([bool]$Manifest.environment.included) {
        $null = Get-WindowsManifestArtifact `
            -Manifest $Manifest `
            -RelativePath "secrets/environment.cms"
    }
    elseif (
        @(
            $Manifest.artifacts |
                Where-Object {
                    [string]$_.path -eq "secrets/environment.cms"
                }
        ).Count -gt 0
    ) {
        throw "Backup manifest contains CMS environment data marked as skipped."
    }
    else {
        $EnvironmentArtifacts = @(
            @($Manifest.artifacts) |
                Where-Object {
                    [string]$_.path -eq "secrets/environment.cms"
                }
        )
        if ($EnvironmentArtifacts.Count -gt 0) {
            throw "Skipped environment backup contains an unexpected CMS artifact."
        }
    }

    $ComposeArtifact = Get-WindowsManifestArtifact `
        -Manifest $Manifest `
        -RelativePath "config/compose.windows.yml"
    if ([string]$ComposeArtifact.sha256 -ne [string]$Manifest.compose_sha256) {
        throw "Backup manifest Compose SHA-256 does not match the archived Compose file."
    }
    if ((Get-WindowsSha256 -Path $ComposeFile) -ne [string]$Manifest.compose_sha256) {
        throw "Current Compose file does not match the backup manifest."
    }
    if (
        (Get-WindowsProjectVersion -RepoRoot $RepoRoot) -ne
        [string]$Manifest.project_version
    ) {
        throw "Current project version does not match the backup manifest."
    }
    if ((Get-WindowsGitCommit -RepoRoot $RepoRoot) -ne [string]$Manifest.git_commit) {
        throw "Current Git commit does not match the backup manifest."
    }

    $ArchiveToolImage = [string]$Manifest.archive_tool_image
    $ArchiveToolImageId = [string]$Manifest.archive_tool_image_id
    $ExpectedArchiveToolImage = Get-WindowsModelServiceImage `
        -ComposeModel $CurrentComposeModel `
        -ServiceName "postgres"
    if ($ArchiveToolImage -ne $ExpectedArchiveToolImage) {
        throw "Backup archive tool image does not match the rendered PostgreSQL image."
    }
    $ImageMap = Get-WindowsManifestImageMap `
        -Manifest $Manifest `
        -ExpectedServices $ExpectedImageServices
    $PostgresImageRecord = $ImageMap["postgres"]
    if ([string]$PostgresImageRecord.reference -ne $ArchiveToolImage) {
        throw "Backup archive tool image does not match its PostgreSQL image record."
    }
    if ([string]$PostgresImageRecord.id -ne $ArchiveToolImageId) {
        throw "Backup archive tool image ID does not match its image record."
    }
    foreach ($ServiceName in $ExpectedImageServices) {
        $TargetReference = Get-WindowsModelServiceImage `
            -ComposeModel $CurrentComposeModel `
            -ServiceName $ServiceName
        $TargetImageInfo = Get-WindowsImageInfo -Image $TargetReference
        $ImageRecord = $ImageMap[$ServiceName]
        if ([string]$ImageRecord.reference -ne $TargetReference) {
            throw "Backup image reference mismatch for $ServiceName."
        }
        if ([string]$ImageRecord.id -ne [string]$TargetImageInfo.id) {
            throw "Backup image ID mismatch for $ServiceName."
        }
    }

    $ExpectedDatabaseName = Get-WindowsModelEnvironmentValue `
        -ComposeModel $CurrentComposeModel `
        -ServiceName "postgres" `
        -Name "POSTGRES_DB"
    $ExpectedDatabaseUser = Get-WindowsModelEnvironmentValue `
        -ComposeModel $CurrentComposeModel `
        -ServiceName "postgres" `
        -Name "POSTGRES_USER"
    if (
        [string]$Manifest.database.name -ne $ExpectedDatabaseName -or
        [string]$Manifest.database.user -ne $ExpectedDatabaseUser
    ) {
        throw "Backup database identity does not match the current Compose model."
    }
    $ExpectedConfiguration = [ordered]@{
        s3_bucket = Get-WindowsModelEnvironmentValue `
            -ComposeModel $CurrentComposeModel `
            -ServiceName "api" `
            -Name "DRIVE_S3_BUCKET"
        opensearch_index_name = Get-WindowsModelEnvironmentValue `
            -ComposeModel $CurrentComposeModel `
            -ServiceName "api" `
            -Name "DRIVE_OPENSEARCH_INDEX_NAME"
        tls_certificate_name = Get-WindowsModelEnvironmentValue `
            -ComposeModel $CurrentComposeModel `
            -ServiceName "gateway" `
            -Name "DRIVE_TLS_CERT_NAME"
    }
    foreach ($PropertyName in $ExpectedConfiguration.Keys) {
        if (
            [string]$Manifest.configuration.$PropertyName -ne
            [string]$ExpectedConfiguration[$PropertyName]
        ) {
            throw "Backup configuration mismatch: $PropertyName"
        }
    }

    Write-Host (
        "[backup-verify] validating PostgreSQL dump ({0:N1}s elapsed)" -f
        $VerifyStopwatch.Elapsed.TotalSeconds
    )
    $null = Invoke-WindowsBackupHelperContainer -Arguments @(
        "--network", "none",
        "--entrypoint", "sh",
        "--mount", "type=bind,source=$Root,target=/backup,readonly",
        $ArchiveToolImageId,
        "-ec",
        "pg_restore --list /backup/postgres/postgres.dump >/dev/null"
    )
    foreach ($ArchivePath in @(
        "volumes/minio-data.tar.gz",
        "volumes/redis-data.tar.gz",
        "volumes/opensearch-data.tar.gz",
        "volumes/tls-certificates.tar.gz"
    )) {
        Write-Host (
            "[backup-verify] scanning {0} ({1:N1}s elapsed)" -f
            $ArchivePath,
            $VerifyStopwatch.Elapsed.TotalSeconds
        )
        Test-WindowsTarArchiveEntries `
            -ArchiveToolImage $ArchiveToolImageId `
            -BackupDirectory $Root `
            -RelativePath $ArchivePath
    }
    Write-Host (
        "[backup-verify:done] {0:N1}s" -f
        $VerifyStopwatch.Elapsed.TotalSeconds
    )
    return $Manifest
}

function Invoke-WindowsBackup {
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
        [string]$BackupDirectory,

        [string]$ConfigEncryptionCertificateThumbprint,

        [switch]$SkipEnvironmentBackup,

        [ValidateRange(30, 3600)]
        [int]$QuiesceTimeoutSeconds = 300
    )

    $BackupStopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    Write-Host "[backup:start] inspecting source containers, volumes, and images"
    $Root = Resolve-WindowsBackupRoot `
        -RepoRoot $RepoRoot `
        -BackupDirectory $BackupDirectory
    $Certificate = $null
    if (-not $SkipEnvironmentBackup) {
        if ([string]::IsNullOrWhiteSpace($ConfigEncryptionCertificateThumbprint)) {
            throw "A document encryption certificate thumbprint is required."
        }
        $Certificate = Get-WindowsCmsCertificate `
            -Thumbprint $ConfigEncryptionCertificateThumbprint
    }

    $ComposeModel = Get-WindowsComposeModel `
        -ComposeBaseArguments $ComposeBaseArguments
    $ProjectName = [string]$ComposeModel.name
    $Mutex = Enter-WindowsDeploymentMutex -ProjectName $ProjectName
    $VolumeMutexes = @()
    $StoppedServices = New-Object "System.Collections.Generic.List[string]"
    $OriginalServiceStates = @()
    $PartialPath = $null
    $PublishedPath = $null
    $OriginalFailure = $null
    $RecoveryErrors = @()
    try {
        $Containers = @(
            Get-WindowsComposeContainers `
                -ComposeBaseArguments $ComposeBaseArguments
        )
        $DefaultServiceNames = @(
            Get-WindowsComposeDefaultServiceNames -ComposeModel $ComposeModel
        )
        $DefaultContainers = @(
            $Containers |
                Where-Object {
                    [string]$_.Service -in $DefaultServiceNames
                }
        )
        foreach ($ServiceName in $DefaultServiceNames) {
            $ServiceContainers = @(
                $DefaultContainers |
                    Where-Object { [string]$_.Service -eq $ServiceName }
            )
            if ($ServiceContainers.Count -ne 1) {
                throw "Compose service '$ServiceName' must have exactly one container before backup."
            }
        }
        $OriginalServiceStates = @(
            Get-WindowsComposeServiceStateRecords -Containers $DefaultContainers
        )
        $OriginalServiceStates = @(
            $OriginalServiceStates | Sort-Object service
        )
        $SupportedRunningServices = @(
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
        foreach ($Container in $Containers) {
            $State = [string]$Container.State
            $ServiceName = [string]$Container.Service
            if ($State -notin @("running", "exited")) {
                throw "Compose service is in a transitional state: $ServiceName ($State)"
            }
            if ($State -eq "running" -and $ServiceName -notin $SupportedRunningServices) {
                throw "Unexpected one-off Compose service is running: $ServiceName"
            }
            $HealthProperty = $Container.PSObject.Properties["Health"]
            if (
                $State -eq "running" -and
                $null -ne $HealthProperty -and
                -not [string]::IsNullOrWhiteSpace([string]$HealthProperty.Value) -and
                [string]$HealthProperty.Value -ne "healthy"
            ) {
                throw "Compose service is not healthy before backup: $ServiceName"
            }
        }
        $RunningServices = @(
            $OriginalServiceStates |
                Where-Object { [string]$_.state -eq "running" } |
                ForEach-Object { [string]$_.service } |
                Sort-Object -Unique
        )
        if ("postgres" -notin $RunningServices) {
            throw "PostgreSQL must be running before backup."
        }

        $VolumeMap = Get-WindowsBackupVolumeMap -ComposeModel $ComposeModel
        $VolumeMutexes = @(
            Enter-WindowsDeploymentMutexSet -ResourceNames @(
                $VolumeMap.Values |
                    ForEach-Object { "volume:$([string]$_)" }
            )
        )
        foreach ($LogicalName in $VolumeMap.Keys) {
            $PhysicalName = [string]$VolumeMap[$LogicalName]
            $Inspection = Get-WindowsVolumeInspection -VolumeName $PhysicalName
            if ($null -eq $Inspection) {
                throw "Required source volume does not exist: $PhysicalName"
            }
            Assert-WindowsVolumeLabels `
                -Inspection $Inspection `
                -ProjectName $ProjectName `
                -LogicalName $LogicalName
            Assert-WindowsVolumeAttachments `
                -VolumeName $PhysicalName `
                -ProjectName $ProjectName
        }

        $ImageRecords = @(
            Get-WindowsComposeImageRecords `
                -ComposeModel $ComposeModel `
                -Containers $DefaultContainers
        )
        $PostgresImageRecord = @(
            $ImageRecords |
                Where-Object { [string]$_.service -eq "postgres" }
        ) | Select-Object -First 1
        if ($null -eq $PostgresImageRecord) {
            throw "PostgreSQL image record was not created."
        }

        Write-Host (
            "[backup] quiescing source services ({0:N1}s elapsed)" -f
            $BackupStopwatch.Elapsed.TotalSeconds
        )
        $BackupId = [Guid]::NewGuid().ToString("N")
        $Timestamp = [System.DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
        $SafeProjectName = [regex]::Replace(
            $ProjectName,
            "[^A-Za-z0-9._-]",
            "-"
        )
        $FinalName = "$Timestamp-$SafeProjectName-$BackupId"
        $PartialPath = Join-Path $Root ".partial-$BackupId"
        $PublishedPath = Join-Path $Root $FinalName
        if (
            (Test-Path -LiteralPath $PartialPath) -or
            (Test-Path -LiteralPath $PublishedPath)
        ) {
            throw "Backup staging or final path already exists."
        }
        $null = New-Item -ItemType Directory -Path $PartialPath
        Set-WindowsRestrictedAcl -Path $PartialPath -Directory
        foreach ($Directory in @("postgres", "volumes", "config", "config\nginx", "secrets")) {
            $null = New-Item -ItemType Directory -Path (
                Join-Path $PartialPath $Directory
            ) -Force
        }

        Stop-WindowsComposeServices `
            -ComposeBaseArguments $ComposeBaseArguments `
            -RunningServices $RunningServices `
            -RequestedServices @("gateway") `
            -StoppedServices $StoppedServices `
            -TimeoutSeconds $QuiesceTimeoutSeconds
        Stop-WindowsComposeServices `
            -ComposeBaseArguments $ComposeBaseArguments `
            -RunningServices $RunningServices `
            -RequestedServices @("beat", "api") `
            -StoppedServices $StoppedServices `
            -TimeoutSeconds $QuiesceTimeoutSeconds
        Stop-WindowsComposeServices `
            -ComposeBaseArguments $ComposeBaseArguments `
            -RunningServices $RunningServices `
            -RequestedServices @(
                "worker-audit",
                "worker-permission",
                "worker-preview",
                "worker-search",
                "worker-maintenance"
            ) `
            -StoppedServices $StoppedServices `
            -TimeoutSeconds $QuiesceTimeoutSeconds
        Stop-WindowsComposeServices `
            -ComposeBaseArguments $ComposeBaseArguments `
            -RunningServices $RunningServices `
            -RequestedServices @("minio", "redis", "opensearch") `
            -StoppedServices $StoppedServices `
            -TimeoutSeconds $QuiesceTimeoutSeconds

        $QuiescedAt = [System.DateTime]::UtcNow.ToString("o")
        $PostgresUser = Get-WindowsModelEnvironmentValue `
            -ComposeModel $ComposeModel `
            -ServiceName "postgres" `
            -Name "POSTGRES_USER"
        $PostgresDatabase = Get-WindowsModelEnvironmentValue `
            -ComposeModel $ComposeModel `
            -ServiceName "postgres" `
            -Name "POSTGRES_DB"
        $PostgresPassword = Get-WindowsModelEnvironmentValue `
            -ComposeModel $ComposeModel `
            -ServiceName "postgres" `
            -Name "POSTGRES_PASSWORD"
        $PostgresVersion = Invoke-WindowsPostgresQuery `
            -ComposeBaseArguments $ComposeBaseArguments `
            -User $PostgresUser `
            -Database $PostgresDatabase `
            -Sql "SHOW server_version"
        $AlembicRevision = Invoke-WindowsPostgresQuery `
            -ComposeBaseArguments $ComposeBaseArguments `
            -User $PostgresUser `
            -Database $PostgresDatabase `
            -Sql "SELECT version_num FROM alembic_version"
        $WalLsn = Invoke-WindowsPostgresQuery `
            -ComposeBaseArguments $ComposeBaseArguments `
            -User $PostgresUser `
            -Database $PostgresDatabase `
            -Sql "SELECT pg_current_wal_lsn()"

        $PostgresImage = [string]$PostgresImageRecord.reference
        $PostgresImageId = [string]$PostgresImageRecord.id
        $BackendNetwork = Get-WindowsModelBackendNetwork `
            -ComposeModel $ComposeModel
        $HelperSettings = Get-WindowsBackupHelperSettings
        Write-Host (
            "[backup] creating PostgreSQL dump ({0:N1}s elapsed)" -f
            $BackupStopwatch.Elapsed.TotalSeconds
        )
        $null = Invoke-WindowsBackupHelperContainer -Arguments @(
            "--network", $BackendNetwork,
            "--entrypoint", "sh",
            "--mount", "type=bind,source=$PartialPath,target=/backup",
            "-e", "PGHOST=postgres",
            "-e", "PGUSER=$PostgresUser",
            "-e", "PGDATABASE=$PostgresDatabase",
            "-e", "PGPASSWORD=$PostgresPassword",
            $PostgresImageId,
            "-ec",
            (
                "pg_dump --format=custom " +
                "--compress=$($HelperSettings.pg_dump_compression_level) " +
                "--no-owner --no-acl " +
                "--file=/backup/postgres/postgres.dump; " +
                "pg_restore --list /backup/postgres/postgres.dump >/dev/null"
            )
        )

        foreach ($LogicalName in @(
            "minio-data",
            "redis-data",
            "opensearch-data",
            "tls-certificates"
        )) {
            Write-Host (
                "[backup] archiving {0} ({1:N1}s elapsed)" -f
                $LogicalName,
                $BackupStopwatch.Elapsed.TotalSeconds
            )
            Invoke-WindowsVolumeArchive `
                -ArchiveToolImage $PostgresImageId `
                -VolumeName $VolumeMap[$LogicalName] `
                -BackupDirectory $PartialPath `
                -ArchiveRelativePath "volumes/$LogicalName.tar.gz" `
                -SkipImmediateVerification
        }

        Copy-Item `
            -LiteralPath $ComposeFile `
            -Destination (Join-Path $PartialPath "config\compose.windows.yml")
        foreach ($Template in Get-ChildItem `
            -LiteralPath (Join-Path $RepoRoot "deploy\windows\nginx") `
            -File `
            -Filter "*.template") {
            Copy-Item `
                -LiteralPath $Template.FullName `
                -Destination (Join-Path $PartialPath "config\nginx\$($Template.Name)")
        }

        $EnvironmentIncluded = -not $SkipEnvironmentBackup
        if ($EnvironmentIncluded) {
            $ProtectedEnvironment = Protect-CmsMessage `
                -To $Certificate `
                -Path $EnvFile
            Write-WindowsUtf8File `
                -Path (Join-Path $PartialPath "secrets\environment.cms") `
                -Content ([string]$ProtectedEnvironment)
        }

        $Artifacts = @()
        foreach ($File in Get-ChildItem -LiteralPath $PartialPath -Recurse -File |
            Sort-Object FullName) {
            $RelativePath = Get-WindowsRelativeArtifactPath `
                -Root $PartialPath `
                -Path $File.FullName
            $Artifacts += [pscustomobject][ordered]@{
                path = $RelativePath
                size_bytes = [int64]$File.Length
                sha256 = Get-WindowsSha256 -Path $File.FullName
            }
        }

        $VolumeRecords = @()
        foreach ($LogicalName in @(
            "postgres-data",
            "redis-data",
            "minio-data",
            "opensearch-data",
            "tls-certificates"
        )) {
            $VolumeRecords += [pscustomobject][ordered]@{
                logical_name = $LogicalName
                physical_name = $VolumeMap[$LogicalName]
                backup_mode = if ($LogicalName -eq "postgres-data") {
                    "pg_dump"
                }
                else {
                    "stopped-volume-tar"
                }
            }
        }

        $Configuration = [ordered]@{
            s3_bucket = Get-WindowsModelEnvironmentValue `
                -ComposeModel $ComposeModel `
                -ServiceName "api" `
                -Name "DRIVE_S3_BUCKET"
            opensearch_index_name = Get-WindowsModelEnvironmentValue `
                -ComposeModel $ComposeModel `
                -ServiceName "api" `
                -Name "DRIVE_OPENSEARCH_INDEX_NAME"
            tls_certificate_name = Get-WindowsModelEnvironmentValue `
                -ComposeModel $ComposeModel `
                -ServiceName "gateway" `
                -Name "DRIVE_TLS_CERT_NAME"
        }
        $Manifest = [ordered]@{
            format_version = 1
            backup_id = $BackupId
            created_at_utc = [System.DateTime]::UtcNow.ToString("o")
            quiesced_at_utc = $QuiescedAt
            source_project = $ProjectName
            project_version = Get-WindowsProjectVersion -RepoRoot $RepoRoot
            git_commit = Get-WindowsGitCommit -RepoRoot $RepoRoot
            compose_sha256 = Get-WindowsSha256 -Path $ComposeFile
            archive_tool_image = $PostgresImage
            archive_tool_image_id = $PostgresImageId
            running_services = @($RunningServices)
            service_states = @($OriginalServiceStates)
            database = [ordered]@{
                name = $PostgresDatabase
                user = $PostgresUser
                server_version = $PostgresVersion
                alembic_revision = $AlembicRevision
                wal_lsn = $WalLsn
                dump_format = "custom"
            }
            environment = [ordered]@{
                included = $EnvironmentIncluded
                protection = if ($EnvironmentIncluded) {
                    "windows-cms"
                }
                else {
                    "skipped"
                }
                certificate_thumbprint = if ($EnvironmentIncluded) {
                    $ConfigEncryptionCertificateThumbprint.ToUpperInvariant()
                }
                else {
                    ""
                }
            }
            configuration = $Configuration
            volumes = $VolumeRecords
            images = $ImageRecords
            artifacts = $Artifacts
        }
        $ManifestPath = Join-Path $PartialPath "manifest.json"
        $ManifestJson = $Manifest | ConvertTo-Json -Depth 12
        Write-WindowsUtf8File -Path $ManifestPath -Content ($ManifestJson + "`n")
        $ManifestHash = Get-WindowsSha256 -Path $ManifestPath
        Write-WindowsUtf8File `
            -Path (Join-Path $PartialPath "manifest.sha256") `
            -Content "$ManifestHash  manifest.json`n"
        Assert-WindowsRestrictedAcl -Path $PartialPath
        Assert-WindowsNoReparsePoint `
            -Path $PartialPath `
            -Label "Backup staging"

        Write-Host (
            "[backup] running publish-time verification ({0:N1}s elapsed)" -f
            $BackupStopwatch.Elapsed.TotalSeconds
        )
        $null = Test-WindowsBackup `
            -RepoRoot $RepoRoot `
            -ComposeFile $ComposeFile `
            -EnvFile $EnvFile `
            -ComposeBaseArguments $ComposeBaseArguments `
            -BackupPath $PartialPath

        [System.IO.Directory]::Move($PartialPath, $PublishedPath)
        Assert-WindowsRestrictedAcl -Path $PublishedPath
        Assert-WindowsNoReparsePoint `
            -Path $PublishedPath `
            -Label "Published backup"
        $PartialPath = $null
    }
    catch {
        $OriginalFailure = $_
    }
    finally {
        try {
            Restore-WindowsSourceServiceState `
                -ComposeBaseArguments $ComposeBaseArguments `
                -OriginalServiceStates $OriginalServiceStates
        }
        catch {
            $RecoveryErrors += $_.Exception.Message
        }

        if (
            -not [string]::IsNullOrWhiteSpace($PartialPath) -and
            (Test-Path -LiteralPath $PartialPath)
        ) {
            try {
                if (-not (Test-WindowsPathWithin -Parent $Root -Candidate $PartialPath)) {
                    throw "Refusing to remove backup staging outside the backup root."
                }
                Assert-WindowsNoReparsePoint `
                    -Path $PartialPath `
                    -Label "Backup staging cleanup path"
                Remove-Item -LiteralPath $PartialPath -Recurse -Force
            }
            catch {
                $RecoveryErrors += "staging cleanup failed: $($_.Exception.Message)"
            }
        }
        if ($VolumeMutexes.Count -gt 0) {
            try {
                Exit-WindowsDeploymentMutexSet -Mutexes $VolumeMutexes
            }
            catch {
                $RecoveryErrors += "volume mutex release failed: $($_.Exception.Message)"
            }
        }
        try {
            Exit-WindowsDeploymentMutex -Mutex $Mutex
        }
        catch {
            $RecoveryErrors += "project mutex release failed: $($_.Exception.Message)"
        }
    }

    if ($null -ne $OriginalFailure) {
        if ($RecoveryErrors.Count -gt 0) {
            throw "Backup failed; recovery also failed: $($RecoveryErrors -join '; '). Original error: $($OriginalFailure.Exception.Message)"
        }
        throw $OriginalFailure
    }
    if ($RecoveryErrors.Count -gt 0) {
        throw "Backup was published, but source service recovery failed: $($RecoveryErrors -join '; '). Backup: $PublishedPath"
    }
    Write-Host (
        "[backup:done] {0} ({1:N1}s)" -f
        $PublishedPath,
        $BackupStopwatch.Elapsed.TotalSeconds
    )
    Write-Output $PublishedPath
}

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

        [string]$RestoreEnvironmentOutput,

        [switch]$ForceRestore,

        [switch]$NoStartAfterRestore
    )

    $Root = [System.IO.Path]::GetFullPath($BackupPath)
    $Manifest = Test-WindowsBackup `
        -RepoRoot $RepoRoot `
        -ComposeFile $ComposeFile `
        -EnvFile $EnvFile `
        -ComposeBaseArguments $ComposeBaseArguments `
        -BackupPath $Root

    $ComposeModel = Get-WindowsComposeModel `
        -ComposeBaseArguments $ComposeBaseArguments
    $TargetProject = [string]$ComposeModel.name
    if ($TargetProject -eq [string]$Manifest.source_project) {
        throw "Restore requires a different Compose project from the backup source."
    }

    $VolumeMap = Get-WindowsBackupVolumeMap -ComposeModel $ComposeModel
    $SourceVolumeMap = Get-WindowsManifestVolumeMap -Manifest $Manifest
    $SourcePhysicalNames = New-Object "System.Collections.Generic.HashSet[string]" (
        [System.StringComparer]::OrdinalIgnoreCase
    )
    foreach ($VolumeRecord in $SourceVolumeMap.Values) {
        $null = $SourcePhysicalNames.Add([string]$VolumeRecord.physical_name)
    }
    foreach ($PhysicalName in $VolumeMap.Values) {
        if ($SourcePhysicalNames.Contains([string]$PhysicalName)) {
            throw "Restore target volume overlaps a source physical volume: $PhysicalName"
        }
    }
    $ArchiveToolImage = [string]$Manifest.archive_tool_image_id
    $ExpectedImageServices = @(
        Get-WindowsComposeDefaultServiceNames -ComposeModel $ComposeModel
    )
    $SourceImageMap = Get-WindowsManifestImageMap `
        -Manifest $Manifest `
        -ExpectedServices $ExpectedImageServices
    foreach ($ServiceName in $ExpectedImageServices) {
        $TargetReference = Get-WindowsModelServiceImage `
            -ComposeModel $ComposeModel `
            -ServiceName $ServiceName
        $TargetImageInfo = Get-WindowsImageInfo -Image $TargetReference
        if (
            [string]$SourceImageMap[$ServiceName].reference -ne $TargetReference -or
            [string]$SourceImageMap[$ServiceName].id -ne
            [string]$TargetImageInfo.id
        ) {
            throw "Restore image reference or ID mismatch for $ServiceName."
        }
    }

    $OutputPath = $null
    $DecryptedEnvironment = $null
    if (-not [string]::IsNullOrWhiteSpace($RestoreEnvironmentOutput)) {
        if (-not [bool]$Manifest.environment.included) {
            throw "Backup does not contain an encrypted environment file."
        }
        $EnvironmentArtifact = Get-WindowsManifestArtifact `
            -Manifest $Manifest `
            -RelativePath "secrets/environment.cms"
        $EnvironmentPath = Resolve-WindowsBackupArtifactPath `
            -BackupRoot $Root `
            -RelativePath ([string]$EnvironmentArtifact.path)
        if (-not [System.IO.Path]::IsPathRooted($RestoreEnvironmentOutput)) {
            throw "RestoreEnvironmentOutput must be an absolute path."
        }
        $OutputPath = [System.IO.Path]::GetFullPath($RestoreEnvironmentOutput)
        if (
            Test-WindowsPathWithin -Parent $RepoRoot -Candidate $OutputPath
        ) {
            throw "RestoreEnvironmentOutput must be outside the repository."
        }
        if (Test-WindowsPathWithin -Parent $Root -Candidate $OutputPath) {
            throw "RestoreEnvironmentOutput must be outside the backup directory."
        }
        $PathRoot = [System.IO.Path]::GetPathRoot($OutputPath)
        if ($OutputPath.Substring($PathRoot.Length).Contains(":")) {
            throw "RestoreEnvironmentOutput must not use an alternate data stream."
        }
        if (Test-Path -LiteralPath $OutputPath) {
            throw "RestoreEnvironmentOutput already exists: $OutputPath"
        }
        $OutputParent = [System.IO.Path]::GetDirectoryName($OutputPath)
        if (
            [string]::IsNullOrWhiteSpace($OutputParent) -or
            -not (Test-Path -LiteralPath $OutputParent -PathType Container)
        ) {
            throw "RestoreEnvironmentOutput parent directory must already exist."
        }
        Assert-WindowsNoReparsePoint `
            -Path $OutputParent `
            -Label "RestoreEnvironmentOutput"
        $DecryptedEnvironment = [string](
            Unprotect-CmsMessage -Path $EnvironmentPath
        )
    }

    $Mutex = Enter-WindowsDeploymentMutex -ProjectName $TargetProject
    $VolumeMutexes = @()
    try {
        $VolumeMutexes = @(
            Enter-WindowsDeploymentMutexSet -ResourceNames @(
                $VolumeMap.Values |
                    ForEach-Object { "volume:$([string]$_)" }
            )
        )
    }
    catch {
        Exit-WindowsDeploymentMutex -Mutex $Mutex
        throw
    }
    $LogicalVolumeNames = @(
        "postgres-data",
        "redis-data",
        "minio-data",
        "opensearch-data",
        "tls-certificates"
    )
    $RestoreMutationStarted = $false
    $RestoreFailure = $null
    $RestoreRecoveryErrors = New-Object "System.Collections.Generic.List[string]"
    $VolumeStates = @{}
    $CreatedVolumes = New-Object "System.Collections.Generic.List[string]"
    $TouchedLogicalNames = New-Object "System.Collections.Generic.HashSet[string]" (
        [System.StringComparer]::OrdinalIgnoreCase
    )
    $RollbackRoot = $null
    $RollbackArtifacts = @{}
    $PreserveRollback = $false
    $EnvironmentOutputPublished = $false
    $RestoreCommitted = $false
    try {
        $Containers = @(
            Get-WindowsComposeContainers `
                -ComposeBaseArguments $ComposeBaseArguments
        )
        foreach ($Container in $Containers) {
            if ([string]$Container.State -ne "exited") {
                throw (
                    "Target Compose project has an active or transitional " +
                    "container: $($Container.Service) ($($Container.State))"
                )
            }
        }
        if ($Containers.Count -gt 0 -and -not $ForceRestore) {
            throw "Target Compose project already has containers; use -ForceRestore after stopping it."
        }
        if ($Containers.Count -gt 0) {
            $RestoreMutationStarted = $true
            $null = Invoke-WindowsDocker -Arguments @(
                $ComposeBaseArguments +
                @("down", "--remove-orphans", "--timeout", "60")
            )
            $RemainingContainers = @(
                Get-WindowsComposeContainers `
                    -ComposeBaseArguments $ComposeBaseArguments
            )
            if ($RemainingContainers.Count -gt 0) {
                throw "Target Compose containers remain after down."
            }
        }

        foreach ($LogicalName in $LogicalVolumeNames) {
            $PhysicalName = [string]$VolumeMap[$LogicalName]
            $Inspection = Get-WindowsVolumeInspection -VolumeName $PhysicalName
            $Exists = $null -ne $Inspection
            $Empty = $true
            if ($Exists) {
                Assert-WindowsVolumeLabels `
                    -Inspection $Inspection `
                    -ProjectName $TargetProject `
                    -LogicalName $LogicalName
                $AttachedContainers = @(
                    Get-WindowsVolumeAttachedContainerIds `
                        -VolumeName $PhysicalName
                )
                if ($AttachedContainers.Count -gt 0) {
                    throw "Target volume is attached to a container: $PhysicalName"
                }
                $Empty = Test-WindowsVolumeEmpty `
                    -ArchiveToolImage $ArchiveToolImage `
                    -VolumeName $PhysicalName
            }
            if (-not $Empty -and -not $ForceRestore) {
                throw "Target volume is not empty: $PhysicalName"
            }
            $VolumeStates[$LogicalName] = [pscustomobject][ordered]@{
                exists = $Exists
                empty = $Empty
                physical_name = $PhysicalName
            }
        }

        $NonemptyLogicalNames = @(
            $LogicalVolumeNames |
                Where-Object {
                    [bool]$VolumeStates[$_].exists -and
                    -not [bool]$VolumeStates[$_].empty
                }
        )
        if ($ForceRestore -and $NonemptyLogicalNames.Count -gt 0) {
            $RollbackRoot = Join-Path (
                [System.IO.Path]::GetTempPath()
            ) (
                "enterprise-drive-restore-rollback-" +
                [Guid]::NewGuid().ToString("N")
            )
            $null = New-Item -ItemType Directory -Path $RollbackRoot
            Set-WindowsRestrictedAcl -Path $RollbackRoot -Directory
            $null = New-Item -ItemType Directory -Path (
                Join-Path $RollbackRoot "volumes"
            )
            foreach ($LogicalName in $NonemptyLogicalNames) {
                $RelativePath = "volumes/$LogicalName.tar.gz"
                Invoke-WindowsVolumeArchive `
                    -ArchiveToolImage $ArchiveToolImage `
                    -VolumeName $VolumeMap[$LogicalName] `
                    -BackupDirectory $RollbackRoot `
                    -ArchiveRelativePath $RelativePath
                $RollbackArtifacts[$LogicalName] = $RelativePath
            }
            Assert-WindowsRestrictedAcl -Path $RollbackRoot
            Assert-WindowsNoReparsePoint `
                -Path $RollbackRoot `
                -Label "Restore rollback staging"
        }

        foreach ($LogicalName in $LogicalVolumeNames) {
            $VolumeState = $VolumeStates[$LogicalName]
            $PhysicalName = [string]$VolumeState.physical_name
            if (-not [bool]$VolumeState.exists) {
                $RestoreMutationStarted = $true
                $null = Invoke-WindowsDocker -Arguments @(
                    "volume", "create",
                    "--label", "com.docker.compose.project=$TargetProject",
                    "--label", "com.docker.compose.volume=$LogicalName",
                    $PhysicalName
                )
                $CreatedVolumes.Add($PhysicalName)
                $null = $TouchedLogicalNames.Add($LogicalName)
            }
            if (-not [bool]$VolumeState.empty) {
                $RestoreMutationStarted = $true
                $null = $TouchedLogicalNames.Add($LogicalName)
                Clear-WindowsVolume `
                    -ArchiveToolImage $ArchiveToolImage `
                    -VolumeName $PhysicalName
                if (
                    -not (
                        Test-WindowsVolumeEmpty `
                            -ArchiveToolImage $ArchiveToolImage `
                            -VolumeName $PhysicalName
                    )
                ) {
                    throw "Target volume did not become empty: $PhysicalName"
                }
            }
        }

        foreach ($LogicalName in @(
            "minio-data",
            "redis-data",
            "opensearch-data",
            "tls-certificates"
        )) {
            $RestoreMutationStarted = $true
            $null = $TouchedLogicalNames.Add($LogicalName)
            Restore-WindowsVolumeArchive `
                -ArchiveToolImage $ArchiveToolImage `
                -VolumeName $VolumeMap[$LogicalName] `
                -BackupDirectory $Root `
                -ArchiveRelativePath "volumes/$LogicalName.tar.gz"
        }

        $RestoreMutationStarted = $true
        $null = $TouchedLogicalNames.Add("postgres-data")
        $null = Invoke-WindowsDocker -Arguments @(
            $ComposeBaseArguments +
            @(
                "up",
                "--detach",
                "--no-deps",
                "--no-build",
                "--pull", "never",
                "postgres"
            )
        )
        Wait-WindowsComposeServices `
            -ComposeBaseArguments $ComposeBaseArguments `
            -Services @("postgres") `
            -TimeoutSeconds 180

        $PostgresUser = Get-WindowsModelEnvironmentValue `
            -ComposeModel $ComposeModel `
            -ServiceName "postgres" `
            -Name "POSTGRES_USER"
        $PostgresDatabase = Get-WindowsModelEnvironmentValue `
            -ComposeModel $ComposeModel `
            -ServiceName "postgres" `
            -Name "POSTGRES_DB"
        $PostgresPassword = Get-WindowsModelEnvironmentValue `
            -ComposeModel $ComposeModel `
            -ServiceName "postgres" `
            -Name "POSTGRES_PASSWORD"
        $BackendNetwork = Get-WindowsModelBackendNetwork `
            -ComposeModel $ComposeModel
        $null = Invoke-WindowsBackupHelperContainer -Arguments @(
            "--network", $BackendNetwork,
            "--entrypoint", "sh",
            "--mount", "type=bind,source=$Root,target=/backup,readonly",
            "-e", "PGHOST=postgres",
            "-e", "PGUSER=$PostgresUser",
            "-e", "PGDATABASE=$PostgresDatabase",
            "-e", "PGPASSWORD=$PostgresPassword",
            $ArchiveToolImage,
            "-ec",
            (
                'pg_restore --exit-on-error --clean --if-exists ' +
                '--single-transaction --no-owner --no-acl ' +
                '--dbname="$PGDATABASE" /backup/postgres/postgres.dump'
            )
        )
        $RestoredAlembicRevision = Invoke-WindowsPostgresQuery `
            -ComposeBaseArguments $ComposeBaseArguments `
            -User $PostgresUser `
            -Database $PostgresDatabase `
            -Sql "SELECT version_num FROM alembic_version"
        if (
            $RestoredAlembicRevision -ne
            [string]$Manifest.database.alembic_revision
        ) {
            throw "Restored Alembic revision does not match the backup manifest."
        }

        if ($NoStartAfterRestore) {
            $null = Invoke-WindowsDocker -Arguments @(
                $ComposeBaseArguments +
                @("stop", "--timeout", "60", "postgres")
            )
        }
        else {
            $null = Invoke-WindowsDocker -Arguments @(
                $ComposeBaseArguments +
                @(
                    "up",
                    "--detach",
                    "--remove-orphans",
                    "--no-build",
                    "--pull", "never",
                    "--wait",
                    "--wait-timeout", "360"
                )
            )
            $PostStartAlembicRevision = Invoke-WindowsPostgresQuery `
                -ComposeBaseArguments $ComposeBaseArguments `
                -User $PostgresUser `
                -Database $PostgresDatabase `
                -Sql "SELECT version_num FROM alembic_version"
            if (
                $PostStartAlembicRevision -ne
                [string]$Manifest.database.alembic_revision
            ) {
                throw "Alembic revision changed after full Compose startup."
            }
            $PostStartImageRecords = @(
                Get-WindowsComposeImageRecords `
                    -ComposeModel $ComposeModel `
                    -Containers @(
                        Get-WindowsComposeContainers `
                            -ComposeBaseArguments $ComposeBaseArguments
                    )
            )
            foreach ($ImageRecord in $PostStartImageRecords) {
                if (
                    [string]$SourceImageMap[[string]$ImageRecord.service].id -ne
                    [string]$ImageRecord.id
                ) {
                    throw "Container image changed after restore: $($ImageRecord.service)"
                }
            }
        }

        if ($null -ne $OutputPath) {
            Write-WindowsRestrictedUtf8File `
                -Path $OutputPath `
                -Content $DecryptedEnvironment
            $EnvironmentOutputPublished = $true
        }
        $RestoreCommitted = $true
    }
    catch {
        $RestoreFailure = $_
        if ($RestoreMutationStarted) {
            try {
                $null = Invoke-WindowsDocker -Arguments @(
                    $ComposeBaseArguments +
                    @("down", "--remove-orphans", "--timeout", "60")
                )
            }
            catch {
                $RestoreRecoveryErrors.Add(
                    "compose down failed: $($_.Exception.Message)"
                )
            }
            try {
                $RemainingContainers = @(
                    Get-WindowsComposeContainers `
                        -ComposeBaseArguments $ComposeBaseArguments
                )
                if ($RemainingContainers.Count -gt 0) {
                    $RestoreRecoveryErrors.Add(
                        "target Compose containers remain after failure isolation"
                    )
                }
            }
            catch {
                $RestoreRecoveryErrors.Add(
                    "container isolation check failed: $($_.Exception.Message)"
                )
            }

            foreach ($PhysicalName in @($CreatedVolumes)) {
                try {
                    $Inspection = Get-WindowsVolumeInspection `
                        -VolumeName $PhysicalName
                    if ($null -ne $Inspection) {
                        $AttachedContainers = @(
                            Get-WindowsVolumeAttachedContainerIds `
                                -VolumeName $PhysicalName
                        )
                        if ($AttachedContainers.Count -gt 0) {
                            throw "volume remains attached to a container"
                        }
                        $null = Invoke-WindowsDocker -Arguments @(
                            "volume",
                            "rm",
                            $PhysicalName
                        )
                    }
                }
                catch {
                    $RestoreRecoveryErrors.Add(
                        "created volume cleanup failed for '$PhysicalName': " +
                        $_.Exception.Message
                    )
                }
            }
            foreach ($LogicalName in @($TouchedLogicalNames)) {
                $PhysicalName = [string]$VolumeMap[$LogicalName]
                if ($CreatedVolumes.Contains($PhysicalName)) {
                    continue
                }
                try {
                    $Inspection = Get-WindowsVolumeInspection `
                        -VolumeName $PhysicalName
                    if ($null -eq $Inspection) {
                        continue
                    }
                    $AttachedContainers = @(
                        Get-WindowsVolumeAttachedContainerIds `
                            -VolumeName $PhysicalName
                    )
                    if ($AttachedContainers.Count -gt 0) {
                        throw "volume remains attached to a container"
                    }
                    Clear-WindowsVolume `
                        -ArchiveToolImage $ArchiveToolImage `
                        -VolumeName $PhysicalName
                    $OriginalVolumeState = $VolumeStates[$LogicalName]
                    if (-not [bool]$OriginalVolumeState.empty) {
                        if (
                            [string]::IsNullOrWhiteSpace($RollbackRoot) -or
                            -not $RollbackArtifacts.ContainsKey($LogicalName)
                        ) {
                            throw "rollback archive is missing"
                        }
                        Restore-WindowsVolumeArchive `
                            -ArchiveToolImage $ArchiveToolImage `
                            -VolumeName $PhysicalName `
                            -BackupDirectory $RollbackRoot `
                            -ArchiveRelativePath (
                                [string]$RollbackArtifacts[$LogicalName]
                            )
                        if (
                            Test-WindowsVolumeEmpty `
                                -ArchiveToolImage $ArchiveToolImage `
                                -VolumeName $PhysicalName
                        ) {
                            throw "rollback archive restored an empty volume"
                        }
                    }
                    elseif (
                        -not (
                            Test-WindowsVolumeEmpty `
                                -ArchiveToolImage $ArchiveToolImage `
                                -VolumeName $PhysicalName
                        )
                    ) {
                        throw "volume did not return to its original empty state"
                    }
                }
                catch {
                    if (-not [bool]$VolumeStates[$LogicalName].empty) {
                        $PreserveRollback = $true
                    }
                    $RestoreRecoveryErrors.Add(
                        "touched volume recovery failed for '$PhysicalName': " +
                        $_.Exception.Message
                    )
                }
            }
        }
        if ($EnvironmentOutputPublished -and -not $RestoreCommitted) {
            $RestoreRecoveryErrors.Add(
                "environment output was published before restore commit and " +
                "was preserved for manual inspection: $OutputPath"
            )
        }
        if (
            -not [string]::IsNullOrWhiteSpace($RollbackRoot) -and
            (Test-Path -LiteralPath $RollbackRoot -PathType Container)
        ) {
            if ($PreserveRollback) {
                $RestoreRecoveryErrors.Add(
                    "rollback data was preserved for manual recovery: $RollbackRoot"
                )
            }
            else {
                try {
                    Remove-WindowsRestoreRollbackRoot -Path $RollbackRoot
                    $RollbackRoot = $null
                }
                catch {
                    $RestoreRecoveryErrors.Add(
                        "rollback cleanup failed: $($_.Exception.Message). " +
                        "Rollback data: $RollbackRoot"
                    )
                }
            }
        }
    }
    finally {
        $DecryptedEnvironment = $null
        try {
            Exit-WindowsDeploymentMutexSet -Mutexes $VolumeMutexes
        }
        catch {
            $RestoreRecoveryErrors.Add(
                "volume mutex release failed: $($_.Exception.Message)"
            )
        }
        try {
            Exit-WindowsDeploymentMutex -Mutex $Mutex
        }
        catch {
            $RestoreRecoveryErrors.Add(
                "project mutex release failed: $($_.Exception.Message)"
            )
        }
    }

    if (
        $RestoreCommitted -and
        -not [string]::IsNullOrWhiteSpace($RollbackRoot) -and
        (Test-Path -LiteralPath $RollbackRoot -PathType Container)
    ) {
        try {
            Remove-WindowsRestoreRollbackRoot -Path $RollbackRoot
            $RollbackRoot = $null
        }
        catch {
            $RestoreRecoveryErrors.Add(
                "rollback cleanup failed after restore commit: " +
                "$($_.Exception.Message). Rollback data: $RollbackRoot"
            )
        }
    }

    if ($null -ne $RestoreFailure) {
        if ($RestoreRecoveryErrors.Count -gt 0) {
            throw "Restore failed; target isolation also failed: $($RestoreRecoveryErrors -join '; '). Original error: $($RestoreFailure.Exception.Message)"
        }
        throw $RestoreFailure
    }
    if ($RestoreRecoveryErrors.Count -gt 0) {
        throw "Restore completed, but maintenance cleanup failed: $($RestoreRecoveryErrors -join '; ')"
    }
    Write-Output "Restore completed for project '$TargetProject' from '$Root'."
}
