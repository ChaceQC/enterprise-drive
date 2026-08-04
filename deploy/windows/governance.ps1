function Get-WindowsGovernanceJson {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $StrictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)
    $Text = [System.IO.File]::ReadAllText($Path, $StrictUtf8)
    return $Text | ConvertFrom-Json -ErrorAction Stop
}

function Get-WindowsBackupRecord {
    param(
        [Parameter(Mandatory = $true)]
        [string]$BackupPath
    )

    $Path = [System.IO.Path]::GetFullPath($BackupPath)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "Backup path does not exist: $Path"
    }
    Assert-WindowsNoReparsePoint -Path $Path -Label "Backup retention candidate"
    Assert-WindowsRestrictedAcl -Path $Path

    $Name = [System.IO.Path]::GetFileName($Path)
    if (
        $Name -notmatch (
            "^(?<timestamp>[0-9]{8}T[0-9]{6}Z)-" +
            "(?<project>[A-Za-z0-9._-]+)-" +
            "(?<backup_id>[0-9a-f]{32})$"
        )
    ) {
        throw "Backup directory name is not managed by this project: $Name"
    }
    $DirectoryBackupId = $Matches["backup_id"]

    $ManifestPath = Join-Path $Path "manifest.json"
    $ChecksumPath = Join-Path $Path "manifest.sha256"
    foreach ($RequiredPath in @($ManifestPath, $ChecksumPath)) {
        if (-not (Test-Path -LiteralPath $RequiredPath -PathType Leaf)) {
            throw "Managed backup is missing a required file: $RequiredPath"
        }
        Assert-WindowsNoReparsePoint -Path $RequiredPath -Label "Backup metadata"
    }

    $StrictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)
    $ChecksumText = [System.IO.File]::ReadAllText(
        $ChecksumPath,
        $StrictUtf8
    ).Trim()
    if ($ChecksumText -notmatch "^([0-9a-f]{64})  manifest[.]json$") {
        throw "Backup manifest checksum has an invalid format: $ChecksumPath"
    }
    $ExpectedChecksum = $Matches[1]
    $ActualChecksum = Get-WindowsSha256 -Path $ManifestPath
    if ($ActualChecksum -ne $ExpectedChecksum) {
        throw "Backup manifest checksum does not match: $ManifestPath"
    }

    $Manifest = Get-WindowsGovernanceJson -Path $ManifestPath
    if ([int]$Manifest.format_version -notin @(1, 2)) {
        throw "Unsupported backup manifest format: $($Manifest.format_version)"
    }
    Test-WindowsManifestSignature -BackupRoot $Path -Manifest $Manifest
    if ([string]$Manifest.backup_id -ne $DirectoryBackupId) {
        throw "Backup directory ID does not match manifest backup_id: $Path"
    }

    $CreatedAt = [System.DateTimeOffset]::MinValue
    if (
        -not [System.DateTimeOffset]::TryParse(
            [string]$Manifest.created_at_utc,
            [System.Globalization.CultureInfo]::InvariantCulture,
            [System.Globalization.DateTimeStyles]::AssumeUniversal,
            [ref]$CreatedAt
        )
    ) {
        throw "Backup manifest created_at_utc is invalid: $ManifestPath"
    }

    return [pscustomobject][ordered]@{
        path = $Path
        name = $Name
        backup_id = [string]$Manifest.backup_id
        source_project = [string]$Manifest.source_project
        created_at_utc = $CreatedAt.ToUniversalTime()
        project_version = [string]$Manifest.project_version
        git_commit = [string]$Manifest.git_commit
        alembic_revision = [string]$Manifest.database.alembic_revision
    }
}

function Get-WindowsBackupInventory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,

        [Parameter(Mandatory = $true)]
        [string]$BackupDirectory
    )

    $Root = Resolve-WindowsBackupRoot `
        -RepoRoot $RepoRoot `
        -BackupDirectory $BackupDirectory
    $Records = @()
    foreach (
        $Directory in @(
            Get-ChildItem -LiteralPath $Root -Directory -Force -ErrorAction Stop
        )
    ) {
        if ($Directory.Name.StartsWith(".partial-")) {
            continue
        }
        if (
            $Directory.Name -notmatch (
                "^[0-9]{8}T[0-9]{6}Z-" +
                "[A-Za-z0-9._-]+-[0-9a-f]{32}$"
            )
        ) {
            continue
        }
        $Records += Get-WindowsBackupRecord -BackupPath $Directory.FullName
    }
    return @($Records | Sort-Object -Property created_at_utc -Descending)
}

function Write-WindowsGovernanceRecord {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,

        [Parameter(Mandatory = $true)]
        [string]$Directory,

        [Parameter(Mandatory = $true)]
        [ValidatePattern("^[A-Za-z0-9._-]+$")]
        [string]$Prefix,

        [Parameter(Mandatory = $true)]
        [object]$Payload
    )

    $Root = Resolve-WindowsBackupRoot `
        -RepoRoot $RepoRoot `
        -BackupDirectory $Directory
    $Timestamp = [System.DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
    $Suffix = [Guid]::NewGuid().ToString("N")
    $Path = Join-Path $Root "$Prefix-$Timestamp-$Suffix.json"
    $Content = ($Payload | ConvertTo-Json -Depth 16) + "`n"
    Write-WindowsRestrictedUtf8File -Path $Path -Content $Content
    return $Path
}

function Invoke-WindowsBackupRetention {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,

        [Parameter(Mandatory = $true)]
        [string[]]$ComposeBaseArguments,

        [Parameter(Mandatory = $true)]
        [string]$BackupDirectory,

        [ValidateRange(1, 3650)]
        [int]$RetentionDays = 35,

        [ValidateRange(1, 1000)]
        [int]$RetentionCount = 8,

        [switch]$Apply
    )

    $Root = Resolve-WindowsBackupRoot `
        -RepoRoot $RepoRoot `
        -BackupDirectory $BackupDirectory
    $ProjectName = Get-WindowsComposeProjectName `
        -ComposeBaseArguments $ComposeBaseArguments
    $Mutex = Enter-WindowsDeploymentMutex -ProjectName $ProjectName
    try {
        $Records = @(
            Get-WindowsBackupInventory `
                -RepoRoot $RepoRoot `
                -BackupDirectory $Root |
                Where-Object { $_.source_project -eq $ProjectName }
        )
        $Cutoff = [System.DateTimeOffset]::UtcNow.AddDays(-$RetentionDays)
        $Retained = New-Object "System.Collections.Generic.List[object]"
        $Eligible = New-Object "System.Collections.Generic.List[object]"
        for ($Index = 0; $Index -lt $Records.Count; $Index++) {
            $Record = $Records[$Index]
            if (
                $Index -lt $RetentionCount -or
                $Record.created_at_utc -ge $Cutoff
            ) {
                $Retained.Add($Record)
            }
            else {
                $Eligible.Add($Record)
            }
        }

        $Removed = New-Object "System.Collections.Generic.List[string]"
        if ($Apply) {
            foreach ($Record in $Eligible) {
                $Candidate = [System.IO.Path]::GetFullPath(
                    [string]$Record.path
                )
                if (
                    $Candidate -eq $Root -or
                    -not (
                        Test-WindowsPathWithin `
                            -Parent $Root `
                            -Candidate $Candidate
                    )
                ) {
                    throw "Refusing to remove a retention candidate outside the backup root."
                }
                Assert-WindowsNoReparsePoint `
                    -Path $Candidate `
                    -Label "Backup retention deletion"
                Assert-WindowsRestrictedAcl -Path $Candidate
                Remove-Item -LiteralPath $Candidate -Recurse -Force
                if (Test-Path -LiteralPath $Candidate) {
                    throw "Backup retention did not remove: $Candidate"
                }
                $Removed.Add($Candidate)
            }
        }

        $RecordDirectory = Join-Path $Root ".governance"
        $Payload = [pscustomobject][ordered]@{
            action = "backup-retention"
            created_at_utc = [System.DateTime]::UtcNow.ToString("o")
            source_project = $ProjectName
            backup_root = $Root
            apply = [bool]$Apply
            retention_days = $RetentionDays
            retention_count = $RetentionCount
            scanned = $Records.Count
            retained = $Retained.Count
            eligible = $Eligible.Count
            removed = $Removed.Count
            eligible_paths = @($Eligible | ForEach-Object { $_.path })
            removed_paths = @($Removed)
        }
        $RecordPath = Write-WindowsGovernanceRecord `
            -RepoRoot $RepoRoot `
            -Directory $RecordDirectory `
            -Prefix "backup-retention" `
            -Payload $Payload
        $Payload | Add-Member `
            -NotePropertyName record_path `
            -NotePropertyValue $RecordPath
        return $Payload
    }
    finally {
        Exit-WindowsDeploymentMutex -Mutex $Mutex
    }
}

function Invoke-WindowsRestoreDrill {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,

        [Parameter(Mandatory = $true)]
        [string]$ComposeFile,

        [Parameter(Mandatory = $true)]
        [string]$EnvFile,

        [Parameter(Mandatory = $true)]
        [string[]]$ComposeBaseArguments,

        [string]$BackupPath,

        [string]$BackupDirectory,

        [Parameter(Mandatory = $true)]
        [string]$RecordDirectory
    )

    if (
        [string]::IsNullOrWhiteSpace($BackupPath) -eq
        [string]::IsNullOrWhiteSpace($BackupDirectory)
    ) {
        throw "Restore drill requires exactly one of BackupPath or BackupDirectory."
    }

    $SourceProject = Get-WindowsComposeProjectName `
        -ComposeBaseArguments $ComposeBaseArguments
    $SelectedRecord = $null
    if (-not [string]::IsNullOrWhiteSpace($BackupPath)) {
        $SelectedRecord = Get-WindowsBackupRecord -BackupPath $BackupPath
    }
    else {
        $Inventory = @(
            Get-WindowsBackupInventory `
                -RepoRoot $RepoRoot `
                -BackupDirectory $BackupDirectory |
                Where-Object { $_.source_project -eq $SourceProject }
        )
        if ($Inventory.Count -eq 0) {
            throw "No managed backup exists for project '$SourceProject'."
        }
        $SelectedRecord = $Inventory[0]
    }

    $RecordRoot = Resolve-WindowsBackupRoot `
        -RepoRoot $RepoRoot `
        -BackupDirectory $RecordDirectory
    $StartedAt = [System.DateTimeOffset]::UtcNow
    $TargetProject = (
        "enterprise-drive-restore-drill-" +
        $StartedAt.ToString("yyyyMMddHHmmss") +
        "-" +
        [Guid]::NewGuid().ToString("N").Substring(0, 8)
    )
    $OriginalProject = [System.Environment]::GetEnvironmentVariable(
        "COMPOSE_PROJECT_NAME",
        [System.EnvironmentVariableTarget]::Process
    )
    $Failure = $null
    $CleanupFailure = $null
    $RestoreOutput = @()
    try {
        [System.Environment]::SetEnvironmentVariable(
            "COMPOSE_PROJECT_NAME",
            $TargetProject,
            [System.EnvironmentVariableTarget]::Process
        )
        $RestoreOutput = @(
            Invoke-WindowsRestore `
                -RepoRoot $RepoRoot `
                -ComposeFile $ComposeFile `
                -EnvFile $EnvFile `
                -ComposeBaseArguments $ComposeBaseArguments `
                -BackupPath ([string]$SelectedRecord.path) `
                -NoStartAfterRestore
        )
    }
    catch {
        $Failure = $_
    }
    finally {
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
            $RemainingContainers = @(
                Invoke-WindowsDocker -Arguments @(
                    "ps",
                    "--all",
                    "--quiet",
                    "--filter",
                    "label=com.docker.compose.project=$TargetProject"
                )
            )
            $RemainingVolumes = @(
                Invoke-WindowsDocker -Arguments @(
                    "volume",
                    "ls",
                    "--quiet",
                    "--filter",
                    "label=com.docker.compose.project=$TargetProject"
                )
            )
            if (
                $RemainingContainers.Count -gt 0 -or
                $RemainingVolumes.Count -gt 0
            ) {
                throw "Restore drill cleanup left target containers or volumes."
            }
        }
        catch {
            $CleanupFailure = $_
        }
        [System.Environment]::SetEnvironmentVariable(
            "COMPOSE_PROJECT_NAME",
            $OriginalProject,
            [System.EnvironmentVariableTarget]::Process
        )
    }

    $CompletedAt = [System.DateTimeOffset]::UtcNow
    $Status = if ($null -eq $Failure -and $null -eq $CleanupFailure) {
        "succeeded"
    }
    else {
        "failed"
    }
    $Payload = [pscustomobject][ordered]@{
        action = "restore-drill"
        drill_id = [Guid]::NewGuid().ToString("N")
        status = $Status
        started_at_utc = $StartedAt.ToString("o")
        completed_at_utc = $CompletedAt.ToString("o")
        duration_seconds = [Math]::Round(
            ($CompletedAt - $StartedAt).TotalSeconds,
            3
        )
        source_project = [string]$SelectedRecord.source_project
        target_project = $TargetProject
        backup_path = [string]$SelectedRecord.path
        backup_id = [string]$SelectedRecord.backup_id
        project_version = [string]$SelectedRecord.project_version
        git_commit = [string]$SelectedRecord.git_commit
        alembic_revision = [string]$SelectedRecord.alembic_revision
        mode = "isolated-data-restore"
        target_cleanup = if ($null -eq $CleanupFailure) {
            "succeeded"
        }
        else {
            "failed"
        }
        error = if ($null -ne $Failure) {
            "$($Failure.Exception.GetType().Name): $($Failure.Exception.Message)"
        }
        elseif ($null -ne $CleanupFailure) {
            "$($CleanupFailure.Exception.GetType().Name): $($CleanupFailure.Exception.Message)"
        }
        else {
            ""
        }
        restore_output = @($RestoreOutput | ForEach-Object { [string]$_ })
    }
    $RecordPath = Write-WindowsGovernanceRecord `
        -RepoRoot $RepoRoot `
        -Directory $RecordRoot `
        -Prefix "restore-drill" `
        -Payload $Payload
    $Payload | Add-Member `
        -NotePropertyName record_path `
        -NotePropertyValue $RecordPath

    if ($null -ne $Failure) {
        throw (
            "Restore drill failed; record: $RecordPath. " +
            $Failure.Exception.Message
        )
    }
    if ($null -ne $CleanupFailure) {
        throw (
            "Restore drill cleanup failed; record: $RecordPath. " +
            $CleanupFailure.Exception.Message
        )
    }
    return $Payload
}

function Register-WindowsGovernanceTask {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TaskName,

        [Parameter(Mandatory = $true)]
        [string]$Description,

        [Parameter(Mandatory = $true)]
        [string]$Arguments,

        [Parameter(Mandatory = $true)]
        [object]$Trigger,

        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    Import-Module ScheduledTasks -ErrorAction Stop
    $PowerShellExecutable = (Get-Process -Id $PID).Path
    $ScheduledAction = New-ScheduledTaskAction `
        -Execute $PowerShellExecutable `
        -Argument $Arguments `
        -WorkingDirectory $RepoRoot
    $Settings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -WakeToRun `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Hours 12)
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $ScheduledAction `
        -Trigger $Trigger `
        -Settings $Settings `
        -Description $Description `
        -Force
}

function Register-WindowsBackupRetentionTask {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,

        [Parameter(Mandatory = $true)]
        [string]$ManageScript,

        [Parameter(Mandatory = $true)]
        [string]$EnvFile,

        [Parameter(Mandatory = $true)]
        [string]$BackupDirectory,

        [ValidateRange(1, 3650)]
        [int]$RetentionDays = 35,

        [ValidateRange(1, 1000)]
        [int]$RetentionCount = 8,

        [Parameter(Mandatory = $true)]
        [string]$TaskName,

        [Parameter(Mandatory = $true)]
        [string]$At
    )

    $TriggerTime = [System.DateTime]::Today.Add(
        [System.TimeSpan]::ParseExact(
            $At,
            "hh\:mm",
            [System.Globalization.CultureInfo]::InvariantCulture
        )
    )
    $Arguments = @(
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$ManageScript`"",
        "backup-retention",
        "-EnvFile", "`"$EnvFile`"",
        "-BackupDirectory", "`"$BackupDirectory`"",
        "-RetentionDays", $RetentionDays.ToString(
            [System.Globalization.CultureInfo]::InvariantCulture
        ),
        "-RetentionCount", $RetentionCount.ToString(
            [System.Globalization.CultureInfo]::InvariantCulture
        ),
        "-ApplyRetention"
    ) -join " "
    Register-WindowsGovernanceTask `
        -TaskName $TaskName `
        -Description "Enterprise Drive backup retention rotation" `
        -Arguments $Arguments `
        -Trigger (New-ScheduledTaskTrigger -Daily -At $TriggerTime) `
        -RepoRoot $RepoRoot
}

function Register-WindowsRestoreDrillTask {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,

        [Parameter(Mandatory = $true)]
        [string]$ManageScript,

        [Parameter(Mandatory = $true)]
        [string]$EnvFile,

        [Parameter(Mandatory = $true)]
        [string]$BackupDirectory,

        [Parameter(Mandatory = $true)]
        [string]$RecordDirectory,

        [Parameter(Mandatory = $true)]
        [string]$TaskName,

        [Parameter(Mandatory = $true)]
        [string]$At,

        [Parameter(Mandatory = $true)]
        [string]$DayOfWeek
    )

    $TriggerTime = [System.DateTime]::Today.Add(
        [System.TimeSpan]::ParseExact(
            $At,
            "hh\:mm",
            [System.Globalization.CultureInfo]::InvariantCulture
        )
    )
    $Arguments = @(
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$ManageScript`"",
        "restore-drill",
        "-EnvFile", "`"$EnvFile`"",
        "-BackupDirectory", "`"$BackupDirectory`"",
        "-RestoreDrillDirectory", "`"$RecordDirectory`""
    ) -join " "
    Register-WindowsGovernanceTask `
        -TaskName $TaskName `
        -Description "Enterprise Drive isolated restore drill" `
        -Arguments $Arguments `
        -Trigger (
            New-ScheduledTaskTrigger `
                -Weekly `
                -WeeksInterval 1 `
                -DaysOfWeek $DayOfWeek `
                -At $TriggerTime
        ) `
        -RepoRoot $RepoRoot
}

function Unregister-WindowsGovernanceTask {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TaskName
    )

    Import-Module ScheduledTasks -ErrorAction Stop
    $Task = Get-ScheduledTask -TaskPath "\" |
        Where-Object { $_.TaskName -eq $TaskName }
    if ($null -ne $Task) {
        $Task | Unregister-ScheduledTask -Confirm:$false
    }
    else {
        Write-Output "Scheduled task does not exist: $TaskName"
    }
}

function Test-WindowsPublicIpAddress {
    param(
        [Parameter(Mandatory = $true)]
        [System.Net.IPAddress]$Address
    )

    if ([System.Net.IPAddress]::IsLoopback($Address)) {
        return $false
    }
    if ($Address.IsIPv4MappedToIPv6) {
        return Test-WindowsPublicIpAddress -Address $Address.MapToIPv4()
    }
    if (
        $Address.AddressFamily -eq
        [System.Net.Sockets.AddressFamily]::InterNetwork
    ) {
        $Bytes = $Address.GetAddressBytes()
        if (
            $Bytes[0] -eq 0 -or
            $Bytes[0] -eq 10 -or
            $Bytes[0] -eq 127 -or
            ($Bytes[0] -eq 169 -and $Bytes[1] -eq 254) -or
            ($Bytes[0] -eq 172 -and $Bytes[1] -ge 16 -and $Bytes[1] -le 31) -or
            ($Bytes[0] -eq 192 -and $Bytes[1] -eq 0 -and $Bytes[2] -eq 0) -or
            ($Bytes[0] -eq 192 -and $Bytes[1] -eq 0 -and $Bytes[2] -eq 2) -or
            ($Bytes[0] -eq 192 -and $Bytes[1] -eq 168) -or
            ($Bytes[0] -eq 100 -and $Bytes[1] -ge 64 -and $Bytes[1] -le 127) -or
            ($Bytes[0] -eq 198 -and $Bytes[1] -in @(18, 19)) -or
            ($Bytes[0] -eq 198 -and $Bytes[1] -eq 51 -and $Bytes[2] -eq 100) -or
            ($Bytes[0] -eq 203 -and $Bytes[1] -eq 0 -and $Bytes[2] -eq 113) -or
            $Bytes[0] -ge 224
        ) {
            return $false
        }
        return $true
    }
    if (
        $Address.IsIPv6LinkLocal -or
        $Address.IsIPv6SiteLocal -or
        $Address.IsIPv6Multicast -or
        $Address.Equals([System.Net.IPAddress]::IPv6Any) -or
        $Address.Equals([System.Net.IPAddress]::IPv6None)
    ) {
        return $false
    }
    $Ipv6Bytes = $Address.GetAddressBytes()
    if (($Ipv6Bytes[0] -band 0xFE) -eq 0xFC) {
        return $false
    }
    if (
        $Ipv6Bytes[0] -eq 0x20 -and
        $Ipv6Bytes[1] -eq 0x01 -and
        $Ipv6Bytes[2] -eq 0x0D -and
        $Ipv6Bytes[3] -eq 0xB8
    ) {
        return $false
    }
    return $true
}

function Get-WindowsPublicDnsEvidence {
    param(
        [Parameter(Mandatory = $true)]
        [string]$HostName
    )

    $Addresses = @([System.Net.Dns]::GetHostAddresses($HostName))
    if ($Addresses.Count -eq 0) {
        throw "DNS name did not resolve to an IP address: $HostName"
    }
    $NonPublicAddresses = @(
        $Addresses |
            Where-Object { -not (Test-WindowsPublicIpAddress -Address $_) }
    )
    if ($NonPublicAddresses.Count -gt 0) {
        throw (
            "DNS name resolved to a non-public IP address: " +
            "$HostName -> $($NonPublicAddresses -join ', ')"
        )
    }
    return @($Addresses | ForEach-Object { $_.ToString() })
}

function Invoke-WindowsHttpEvidence {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Uri
    )

    Add-Type -AssemblyName System.Net.Http
    $Handler = New-Object System.Net.Http.HttpClientHandler
    $Handler.AllowAutoRedirect = $false
    $Client = New-Object System.Net.Http.HttpClient($Handler)
    $Client.Timeout = New-TimeSpan -Seconds 15
    try {
        $Response = $Client.GetAsync($Uri).GetAwaiter().GetResult()
        $Body = $Response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        if ($Body.Length -gt 4096) {
            $Body = $Body.Substring(0, 4096)
        }
        return [pscustomobject][ordered]@{
            uri = $Uri
            status_code = [int]$Response.StatusCode
            location = if ($null -ne $Response.Headers.Location) {
                [string]$Response.Headers.Location
            }
            else {
                ""
            }
            body = $Body
        }
    }
    finally {
        $Client.Dispose()
        $Handler.Dispose()
    }
}

function Get-WindowsTlsCertificateEvidence {
    param(
        [Parameter(Mandatory = $true)]
        [string]$HostName
    )

    $TcpClient = New-Object System.Net.Sockets.TcpClient
    $SslStream = $null
    try {
        $TcpClient.Connect($HostName, 443)
        $SslStream = New-Object System.Net.Security.SslStream(
            $TcpClient.GetStream(),
            $false
        )
        $SslStream.AuthenticateAsClient($HostName)
        $Certificate = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2(
            $SslStream.RemoteCertificate
        )
        $Remaining = $Certificate.NotAfter.ToUniversalTime() - [System.DateTime]::UtcNow
        if ($Remaining.TotalDays -lt 14) {
            throw "TLS certificate expires in less than 14 days: $HostName"
        }
        return [pscustomobject][ordered]@{
            host = $HostName
            subject = $Certificate.Subject
            issuer = $Certificate.Issuer
            thumbprint = $Certificate.Thumbprint
            not_before_utc = $Certificate.NotBefore.ToUniversalTime().ToString("o")
            not_after_utc = $Certificate.NotAfter.ToUniversalTime().ToString("o")
            days_remaining = [Math]::Round($Remaining.TotalDays, 2)
            protocol = [string]$SslStream.SslProtocol
        }
    }
    finally {
        if ($null -ne $SslStream) {
            $SslStream.Dispose()
        }
        $TcpClient.Dispose()
    }
}

function Invoke-WindowsPublicTlsValidation {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,

        [Parameter(Mandatory = $true)]
        [string]$ApiHost,

        [Parameter(Mandatory = $true)]
        [string]$StorageHost,

        [Parameter(Mandatory = $true)]
        [string]$RecordDirectory
    )

    $StartedAt = [System.DateTimeOffset]::UtcNow
    $RecordRoot = Resolve-WindowsBackupRoot `
        -RepoRoot $RepoRoot `
        -BackupDirectory $RecordDirectory
    $Failure = $null
    $Evidence = $null
    try {
        $ApiDns = Get-WindowsPublicDnsEvidence -HostName $ApiHost
        $StorageDns = Get-WindowsPublicDnsEvidence -HostName $StorageHost
        $ApiRedirect = Invoke-WindowsHttpEvidence `
            -Uri "http://$ApiHost/readyz"
        $StorageRedirect = Invoke-WindowsHttpEvidence `
            -Uri "http://$StorageHost/minio/health/live"
        if (
            $ApiRedirect.status_code -ne 308 -or
            $ApiRedirect.location -ne "https://$ApiHost/readyz"
        ) {
            throw "API HTTP endpoint did not return the expected HTTPS 308 redirect."
        }
        if (
            $StorageRedirect.status_code -ne 308 -or
            $StorageRedirect.location -ne (
                "https://$StorageHost/minio/health/live"
            )
        ) {
            throw "Storage HTTP endpoint did not return the expected HTTPS 308 redirect."
        }

        $ApiReady = Invoke-WindowsHttpEvidence `
            -Uri "https://$ApiHost/readyz"
        if ($ApiReady.status_code -ne 200) {
            throw "Public API readiness returned HTTP $($ApiReady.status_code)."
        }
        $ApiReadyPayload = $ApiReady.body |
            ConvertFrom-Json -ErrorAction Stop
        if ([string]$ApiReadyPayload.status -ne "ready") {
            throw "Public API readiness did not report status=ready."
        }

        $StorageReady = Invoke-WindowsHttpEvidence `
            -Uri "https://$StorageHost/minio/health/live"
        if ($StorageReady.status_code -ne 200) {
            throw "Public storage readiness returned HTTP $($StorageReady.status_code)."
        }

        $Evidence = [pscustomobject][ordered]@{
            api_dns = $ApiDns
            storage_dns = $StorageDns
            api_redirect = $ApiRedirect
            storage_redirect = $StorageRedirect
            api_ready = [pscustomobject][ordered]@{
                uri = $ApiReady.uri
                status_code = $ApiReady.status_code
                status = [string]$ApiReadyPayload.status
                database = [string]$ApiReadyPayload.checks.database
            }
            storage_ready = [pscustomobject][ordered]@{
                uri = $StorageReady.uri
                status_code = $StorageReady.status_code
            }
            certificates = @(
                Get-WindowsTlsCertificateEvidence -HostName $ApiHost
                Get-WindowsTlsCertificateEvidence -HostName $StorageHost
            )
        }
    }
    catch {
        $Failure = $_
    }

    $CompletedAt = [System.DateTimeOffset]::UtcNow
    $Payload = [pscustomobject][ordered]@{
        action = "public-tls-validation"
        status = if ($null -eq $Failure) { "succeeded" } else { "failed" }
        started_at_utc = $StartedAt.ToString("o")
        completed_at_utc = $CompletedAt.ToString("o")
        duration_seconds = [Math]::Round(
            ($CompletedAt - $StartedAt).TotalSeconds,
            3
        )
        api_host = $ApiHost
        storage_host = $StorageHost
        evidence = $Evidence
        error = if ($null -ne $Failure) {
            "$($Failure.Exception.GetType().Name): $($Failure.Exception.Message)"
        }
        else {
            ""
        }
    }
    $RecordPath = Write-WindowsGovernanceRecord `
        -RepoRoot $RepoRoot `
        -Directory $RecordRoot `
        -Prefix "public-tls-validation" `
        -Payload $Payload
    $Payload | Add-Member `
        -NotePropertyName record_path `
        -NotePropertyValue $RecordPath

    if ($null -ne $Failure) {
        throw (
            "Public TLS validation failed; record: $RecordPath. " +
            $Failure.Exception.Message
        )
    }
    return $Payload
}
