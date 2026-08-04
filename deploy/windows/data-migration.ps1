function Invoke-WindowsOpenSearchRequest {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$ComposeBaseArguments,

        [Parameter(Mandatory = $true)]
        [ValidateSet("GET", "POST", "PUT", "DELETE")]
        [string]$Method,

        [Parameter(Mandatory = $true)]
        [string]$Path,

        [AllowEmptyString()]
        [string]$Body = "",

        [int[]]$ExpectedStatus = @(200)
    )

    $Containers = @(
        Get-WindowsComposeContainers `
            -ComposeBaseArguments $ComposeBaseArguments |
            Where-Object { [string]$_.Service -eq "opensearch" }
    )
    if ($Containers.Count -ne 1) {
        throw "OpenSearch migration requires exactly one Compose container."
    }
    if ([string]$Containers[0].State -ne "running") {
        throw "OpenSearch migration requires the Compose service to be running."
    }
    $IdProperty = $Containers[0].PSObject.Properties["ID"]
    if ($null -eq $IdProperty) {
        $IdProperty = $Containers[0].PSObject.Properties["Id"]
    }
    $ContainerId = if ($null -eq $IdProperty) {
        ""
    }
    else {
        [string]$IdProperty.Value
    }
    if ([string]::IsNullOrWhiteSpace($ContainerId)) {
        throw "OpenSearch migration could not resolve the container ID."
    }

    $RemotePath = ""
    $TemporaryRoot = ""
    try {
        $Arguments = @(
            $ComposeBaseArguments +
            @(
                "exec",
                "--no-TTY",
                "opensearch",
                "curl",
                "-sS",
                "-X$Method",
                "-H",
                "Content-Type: application/json"
            )
        )
        if (-not [string]::IsNullOrEmpty($Body)) {
            $TemporaryRoot = Join-Path (
                [System.IO.Path]::GetTempPath()
            ) (
                "enterprise-drive-opensearch-request-" +
                [Guid]::NewGuid().ToString("N")
            )
            $null = New-Item -ItemType Directory -Path $TemporaryRoot
            Set-WindowsRestrictedAcl -Path $TemporaryRoot -Directory
            $RequestPath = Join-Path $TemporaryRoot "request.json"
            Write-WindowsRestrictedUtf8File `
                -Path $RequestPath `
                -Content $Body
            $RemotePath = "/tmp/enterprise-drive-$([Guid]::NewGuid().ToString('N')).json"
            $null = Invoke-WindowsDocker -Arguments @(
                "cp",
                $RequestPath,
                "${ContainerId}:$RemotePath"
            )
            $Arguments += @("--data-binary", "@$RemotePath")
        }
        $Arguments += @(
            "-w",
            "`n__HTTP_STATUS__:%{http_code}",
            "http://127.0.0.1:9200$Path"
        )
        $Output = @(Invoke-WindowsDocker -Arguments $Arguments)
        $Text = $Output -join "`n"
        $Match = [regex]::Match(
            $Text,
            "(?s)^(?<body>.*)`n__HTTP_STATUS__:(?<status>[0-9]{3})$"
        )
        if (-not $Match.Success) {
            throw "OpenSearch migration response did not contain an HTTP status."
        }
        $Status = [int]$Match.Groups["status"].Value
        $ResponseBody = $Match.Groups["body"].Value
        if ($Status -notin $ExpectedStatus) {
            $Excerpt = if ($ResponseBody.Length -gt 500) {
                $ResponseBody.Substring(0, 500)
            }
            else {
                $ResponseBody
            }
            throw "OpenSearch migration request failed with HTTP ${Status}: $Excerpt"
        }
        return [pscustomobject][ordered]@{
            status = $Status
            body = $ResponseBody
        }
    }
    finally {
        if (-not [string]::IsNullOrWhiteSpace($RemotePath)) {
            try {
                $null = Invoke-WindowsDocker -Arguments @(
                    @(
                        "exec",
                        "--user", "0",
                        $ContainerId,
                        "rm",
                        "-f",
                        $RemotePath
                    )
                )
            }
            catch {
                Write-Warning "OpenSearch request cleanup failed: $($_.Exception.Message)"
            }
        }
        if (
            -not [string]::IsNullOrWhiteSpace($TemporaryRoot) -and
            (Test-Path -LiteralPath $TemporaryRoot -PathType Container)
        ) {
            Remove-Item -LiteralPath $TemporaryRoot -Recurse -Force
        }
    }
}

function Get-WindowsComposeImageRecord {
    param(
        [Parameter(Mandatory = $true)]
        [object]$ComposeModel,

        [Parameter(Mandatory = $true)]
        [string[]]$ComposeBaseArguments,

        [Parameter(Mandatory = $true)]
        [string]$ServiceName
    )

    $Containers = @(
        Get-WindowsComposeContainers `
            -ComposeBaseArguments $ComposeBaseArguments |
            Where-Object { [string]$_.Service -eq $ServiceName }
    )
    if ($Containers.Count -ne 1) {
        throw "Migration requires exactly one container for '$ServiceName'."
    }
    $Reference = Get-WindowsModelServiceImage `
        -ComposeModel $ComposeModel `
        -ServiceName $ServiceName
    $ImageInfo = Get-WindowsImageInfo -Image $Reference
    $ContainerImageId = Get-WindowsComposeContainerImageId `
        -Container $Containers[0]
    if ([string]$ContainerImageId -ne [string]$ImageInfo.id) {
        throw "Migration image ID does not match the reference for '$ServiceName'."
    }
    return [pscustomobject][ordered]@{
        service = $ServiceName
        reference = [string]$ImageInfo.reference
        id = $ContainerImageId
        repo_digests = @($ImageInfo.repo_digests)
    }
}

function Export-WindowsRedisPortableData {
    param(
        [Parameter(Mandatory = $true)]
        [object]$ComposeModel,

        [Parameter(Mandatory = $true)]
        [string[]]$ComposeBaseArguments,

        [Parameter(Mandatory = $true)]
        [string]$StagingRoot
    )

    $RedisDirectory = Join-Path $StagingRoot "redis"
    $null = New-Item -ItemType Directory -Path $RedisDirectory -Force
    $RedisRecord = Get-WindowsComposeImageRecord `
        -ComposeModel $ComposeModel `
        -ComposeBaseArguments $ComposeBaseArguments `
        -ServiceName "redis"
    $RedisPassword = Get-WindowsModelEnvironmentValue `
        -ComposeModel $ComposeModel `
        -ServiceName "redis" `
        -Name "REDIS_PASSWORD"
    $BackendNetwork = Get-WindowsModelBackendNetwork -ComposeModel $ComposeModel
    $null = Invoke-WindowsBackupHelperContainer -Arguments @(
        "--network", $BackendNetwork,
        "--user", "0:0",
        "--entrypoint", "sh",
        "--mount", "type=bind,source=$RedisDirectory,target=/migration",
        "-e", "REDISCLI_AUTH=$RedisPassword",
        [string]$RedisRecord.id,
        "-ec",
        "redis-cli -h redis --rdb /migration/redis.rdb >/dev/null"
    )
    $RdbPath = Join-Path $RedisDirectory "redis.rdb"
    if (
        -not (Test-Path -LiteralPath $RdbPath -PathType Leaf) -or
        [int64](Get-Item -LiteralPath $RdbPath).Length -le 0
    ) {
        throw "Redis portable export did not create a nonempty RDB."
    }
    $Info = @(
        Invoke-WindowsDocker -Arguments @(
            $ComposeBaseArguments +
            @("exec", "--no-TTY", "redis", "redis-cli", "INFO", "server")
        )
    ) -join "`n"
    $VersionMatch = [regex]::Match($Info, "(?m)^redis_version:(?<value>[^\r\n]+)")
    if (-not $VersionMatch.Success) {
        throw "Redis portable export could not determine the server version."
    }
    $Keyspace = @(
        Invoke-WindowsDocker -Arguments @(
            $ComposeBaseArguments +
            @("exec", "--no-TTY", "redis", "redis-cli", "INFO", "keyspace")
        )
    ) -join "`n"
    return [ordered]@{
        image_reference = [string]$RedisRecord.reference
        image_id = [string]$RedisRecord.id
        server_version = $VersionMatch.Groups["value"].Value.Trim()
        keyspace_info = $Keyspace.Trim()
        artifact_path = "redis/redis.rdb"
    }
}

function Export-WindowsOpenSearchPortableData {
    param(
        [Parameter(Mandatory = $true)]
        [object]$ComposeModel,

        [Parameter(Mandatory = $true)]
        [string[]]$ComposeBaseArguments,

        [Parameter(Mandatory = $true)]
        [string]$StagingRoot
    )

    $OpenSearchDirectory = Join-Path $StagingRoot "opensearch"
    $null = New-Item -ItemType Directory -Path $OpenSearchDirectory -Force
    $OpenSearchRecord = Get-WindowsComposeImageRecord `
        -ComposeModel $ComposeModel `
        -ComposeBaseArguments $ComposeBaseArguments `
        -ServiceName "opensearch"
    $IndexName = Get-WindowsModelEnvironmentValue `
        -ComposeModel $ComposeModel `
        -ServiceName "api" `
        -Name "DRIVE_OPENSEARCH_INDEX_NAME"
    $EncodedIndex = [System.Uri]::EscapeDataString($IndexName)
    $VersionResponse = Invoke-WindowsOpenSearchRequest `
        -ComposeBaseArguments $ComposeBaseArguments `
        -Method GET `
        -Path "/"
    $VersionObject = $VersionResponse.body | ConvertFrom-Json -ErrorAction Stop
    $IndexResponse = Invoke-WindowsOpenSearchRequest `
        -ComposeBaseArguments $ComposeBaseArguments `
        -Method GET `
        -Path "/$EncodedIndex" `
        -ExpectedStatus @(200, 404)
    $IndexExists = $IndexResponse.status -eq 200
    $MetadataPath = Join-Path $OpenSearchDirectory "index.json"
    $BulkPath = Join-Path $OpenSearchDirectory "documents.ndjson"
    if ($IndexExists) {
        Write-WindowsUtf8File `
            -Path $MetadataPath `
            -Content ($IndexResponse.body.Trim() + "`n")
    }
    else {
        Write-WindowsUtf8File -Path $MetadataPath -Content "{}`n"
    }
    $Writer = New-Object System.IO.StreamWriter(
        $BulkPath,
        $false,
        (New-Object System.Text.UTF8Encoding($false))
    )
    $DocumentCount = 0L
    $ScrollId = ""
    try {
        if ($IndexExists) {
            $SearchResponse = Invoke-WindowsOpenSearchRequest `
                -ComposeBaseArguments $ComposeBaseArguments `
                -Method POST `
                -Path "/$EncodedIndex/_search?scroll=2m" `
                -Body '{"size":500,"sort":["_doc"],"query":{"match_all":{}}}'
            while ($true) {
                $SearchObject = $SearchResponse.body |
                    ConvertFrom-Json -ErrorAction Stop
                $ScrollId = [string]$SearchObject._scroll_id
                $Hits = @($SearchObject.hits.hits)
                if ($Hits.Count -eq 0) {
                    break
                }
                foreach ($Hit in $Hits) {
                    $Action = [ordered]@{
                        index = [ordered]@{
                            _id = [string]$Hit._id
                        }
                    }
                    $Writer.WriteLine(
                        ($Action | ConvertTo-Json -Compress -Depth 8)
                    )
                    $Source = if ($null -eq $Hit._source) {
                        [pscustomobject]@{}
                    }
                    else {
                        $Hit._source
                    }
                    $Writer.WriteLine(
                        ($Source | ConvertTo-Json -Compress -Depth 100)
                    )
                    $DocumentCount++
                }
                if ([string]::IsNullOrWhiteSpace($ScrollId)) {
                    throw "OpenSearch export response is missing a scroll ID."
                }
                $ScrollBody = [ordered]@{
                    scroll = "2m"
                    scroll_id = $ScrollId
                } | ConvertTo-Json -Compress
                $SearchResponse = Invoke-WindowsOpenSearchRequest `
                    -ComposeBaseArguments $ComposeBaseArguments `
                    -Method POST `
                    -Path "/_search/scroll" `
                    -Body $ScrollBody
            }
        }
    }
    finally {
        $Writer.Dispose()
        if (-not [string]::IsNullOrWhiteSpace($ScrollId)) {
            try {
                $ClearBody = [ordered]@{
                    scroll_id = @($ScrollId)
                } | ConvertTo-Json -Compress
                $null = Invoke-WindowsOpenSearchRequest `
                    -ComposeBaseArguments $ComposeBaseArguments `
                    -Method DELETE `
                    -Path "/_search/scroll" `
                    -Body $ClearBody `
                    -ExpectedStatus @(200, 404)
            }
            catch {
                Write-Warning "OpenSearch scroll cleanup failed: $($_.Exception.Message)"
            }
        }
    }
    return [ordered]@{
        image_reference = [string]$OpenSearchRecord.reference
        image_id = [string]$OpenSearchRecord.id
        server_version = [string]$VersionObject.version.number
        index_name = $IndexName
        index_exists = $IndexExists
        document_count = $DocumentCount
        metadata_path = "opensearch/index.json"
        bulk_path = "opensearch/documents.ndjson"
    }
}

function New-WindowsPortableDataExport {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,

        [Parameter(Mandatory = $true)]
        [string[]]$ComposeBaseArguments,

        [Parameter(Mandatory = $true)]
        [string]$ExportDirectory
    )

    $Root = Resolve-WindowsBackupRoot `
        -RepoRoot $RepoRoot `
        -BackupDirectory $ExportDirectory
    $ComposeModel = Get-WindowsComposeModel `
        -ComposeBaseArguments $ComposeBaseArguments
    $ProjectName = [string]$ComposeModel.name
    $Mutex = Enter-WindowsDeploymentMutex -ProjectName $ProjectName
    $PartialPath = ""
    try {
        Wait-WindowsComposeServices `
            -ComposeBaseArguments $ComposeBaseArguments `
            -Services @("redis", "opensearch") `
            -TimeoutSeconds 180
        $ExportId = [Guid]::NewGuid().ToString("N")
        $Timestamp = [System.DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
        $SafeProject = [regex]::Replace(
            $ProjectName,
            "[^A-Za-z0-9._-]",
            "-"
        )
        $Name = "$Timestamp-$SafeProject-portable-$ExportId"
        $PartialPath = Join-Path $Root ".partial-portable-$ExportId"
        $FinalPath = Join-Path $Root $Name
        $null = New-Item -ItemType Directory -Path $PartialPath
        Set-WindowsRestrictedAcl -Path $PartialPath -Directory

        $Redis = Export-WindowsRedisPortableData `
            -ComposeModel $ComposeModel `
            -ComposeBaseArguments $ComposeBaseArguments `
            -StagingRoot $PartialPath
        $OpenSearch = Export-WindowsOpenSearchPortableData `
            -ComposeModel $ComposeModel `
            -ComposeBaseArguments $ComposeBaseArguments `
            -StagingRoot $PartialPath
        $Artifacts = @()
        foreach (
            $File in @(
                Get-ChildItem -LiteralPath $PartialPath -Recurse -File |
                    Sort-Object FullName
            )
        ) {
            $Artifacts += [pscustomobject][ordered]@{
                path = Get-WindowsRelativeArtifactPath `
                    -Root $PartialPath `
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
            project_version = Get-WindowsProjectVersion -RepoRoot $RepoRoot
            git_commit = Get-WindowsGitCommit -RepoRoot $RepoRoot
            redis = $Redis
            opensearch = $OpenSearch
            artifacts = $Artifacts
        }
        $ManifestPath = Join-Path $PartialPath "manifest.json"
        Write-WindowsUtf8File `
            -Path $ManifestPath `
            -Content (($Manifest | ConvertTo-Json -Depth 16) + "`n")
        $ManifestHash = Get-WindowsSha256 -Path $ManifestPath
        Write-WindowsUtf8File `
            -Path (Join-Path $PartialPath "manifest.sha256") `
            -Content "$ManifestHash  manifest.json`n"
        $null = Test-WindowsPortableDataExport -ExportPath $PartialPath
        [System.IO.Directory]::Move($PartialPath, $FinalPath)
        $PartialPath = ""
        Assert-WindowsRestrictedAcl -Path $FinalPath
        return $FinalPath
    }
    finally {
        if (
            -not [string]::IsNullOrWhiteSpace($PartialPath) -and
            (Test-Path -LiteralPath $PartialPath -PathType Container)
        ) {
            Remove-Item -LiteralPath $PartialPath -Recurse -Force
        }
        Exit-WindowsDeploymentMutex -Mutex $Mutex
    }
}

function Test-WindowsPortableDataExport {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ExportPath
    )

    $Root = [System.IO.Path]::GetFullPath($ExportPath)
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
        throw "Portable data export does not exist: $Root"
    }
    Assert-WindowsNoReparsePoint -Path $Root -Label "Portable data export"
    Assert-WindowsRestrictedAcl -Path $Root
    $ManifestPath = Join-Path $Root "manifest.json"
    $ChecksumPath = Join-Path $Root "manifest.sha256"
    foreach ($Path in @($ManifestPath, $ChecksumPath)) {
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
            throw "Portable data export metadata is missing: $Path"
        }
    }
    $StrictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)
    $Checksum = [System.IO.File]::ReadAllText(
        $ChecksumPath,
        $StrictUtf8
    ).Trim()
    if ($Checksum -notmatch "^([0-9a-f]{64})  manifest[.]json$") {
        throw "Portable data export checksum format is invalid."
    }
    if ((Get-WindowsSha256 -Path $ManifestPath) -ne $Matches[1]) {
        throw "Portable data export manifest checksum does not match."
    }
    $Manifest = (
        [System.IO.File]::ReadAllText($ManifestPath, $StrictUtf8) |
        ConvertFrom-Json -ErrorAction Stop
    )
    foreach ($PropertyName in @(
        "format_version",
        "export_id",
        "created_at_utc",
        "source_project",
        "project_version",
        "git_commit",
        "redis",
        "opensearch",
        "artifacts"
    )) {
        if ($null -eq $Manifest.PSObject.Properties[$PropertyName]) {
            throw "Portable data export manifest is missing '$PropertyName'."
        }
    }
    if (
        [int64]$Manifest.format_version -ne 1 -or
        [string]$Manifest.export_id -notmatch "^[0-9a-f]{32}$" -or
        $Manifest.artifacts -isnot [System.Array]
    ) {
        throw "Portable data export manifest header is invalid."
    }
    $Seen = New-Object "System.Collections.Generic.HashSet[string]" (
        [System.StringComparer]::OrdinalIgnoreCase
    )
    foreach ($Artifact in @($Manifest.artifacts)) {
        if (-not $Seen.Add([string]$Artifact.path)) {
            throw "Portable data export contains a duplicate artifact."
        }
        $Path = Resolve-WindowsBackupArtifactPath `
            -BackupRoot $Root `
            -RelativePath ([string]$Artifact.path)
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
            throw "Portable data export artifact is missing: $($Artifact.path)"
        }
        if (
            [int64](Get-Item -LiteralPath $Path).Length -ne
            [int64]$Artifact.size_bytes -or
            (Get-WindowsSha256 -Path $Path) -ne [string]$Artifact.sha256
        ) {
            throw "Portable data export artifact verification failed: $($Artifact.path)"
        }
    }
    foreach ($RequiredPath in @(
        [string]$Manifest.redis.artifact_path,
        [string]$Manifest.opensearch.metadata_path,
        [string]$Manifest.opensearch.bulk_path
    )) {
        if (-not $Seen.Contains($RequiredPath)) {
            throw "Portable data export is missing a required artifact: $RequiredPath"
        }
    }
    return $Manifest
}

function Get-WindowsMajorVersion {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Version
    )

    $Match = [regex]::Match($Version, "^(?<major>[0-9]+)[.]")
    if (-not $Match.Success) {
        throw "Migration server version is invalid: $Version"
    }
    return [int]$Match.Groups["major"].Value
}

function Get-WindowsCurrentDataVersions {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$ComposeBaseArguments
    )

    $RedisInfo = @(
        Invoke-WindowsDocker -Arguments @(
            $ComposeBaseArguments +
            @("exec", "--no-TTY", "redis", "redis-cli", "INFO", "server")
        )
    ) -join "`n"
    $RedisMatch = [regex]::Match(
        $RedisInfo,
        "(?m)^redis_version:(?<value>[^\r\n]+)"
    )
    if (-not $RedisMatch.Success) {
        throw "Migration could not determine the target Redis version."
    }
    $OpenSearchResponse = Invoke-WindowsOpenSearchRequest `
        -ComposeBaseArguments $ComposeBaseArguments `
        -Method GET `
        -Path "/"
    $OpenSearchObject = $OpenSearchResponse.body |
        ConvertFrom-Json -ErrorAction Stop
    return [pscustomobject][ordered]@{
        redis = $RedisMatch.Groups["value"].Value.Trim()
        opensearch = [string]$OpenSearchObject.version.number
    }
}

function Restore-WindowsRedisPortableData {
    param(
        [Parameter(Mandatory = $true)]
        [object]$ComposeModel,

        [Parameter(Mandatory = $true)]
        [string[]]$ComposeBaseArguments,

        [Parameter(Mandatory = $true)]
        [string]$ExportRoot,

        [Parameter(Mandatory = $true)]
        [object]$Manifest
    )

    $VolumeMap = Get-WindowsBackupVolumeMap -ComposeModel $ComposeModel
    $RedisRecord = Get-WindowsComposeImageRecord `
        -ComposeModel $ComposeModel `
        -ComposeBaseArguments $ComposeBaseArguments `
        -ServiceName "redis"
    $RdbPath = Resolve-WindowsBackupArtifactPath `
        -BackupRoot $ExportRoot `
        -RelativePath ([string]$Manifest.redis.artifact_path)
    $RedisDirectory = [System.IO.Path]::GetDirectoryName($RdbPath)
    $null = Invoke-WindowsDocker -Arguments @(
        $ComposeBaseArguments +
        @("stop", "--timeout", "60", "redis")
    )
    Clear-WindowsVolume `
        -ArchiveToolImage ([string]$RedisRecord.id) `
        -VolumeName ([string]$VolumeMap["redis-data"])
    $RedisBootstrapScript = @(
        "cp /migration/redis.rdb /data/dump.rdb"
        "rm -rf /data/appendonlydir"
        "chown -R redis:redis /data"
        (
            'redis-server --dir /data --dbfilename dump.rdb ' +
            '--appendonly no --port 6379 --daemonize yes'
        )
        "attempt=0"
        (
            'until redis-cli -p 6379 ping 2>/dev/null | grep -qx PONG; do ' +
            'attempt=$((attempt + 1)); test $attempt -lt 60; sleep 1; done'
        )
        "redis-cli -p 6379 CONFIG SET appendonly yes | grep -qx OK"
        "attempt=0"
        (
            'until redis-cli -p 6379 INFO persistence | ' +
            'grep -q ^aof_rewrite_in_progress:0; do ' +
            'attempt=$((attempt + 1)); test $attempt -lt 120; sleep 1; done'
        )
        (
            'redis-cli -p 6379 INFO persistence | ' +
            'grep -q ^aof_last_bgrewrite_status:ok'
        )
        "redis-cli -p 6379 SHUTDOWN SAVE"
        "chown -R redis:redis /data"
    ) -join "; "
    $null = Invoke-WindowsBackupHelperContainer -Arguments @(
        "--network", "none",
        "--user", "0:0",
        "--entrypoint", "sh",
        "--mount", "type=volume,source=$($VolumeMap['redis-data']),target=/data",
        "--mount", "type=bind,source=$RedisDirectory,target=/migration,readonly",
        [string]$RedisRecord.id,
        "-ec",
        $RedisBootstrapScript
    )
    $null = Invoke-WindowsDocker -Arguments @(
        $ComposeBaseArguments +
        @(
            "up",
            "--detach",
            "--no-deps",
            "--no-build",
            "--pull", "never",
            "redis"
        )
    )
    Wait-WindowsComposeServices `
        -ComposeBaseArguments $ComposeBaseArguments `
        -Services @("redis") `
        -TimeoutSeconds 180
}

function ConvertTo-WindowsOpenSearchCreateBody {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Metadata,

        [Parameter(Mandatory = $true)]
        [string]$SourceIndex
    )

    $IndexProperty = $Metadata.PSObject.Properties[$SourceIndex]
    if ($null -eq $IndexProperty) {
        throw "OpenSearch export metadata does not contain the source index."
    }
    $Index = $IndexProperty.Value
    $Settings = [ordered]@{}
    $IndexSettingsProperty = $Index.settings.PSObject.Properties["index"]
    if ($null -ne $IndexSettingsProperty) {
        $IndexSettings = $IndexSettingsProperty.Value
        foreach ($Name in @(
            "number_of_shards",
            "number_of_replicas",
            "refresh_interval",
            "max_result_window",
            "analysis",
            "sort"
        )) {
            $Property = $IndexSettings.PSObject.Properties[$Name]
            if ($null -ne $Property) {
                $Settings[$Name] = $Property.Value
            }
        }
    }
    $Body = [ordered]@{
        settings = $Settings
        mappings = $Index.mappings
    }
    if ($null -ne $Index.PSObject.Properties["aliases"]) {
        $Body["aliases"] = $Index.aliases
    }
    return $Body | ConvertTo-Json -Compress -Depth 100
}

function Import-WindowsOpenSearchBulkFile {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$ComposeBaseArguments,

        [Parameter(Mandatory = $true)]
        [string]$BulkPath,

        [Parameter(Mandatory = $true)]
        [string]$TargetIndex,

        [ValidateRange(1, 5000)]
        [int]$BatchDocuments = 500
    )

    $EncodedTarget = [System.Uri]::EscapeDataString($TargetIndex)
    $Reader = New-Object System.IO.StreamReader(
        $BulkPath,
        (New-Object System.Text.UTF8Encoding($false, $true))
    )
    try {
        while (-not $Reader.EndOfStream) {
            $Builder = New-Object System.Text.StringBuilder
            $Documents = 0
            while (
                $Documents -lt $BatchDocuments -and
                -not $Reader.EndOfStream
            ) {
                $ActionLine = $Reader.ReadLine()
                if ($Reader.EndOfStream) {
                    throw "OpenSearch bulk export contains an incomplete document pair."
                }
                $SourceLine = $Reader.ReadLine()
                $null = $Builder.AppendLine($ActionLine)
                $null = $Builder.AppendLine($SourceLine)
                $Documents++
            }
            if ($Documents -eq 0) {
                break
            }
            $Response = Invoke-WindowsOpenSearchRequest `
                -ComposeBaseArguments $ComposeBaseArguments `
                -Method POST `
                -Path "/$EncodedTarget/_bulk" `
                -Body $Builder.ToString()
            $Object = $Response.body | ConvertFrom-Json -ErrorAction Stop
            if ([bool]$Object.errors) {
                throw "OpenSearch bulk migration reported document errors."
            }
        }
    }
    finally {
        $Reader.Dispose()
    }
}

function Restore-WindowsOpenSearchPortableData {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$ComposeBaseArguments,

        [Parameter(Mandatory = $true)]
        [string]$ExportRoot,

        [Parameter(Mandatory = $true)]
        [object]$Manifest,

        [Parameter(Mandatory = $true)]
        [string]$TargetIndex
    )

    $EncodedTarget = [System.Uri]::EscapeDataString($TargetIndex)
    $null = Invoke-WindowsOpenSearchRequest `
        -ComposeBaseArguments $ComposeBaseArguments `
        -Method DELETE `
        -Path "/$EncodedTarget" `
        -ExpectedStatus @(200, 404)
    if (-not [bool]$Manifest.opensearch.index_exists) {
        return
    }
    $MetadataPath = Resolve-WindowsBackupArtifactPath `
        -BackupRoot $ExportRoot `
        -RelativePath ([string]$Manifest.opensearch.metadata_path)
    $Metadata = Get-WindowsBackupSecurityJson -Path $MetadataPath
    $CreateBody = ConvertTo-WindowsOpenSearchCreateBody `
        -Metadata $Metadata `
        -SourceIndex ([string]$Manifest.opensearch.index_name)
    $null = Invoke-WindowsOpenSearchRequest `
        -ComposeBaseArguments $ComposeBaseArguments `
        -Method PUT `
        -Path "/$EncodedTarget" `
        -Body $CreateBody
    $BulkPath = Resolve-WindowsBackupArtifactPath `
        -BackupRoot $ExportRoot `
        -RelativePath ([string]$Manifest.opensearch.bulk_path)
    Import-WindowsOpenSearchBulkFile `
        -ComposeBaseArguments $ComposeBaseArguments `
        -BulkPath $BulkPath `
        -TargetIndex $TargetIndex
    $null = Invoke-WindowsOpenSearchRequest `
        -ComposeBaseArguments $ComposeBaseArguments `
        -Method POST `
        -Path "/$EncodedTarget/_refresh"
    $CountResponse = Invoke-WindowsOpenSearchRequest `
        -ComposeBaseArguments $ComposeBaseArguments `
        -Method GET `
        -Path "/$EncodedTarget/_count"
    $CountObject = $CountResponse.body | ConvertFrom-Json -ErrorAction Stop
    if (
        [int64]$CountObject.count -ne
        [int64]$Manifest.opensearch.document_count
    ) {
        throw "OpenSearch migrated document count does not match the export."
    }
}

function Invoke-WindowsPortableDataImportInternal {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$ComposeBaseArguments,

        [Parameter(Mandatory = $true)]
        [string]$ExportPath,

        [Parameter(Mandatory = $true)]
        [object]$Manifest,

        [switch]$SkipVersionCheck
    )

    $ComposeModel = Get-WindowsComposeModel `
        -ComposeBaseArguments $ComposeBaseArguments
    $ProjectName = [string]$ComposeModel.name
    $VolumeMap = Get-WindowsBackupVolumeMap -ComposeModel $ComposeModel
    $Mutex = Enter-WindowsDeploymentMutex -ProjectName $ProjectName
    $VolumeMutexes = @()
    try {
        $VolumeMutexes = @(
            Enter-WindowsDeploymentMutexSet -ResourceNames @(
                "volume:$([string]$VolumeMap['redis-data'])",
                "volume:$([string]$VolumeMap['opensearch-data'])"
            )
        )
        if (-not $SkipVersionCheck) {
            $Versions = Get-WindowsCurrentDataVersions `
                -ComposeBaseArguments $ComposeBaseArguments
            if (
                (Get-WindowsMajorVersion -Version ([string]$Versions.redis)) -lt
                (
                    Get-WindowsMajorVersion `
                        -Version ([string]$Manifest.redis.server_version)
                )
            ) {
                throw "Target Redis major version is older than the export."
            }
            if (
                (Get-WindowsMajorVersion -Version ([string]$Versions.opensearch)) -lt
                (
                    Get-WindowsMajorVersion `
                        -Version ([string]$Manifest.opensearch.server_version)
                )
            ) {
                throw "Target OpenSearch major version is older than the export."
            }
        }
        $TargetIndex = Get-WindowsModelEnvironmentValue `
            -ComposeModel $ComposeModel `
            -ServiceName "api" `
            -Name "DRIVE_OPENSEARCH_INDEX_NAME"
        Restore-WindowsRedisPortableData `
            -ComposeModel $ComposeModel `
            -ComposeBaseArguments $ComposeBaseArguments `
            -ExportRoot $ExportPath `
            -Manifest $Manifest
        Restore-WindowsOpenSearchPortableData `
            -ComposeBaseArguments $ComposeBaseArguments `
            -ExportRoot $ExportPath `
            -Manifest $Manifest `
            -TargetIndex $TargetIndex
        return Get-WindowsCurrentDataVersions `
            -ComposeBaseArguments $ComposeBaseArguments
    }
    finally {
        Exit-WindowsDeploymentMutexSet -Mutexes $VolumeMutexes
        Exit-WindowsDeploymentMutex -Mutex $Mutex
    }
}

function Invoke-WindowsPortableDataMigration {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,

        [Parameter(Mandatory = $true)]
        [string[]]$ComposeBaseArguments,

        [Parameter(Mandatory = $true)]
        [string]$ExportPath,

        [Parameter(Mandatory = $true)]
        [string]$RollbackExportDirectory,

        [Parameter(Mandatory = $true)]
        [string]$RecordDirectory,

        [ValidateSet("apply", "rollback")]
        [string]$Mode = "apply"
    )

    $SourceManifest = Test-WindowsPortableDataExport -ExportPath $ExportPath
    $ComposeModel = Get-WindowsComposeModel `
        -ComposeBaseArguments $ComposeBaseArguments
    $TargetProject = [string]$ComposeModel.name
    $StartedAt = [System.DateTimeOffset]::UtcNow
    $RollbackPath = ""
    $Failure = $null
    $RollbackFailure = $null
    $TargetBefore = $null
    $TargetAfter = $null
    $MigrationMutex = Enter-WindowsDeploymentMutex `
        -ProjectName $TargetProject
    try {
        try {
            $TargetBefore = Get-WindowsCurrentDataVersions `
                -ComposeBaseArguments $ComposeBaseArguments
            $RollbackPath = New-WindowsPortableDataExport `
                -RepoRoot $RepoRoot `
                -ComposeBaseArguments $ComposeBaseArguments `
                -ExportDirectory $RollbackExportDirectory
            $TargetAfter = Invoke-WindowsPortableDataImportInternal `
                -ComposeBaseArguments $ComposeBaseArguments `
                -ExportPath ([System.IO.Path]::GetFullPath($ExportPath)) `
                -Manifest $SourceManifest
        }
        catch {
            $Failure = $_
            if (-not [string]::IsNullOrWhiteSpace($RollbackPath)) {
                try {
                    $RollbackManifest = Test-WindowsPortableDataExport `
                        -ExportPath $RollbackPath
                    $null = Invoke-WindowsPortableDataImportInternal `
                        -ComposeBaseArguments $ComposeBaseArguments `
                        -ExportPath $RollbackPath `
                        -Manifest $RollbackManifest `
                        -SkipVersionCheck
                }
                catch {
                    $RollbackFailure = $_
                }
            }
        }
    }
    finally {
        Exit-WindowsDeploymentMutex -Mutex $MigrationMutex
    }

    $CompletedAt = [System.DateTimeOffset]::UtcNow
    $Status = if ($null -eq $Failure) {
        "succeeded"
    }
    elseif ($null -eq $RollbackFailure) {
        "failed-rolled-back"
    }
    else {
        "failed-rollback-failed"
    }
    $Payload = [pscustomobject][ordered]@{
        action = "redis-opensearch-migration"
        mode = $Mode
        migration_id = [Guid]::NewGuid().ToString("N")
        status = $Status
        started_at_utc = $StartedAt.ToString("o")
        completed_at_utc = $CompletedAt.ToString("o")
        duration_seconds = [Math]::Round(
            ($CompletedAt - $StartedAt).TotalSeconds,
            3
        )
        source_export_path = [System.IO.Path]::GetFullPath($ExportPath)
        source_export_id = [string]$SourceManifest.export_id
        source_project = [string]$SourceManifest.source_project
        source_redis_version = [string]$SourceManifest.redis.server_version
        source_opensearch_version = (
            [string]$SourceManifest.opensearch.server_version
        )
        target_project = $TargetProject
        target_before = $TargetBefore
        target_after = $TargetAfter
        rollback_export_path = $RollbackPath
        rollback_status = if ($null -eq $Failure) {
            "not-required"
        }
        elseif ($null -eq $RollbackFailure) {
            "succeeded"
        }
        else {
            "failed"
        }
        error = if ($null -eq $Failure) {
            ""
        }
        else {
            "$($Failure.Exception.GetType().Name): $($Failure.Exception.Message)"
        }
        rollback_error = if ($null -eq $RollbackFailure) {
            ""
        }
        else {
            (
                "$($RollbackFailure.Exception.GetType().Name): " +
                $RollbackFailure.Exception.Message
            )
        }
    }
    $RecordPath = Write-WindowsGovernanceRecord `
        -RepoRoot $RepoRoot `
        -Directory $RecordDirectory `
        -Prefix "data-migration" `
        -Payload $Payload
    $Payload | Add-Member `
        -NotePropertyName record_path `
        -NotePropertyValue $RecordPath
    if ($null -ne $Failure) {
        if ($null -ne $RollbackFailure) {
            throw (
                "Data migration failed and rollback failed; record: " +
                "$RecordPath. Migration error: $($Failure.Exception.Message). " +
                "Rollback error: $($RollbackFailure.Exception.Message)"
            )
        }
        throw (
            "Data migration failed and was rolled back; record: " +
            "$RecordPath. $($Failure.Exception.Message)"
        )
    }
    return $Payload
}
