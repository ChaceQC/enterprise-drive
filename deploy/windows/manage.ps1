[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("config", "up", "down", "status", "logs")]
    [string]$Action = "status",

    [string]$EnvFile = ".env.windows",

    [string]$Service,

    [ValidateRange(1, 10000)]
    [int]$Tail = 200,

    [switch]$Build,

    [switch]$Volumes,

    [switch]$Quiet
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $Utf8NoBom
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom
$env:PYTHONUTF8 = "1"

$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$ComposeFile = Join-Path $RepoRoot "compose.windows.yml"
$ExampleEnvFile = Join-Path $RepoRoot ".env.windows.example"

if (-not [System.IO.Path]::IsPathRooted($EnvFile)) {
    $EnvFile = Join-Path $RepoRoot $EnvFile
}
$EnvFile = [System.IO.Path]::GetFullPath($EnvFile)

if (-not (Test-Path -LiteralPath $ComposeFile -PathType Leaf)) {
    throw "Compose file does not exist: $ComposeFile"
}

if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) {
    if ($Action -eq "config" -and (Test-Path -LiteralPath $ExampleEnvFile -PathType Leaf)) {
        $EnvFile = $ExampleEnvFile
    }
    else {
        throw "Environment file does not exist: $EnvFile. Copy .env.windows.example to .env.windows and replace the example secrets."
    }
}

$null = Get-Command docker -ErrorAction Stop

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

Push-Location $RepoRoot
try {
    switch ($Action) {
        "config" {
            $Arguments = @("config")
            if ($Quiet) {
                $Arguments += "--quiet"
            }
            Invoke-Compose -Arguments $Arguments
        }
        "up" {
            Assert-DockerEngine
            $Arguments = @("up", "--detach", "--remove-orphans")
            if ($Build) {
                $Arguments += "--build"
            }
            Invoke-Compose -Arguments $Arguments
            Invoke-Compose -Arguments @("ps", "--all")
        }
        "down" {
            Assert-DockerEngine
            $Arguments = @("down", "--remove-orphans")
            if ($Volumes) {
                $Arguments += "--volumes"
            }
            Invoke-Compose -Arguments $Arguments
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
    }
}
finally {
    Pop-Location
}
