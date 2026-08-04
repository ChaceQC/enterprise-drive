[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $Utf8NoBom
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom

$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\.."))
. (Join-Path $RepoRoot "deploy\windows\backup-restore.ps1")
. (Join-Path $RepoRoot "deploy\windows\governance.ps1")
. (Join-Path $RepoRoot "deploy\windows\data-migration.ps1")

$Suffix = [Guid]::NewGuid().ToString("N")
$TempRoot = Join-Path (
    [System.IO.Path]::GetTempPath()
) "enterprise-drive-ops-export-$Suffix"
$ExportRoot = Join-Path $TempRoot "exports"
$ProjectName = "ops-export-$($Suffix.Substring(0, 8))"
$script:OpenSearchScrollCalls = 0
$script:ComposeModel = [pscustomobject][ordered]@{
    name = $ProjectName
    networks = [pscustomobject][ordered]@{
        backend = [pscustomobject][ordered]@{ name = "ops-export-network" }
    }
    volumes = [pscustomobject][ordered]@{}
    services = [pscustomobject][ordered]@{
        api = [pscustomobject][ordered]@{
            image = "api:smoke"
            environment = [pscustomobject][ordered]@{
                DRIVE_OPENSEARCH_INDEX_NAME = "drive_files_v1"
            }
        }
        redis = [pscustomobject][ordered]@{
            image = "redis:smoke"
            environment = [pscustomobject][ordered]@{
                REDIS_PASSWORD = "smoke-password"
            }
        }
        opensearch = [pscustomobject][ordered]@{
            image = "opensearch:smoke"
            environment = [pscustomobject][ordered]@{}
        }
    }
}
try {
    $null = New-Item -ItemType Directory -Path $TempRoot
    Set-WindowsRestrictedAcl -Path $TempRoot -Directory
    $null = New-Item -ItemType Directory -Path $ExportRoot
    Set-WindowsRestrictedAcl -Path $ExportRoot -Directory

    function Get-WindowsComposeModel {
        param([string[]]$ComposeBaseArguments)
        $null = $ComposeBaseArguments
        return $script:ComposeModel
    }
    function Get-WindowsComposeProjectName {
        param([string[]]$ComposeBaseArguments)
        $null = $ComposeBaseArguments
        return $ProjectName
    }
    function Get-WindowsComposeContainers {
        param([string[]]$ComposeBaseArguments)
        $null = $ComposeBaseArguments
        return @(
            [pscustomobject][ordered]@{
                Service = "redis"
                State = "running"
                ID = "redis-container"
            },
            [pscustomobject][ordered]@{
                Service = "opensearch"
                State = "running"
                ID = "opensearch-container"
            }
        )
    }
    function Get-WindowsComposeImageRecord {
        param(
            [object]$ComposeModel,
            [string[]]$ComposeBaseArguments,
            [string]$ServiceName
        )
        $null = $ComposeModel
        $null = $ComposeBaseArguments
        return [pscustomobject][ordered]@{
            service = $ServiceName
            reference = "$ServiceName:smoke"
            id = "sha256:$('a' * 64)"
            repo_digests = @()
        }
    }
    function Get-WindowsModelServiceImage {
        param(
            [object]$ComposeModel,
            [string]$ServiceName
        )
        $null = $ComposeModel
        return "$ServiceName:smoke"
    }
    function Get-WindowsImageInfo {
        param([string]$Image)
        return [pscustomobject][ordered]@{
            reference = $Image
            id = "sha256:$('a' * 64)"
            repo_digests = @()
        }
    }
    function Get-WindowsModelBackendNetwork {
        param([object]$ComposeModel)
        $null = $ComposeModel
        return "ops-export-network"
    }
    function Get-WindowsModelEnvironmentValue {
        param(
            [object]$ComposeModel,
            [string]$ServiceName,
            [string]$Name
        )
        return [string]$ComposeModel.services.$ServiceName.environment.$Name
    }
    function Get-WindowsComposeContainerImageId {
        param([object]$Container)
        $null = $Container
        return "sha256:$('a' * 64)"
    }
    function Get-WindowsBackupHelperContainer {
        param([string[]]$Arguments)
        $null = $Arguments
    }
    function Invoke-WindowsBackupHelperContainer {
        param([string[]]$Arguments)
        $MountArgument = @($Arguments | Where-Object { $_ -like "type=bind,source=*" })
        $Source = ($MountArgument -replace "^type=bind,source=", "").Split(",")[0]
        $RedisPath = Join-Path $Source "redis.rdb"
        [System.IO.File]::WriteAllBytes($RedisPath, [byte[]](1, 2, 3, 4, 5))
        return @()
    }
    function Wait-WindowsComposeServices {
        param(
            [string[]]$ComposeBaseArguments,
            [string[]]$Services,
            [int]$TimeoutSeconds
        )
        $null = $ComposeBaseArguments
        $null = $Services
        $null = $TimeoutSeconds
    }
    function Invoke-WindowsDocker {
        param([string[]]$Arguments)
        if ($Arguments -contains "INFO") {
            if ($Arguments -contains "server") {
                return @("redis_version:7.4.1")
            }
            return @("# Keyspace")
        }
        return @()
    }
    function Invoke-WindowsOpenSearchRequest {
        param(
            [string[]]$ComposeBaseArguments,
            [string]$Method,
            [string]$Path,
            [string]$Body,
            [int[]]$ExpectedStatus = @(200)
        )
        $null = $ComposeBaseArguments
        $null = $Body
        $null = $ExpectedStatus
        switch -Regex ("$Method $Path") {
            "^GET /$" {
                return [pscustomobject][ordered]@{
                    status = 200
                    body = '{"version":{"number":"2.17.1"}}'
                }
            }
            "^GET /drive_files_v1$" {
                return [pscustomobject][ordered]@{
                    status = 200
                    body = '{"drive_files_v1":{"settings":{"index":{"number_of_shards":"1"}},"mappings":{"properties":{"value":{"type":"keyword"}}}}}'
                }
            }
            "^POST /drive_files_v1/_search" {
                $script:OpenSearchScrollCalls++
                return [pscustomobject][ordered]@{
                    status = 200
                    body = '{"_scroll_id":"scroll-1","hits":{"hits":[{"_id":"source","_source":{"value":"exported"}}]}}'
                }
            }
            "^POST /_search/scroll" {
                return [pscustomobject][ordered]@{
                    status = 200
                    body = '{"_scroll_id":"scroll-1","hits":{"hits":[]}}'
                }
            }
            "^DELETE /_search/scroll" {
                return [pscustomobject][ordered]@{
                    status = 200
                    body = '{"succeeded":true}'
                }
            }
            default {
                throw "Unexpected mocked OpenSearch request: $Method $Path"
            }
        }
    }
    function Get-WindowsProjectVersion {
        param([string]$RepoRoot)
        $null = $RepoRoot
        return "0.9.0"
    }
    function Get-WindowsGitCommit {
        param([string]$RepoRoot)
        $null = $RepoRoot
        return ("a" * 40)
    }

    $ExportPath = New-WindowsPortableDataExport `
        -RepoRoot $RepoRoot `
        -ComposeBaseArguments @("compose") `
        -ExportDirectory $ExportRoot
    $Manifest = Test-WindowsPortableDataExport -ExportPath $ExportPath
    if ([string]$Manifest.redis.server_version -ne "7.4.1") {
        throw "Portable export did not record the Redis version."
    }
    if ([int64]$Manifest.opensearch.document_count -ne 1) {
        throw "Portable export did not record the OpenSearch document count."
    }
    Write-Output "Sprint 12 portable export smoke tests passed."
}
finally {
    if (Test-Path -LiteralPath $TempRoot -PathType Container) {
        Remove-Item -LiteralPath $TempRoot -Recurse -Force
    }
}
