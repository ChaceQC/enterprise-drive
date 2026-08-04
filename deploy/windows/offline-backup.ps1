function Get-WindowsBackupFileInventory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root
    )

    $RootPath = [System.IO.Path]::GetFullPath($Root)
    $Inventory = @()
    foreach (
        $File in @(
            Get-ChildItem -LiteralPath $RootPath -Recurse -File -Force |
                Sort-Object FullName
        )
    ) {
        Assert-WindowsNoReparsePoint `
            -Path $File.FullName `
            -Label "Offline backup inventory file"
        $Inventory += [pscustomobject][ordered]@{
            path = Get-WindowsRelativeArtifactPath `
                -Root $RootPath `
                -Path $File.FullName
            size_bytes = [int64]$File.Length
            sha256 = Get-WindowsSha256 -Path $File.FullName
        }
    }
    return @($Inventory)
}

function Get-WindowsBackupInventoryDigest {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Inventory
    )

    $Canonical = (
        @(
            $Inventory |
                Sort-Object path |
                ForEach-Object {
                    "{0}`t{1}`t{2}" -f
                    [string]$_.path,
                    [int64]$_.size_bytes,
                    [string]$_.sha256
                }
        ) -join "`n"
    ) + "`n"
    $Encoding = New-Object System.Text.UTF8Encoding($false)
    $Sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $Hash = $Sha256.ComputeHash($Encoding.GetBytes($Canonical))
        return -join ($Hash | ForEach-Object { $_.ToString("x2") })
    }
    finally {
        $Sha256.Dispose()
    }
}

function Assert-WindowsBackupInventoriesEqual {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Expected,

        [Parameter(Mandatory = $true)]
        [object[]]$Actual
    )

    if ($Expected.Count -ne $Actual.Count) {
        throw "Offline backup inventory file count does not match."
    }
    $ExpectedDigest = Get-WindowsBackupInventoryDigest -Inventory $Expected
    $ActualDigest = Get-WindowsBackupInventoryDigest -Inventory $Actual
    if ($ExpectedDigest -ne $ActualDigest) {
        throw "Offline backup inventory digest does not match."
    }
    return $ExpectedDigest
}

function Invoke-WindowsOfflineBackupRotation {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,

        [Parameter(Mandatory = $true)]
        [string[]]$ComposeBaseArguments,

        [string]$BackupPath,

        [string]$BackupDirectory,

        [Parameter(Mandatory = $true)]
        [string]$OfflineBackupDirectory,

        [ValidateRange(1, 3650)]
        [int]$RetentionDays = 120,

        [ValidateRange(1, 1000)]
        [int]$RetentionCount = 12,

        [switch]$ApplyRetention
    )

    if (
        [string]::IsNullOrWhiteSpace($BackupPath) -eq
        [string]::IsNullOrWhiteSpace($BackupDirectory)
    ) {
        throw "Offline rotation requires exactly one of BackupPath or BackupDirectory."
    }
    $ProjectName = Get-WindowsComposeProjectName `
        -ComposeBaseArguments $ComposeBaseArguments
    $SourceRecord = $null
    if (-not [string]::IsNullOrWhiteSpace($BackupPath)) {
        $SourceRecord = Get-WindowsBackupRecord -BackupPath $BackupPath
        if ([string]$SourceRecord.source_project -ne $ProjectName) {
            throw "Offline backup source project does not match the current Compose project."
        }
    }
    else {
        $SourceInventory = @(
            Get-WindowsBackupInventory `
                -RepoRoot $RepoRoot `
                -BackupDirectory $BackupDirectory |
                Where-Object {
                    [string]$_.source_project -eq $ProjectName
                }
        )
        if ($SourceInventory.Count -eq 0) {
            throw "No managed backup exists for project '$ProjectName'."
        }
        $SourceRecord = $SourceInventory[0]
    }

    $SourcePath = [System.IO.Path]::GetFullPath([string]$SourceRecord.path)
    $OfflineRoot = Resolve-WindowsBackupRoot `
        -RepoRoot $RepoRoot `
        -BackupDirectory $OfflineBackupDirectory
    if (
        $OfflineRoot -eq $SourcePath -or
        (Test-WindowsPathWithin -Parent $SourcePath -Candidate $OfflineRoot) -or
        (Test-WindowsPathWithin -Parent $OfflineRoot -Candidate $SourcePath)
    ) {
        throw "Offline backup directory must be separate from the source backup."
    }

    $Mutex = Enter-WindowsDeploymentMutex `
        -ProjectName "$ProjectName-offline-backup"
    $StagingPath = $null
    $DestinationPath = $null
    $PublishedByThisRun = $false
    $OperationCompleted = $false
    try {
        $SourceFiles = @(Get-WindowsBackupFileInventory -Root $SourcePath)
        $SourceDigest = Get-WindowsBackupInventoryDigest `
            -Inventory $SourceFiles
        $DestinationPath = Join-Path $OfflineRoot ([string]$SourceRecord.name)
        $CopyStatus = "copied"
        if (Test-Path -LiteralPath $DestinationPath -PathType Container) {
            $DestinationRecord = Get-WindowsBackupRecord `
                -BackupPath $DestinationPath
            if (
                [string]$DestinationRecord.backup_id -ne
                [string]$SourceRecord.backup_id
            ) {
                throw "Offline destination backup ID does not match the source."
            }
            $DestinationFiles = @(
                Get-WindowsBackupFileInventory -Root $DestinationPath
            )
            $null = Assert-WindowsBackupInventoriesEqual `
                -Expected $SourceFiles `
                -Actual $DestinationFiles
            $CopyStatus = "already-present"
        }
        else {
            $StagingPath = Join-Path (
                $OfflineRoot
            ) ".partial-offline-$([string]$SourceRecord.backup_id)"
            if (Test-Path -LiteralPath $StagingPath) {
                throw "Offline backup staging path already exists: $StagingPath"
            }
            $null = New-Item -ItemType Directory -Path $StagingPath
            Set-WindowsRestrictedAcl -Path $StagingPath -Directory
            Copy-Item `
                -Path (Join-Path $SourcePath "*") `
                -Destination $StagingPath `
                -Recurse `
                -Force
            $CopiedFiles = @(Get-WindowsBackupFileInventory -Root $StagingPath)
            $null = Assert-WindowsBackupInventoriesEqual `
                -Expected $SourceFiles `
                -Actual $CopiedFiles
            [System.IO.Directory]::Move($StagingPath, $DestinationPath)
            $StagingPath = $null
            $PublishedByThisRun = $true
            $null = Get-WindowsBackupRecord -BackupPath $DestinationPath
            Assert-WindowsRestrictedAcl -Path $DestinationPath
        }

        $OfflineRecords = @(
            Get-WindowsBackupInventory `
                -RepoRoot $RepoRoot `
                -BackupDirectory $OfflineRoot |
                Where-Object {
                    [string]$_.source_project -eq $ProjectName
                }
        )
        $Cutoff = [System.DateTimeOffset]::UtcNow.AddDays(-$RetentionDays)
        $Eligible = @()
        for ($Index = 0; $Index -lt $OfflineRecords.Count; $Index++) {
            $Record = $OfflineRecords[$Index]
            if (
                $Index -ge $RetentionCount -and
                $Record.created_at_utc -lt $Cutoff
            ) {
                $Eligible += $Record
            }
        }
        $RemovedPaths = @()
        if ($ApplyRetention) {
            foreach ($Record in $Eligible) {
                $Candidate = [System.IO.Path]::GetFullPath(
                    [string]$Record.path
                )
                if (
                    $Candidate -eq $OfflineRoot -or
                    -not (
                        Test-WindowsPathWithin `
                            -Parent $OfflineRoot `
                            -Candidate $Candidate
                    )
                ) {
                    throw "Refusing to remove an offline backup outside the offline root."
                }
                Assert-WindowsNoReparsePoint `
                    -Path $Candidate `
                    -Label "Offline backup retention deletion"
                Assert-WindowsRestrictedAcl -Path $Candidate
                Remove-Item -LiteralPath $Candidate -Recurse -Force
                $RemovedPaths += $Candidate
            }
        }

        $Payload = [pscustomobject][ordered]@{
            action = "backup-offline-rotate"
            rotation_id = [Guid]::NewGuid().ToString("N")
            created_at_utc = [System.DateTime]::UtcNow.ToString("o")
            source_project = $ProjectName
            source_backup_path = $SourcePath
            source_backup_id = [string]$SourceRecord.backup_id
            source_inventory_files = $SourceFiles.Count
            source_inventory_sha256 = $SourceDigest
            offline_backup_root = $OfflineRoot
            offline_backup_path = $DestinationPath
            copy_status = $CopyStatus
            retention_days = $RetentionDays
            retention_count = $RetentionCount
            apply_retention = [bool]$ApplyRetention
            retention_eligible = $Eligible.Count
            removed_paths = @($RemovedPaths)
        }
        $RecordPath = Write-WindowsGovernanceRecord `
            -RepoRoot $RepoRoot `
            -Directory (Join-Path $OfflineRoot ".governance\offline-copies") `
            -Prefix "offline-copy" `
            -Payload $Payload
        $Payload | Add-Member `
            -NotePropertyName record_path `
            -NotePropertyValue $RecordPath
        $OperationCompleted = $true
        return $Payload
    }
    finally {
        if (
            -not [string]::IsNullOrWhiteSpace($StagingPath) -and
            (Test-Path -LiteralPath $StagingPath -PathType Container)
        ) {
            if (
                Test-WindowsPathWithin `
                    -Parent $OfflineRoot `
                    -Candidate $StagingPath
            ) {
                Remove-Item -LiteralPath $StagingPath -Recurse -Force
            }
        }
        if (
            $PublishedByThisRun -and
            -not $OperationCompleted -and
            -not [string]::IsNullOrWhiteSpace($DestinationPath) -and
            (Test-Path -LiteralPath $DestinationPath -PathType Container) -and
            (Test-WindowsPathWithin -Parent $OfflineRoot -Candidate $DestinationPath)
        ) {
            Remove-Item -LiteralPath $DestinationPath -Recurse -Force
        }
        Exit-WindowsDeploymentMutex -Mutex $Mutex
    }
}
