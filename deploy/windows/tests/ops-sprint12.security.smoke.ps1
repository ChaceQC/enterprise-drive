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
. $SubjectPath

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

        [Parameter(Mandatory = $true)]
        [string]$MessagePattern
    )

    $Failure = $null
    try {
        $null = & $Action
    }
    catch {
        $Failure = $_
    }
    if ($null -eq $Failure) {
        throw "Expected the action to fail."
    }
    if ($Failure.Exception.Message -notlike $MessagePattern) {
        throw (
            "Failure did not match '$MessagePattern': " +
            $Failure.Exception.Message
        )
    }
}

$Suffix = [Guid]::NewGuid().ToString("N")
$TestRoot = Join-Path (
    [System.IO.Path]::GetTempPath()
) "enterprise-drive-ops-security-$Suffix"
$SigningCertificate = $null
$EncryptionCertificate = $null
$PayloadResolution = $null
try {
    $null = New-Item -ItemType Directory -Path $TestRoot
    Set-WindowsRestrictedAcl -Path $TestRoot -Directory
    foreach ($DirectoryName in @("postgres", "volumes", "config", "secrets")) {
        $null = New-Item `
            -ItemType Directory `
            -Path (Join-Path $TestRoot $DirectoryName) `
            -Force
    }
    [System.IO.File]::WriteAllBytes(
        (Join-Path $TestRoot "postgres\postgres.dump"),
        [byte[]](0, 1, 2, 3, 254, 255)
    )
    Write-WindowsUtf8File `
        -Path (Join-Path $TestRoot "volumes\redis-data.tar.gz") `
        -Content "redis-$Suffix"
    Write-WindowsUtf8File `
        -Path (Join-Path $TestRoot "config\compose.windows.yml") `
        -Content "name: smoke-$Suffix`n"
    Write-WindowsUtf8File `
        -Path (Join-Path $TestRoot "secrets\environment.cms") `
        -Content "cms-$Suffix"

    $PayloadArtifacts = @()
    foreach (
        $File in @(
            Get-ChildItem -LiteralPath $TestRoot -Recurse -File |
                Sort-Object FullName
        )
    ) {
        $PayloadArtifacts += [pscustomobject][ordered]@{
            path = Get-WindowsRelativeArtifactPath `
                -Root $TestRoot `
                -Path $File.FullName
            size_bytes = [int64]$File.Length
            sha256 = Get-WindowsSha256 -Path $File.FullName
        }
    }

    $SigningCertificate = New-SelfSignedCertificate `
        -Subject "CN=Enterprise Drive OPS Signing $Suffix" `
        -Type CodeSigningCert `
        -CertStoreLocation "Cert:\CurrentUser\My" `
        -KeyAlgorithm RSA `
        -KeyLength 2048 `
        -NotAfter (Get-Date).AddHours(1)
    $EncryptionCertificate = New-SelfSignedCertificate `
        -Subject "CN=Enterprise Drive OPS Encryption $Suffix" `
        -Type DocumentEncryptionCert `
        -CertStoreLocation "Cert:\CurrentUser\My" `
        -KeyAlgorithm RSA `
        -KeyLength 2048 `
        -NotAfter (Get-Date).AddHours(1)

    $PackageEncryption = New-WindowsEncryptedBackupPackage `
        -StagingRoot $TestRoot `
        -CertificateThumbprint $EncryptionCertificate.Thumbprint `
        -PayloadDirectories @("postgres", "volumes", "config", "secrets")
    Assert-SmokeEqual `
        -Expected $true `
        -Actual ([bool]$PackageEncryption.included) `
        -Message "Full-package encryption was not enabled."
    foreach ($PlaintextDirectory in @("postgres", "volumes", "config", "secrets")) {
        Assert-SmokeEqual `
            -Expected $false `
            -Actual (
                Test-Path -LiteralPath (Join-Path $TestRoot $PlaintextDirectory)
            ) `
            -Message "Plaintext backup payload remains after encryption."
    }

    $SigningMetadata = [ordered]@{
        included = $true
        protection = "cms-detached"
        digest_algorithm = "sha256"
        signed_artifact = "manifest.json"
        signature_path = "manifest.p7s"
        certificate_thumbprint = $SigningCertificate.Thumbprint.ToUpperInvariant()
        certificate_subject = [string]$SigningCertificate.Subject
        certificate_not_after_utc = (
            $SigningCertificate.NotAfter.ToUniversalTime().ToString("o")
        )
    }
    $Manifest = [ordered]@{
        format_version = 2
        source_authentication = $SigningMetadata
        package_encryption = $PackageEncryption
        artifacts = $PayloadArtifacts
    }
    $ManifestPath = Join-Path $TestRoot "manifest.json"
    Write-WindowsUtf8File `
        -Path $ManifestPath `
        -Content (($Manifest | ConvertTo-Json -Depth 12) + "`n")
    $null = New-WindowsManifestSignature `
        -ManifestPath $ManifestPath `
        -SignaturePath (Join-Path $TestRoot "manifest.p7s") `
        -CertificateThumbprint $SigningCertificate.Thumbprint
    $ManifestObject = Get-WindowsBackupSecurityJson -Path $ManifestPath
    Test-WindowsManifestSignature `
        -BackupRoot $TestRoot `
        -Manifest $ManifestObject

    $PayloadResolution = Resolve-WindowsBackupPayload `
        -BackupRoot $TestRoot `
        -Manifest $ManifestObject
    Assert-SmokeEqual `
        -Expected $true `
        -Actual ([bool]$PayloadResolution.encrypted) `
        -Message "Encrypted payload resolution returned the wrong mode."
    foreach ($Artifact in $PayloadArtifacts) {
        $Path = Resolve-WindowsBackupArtifactPath `
            -BackupRoot ([string]$PayloadResolution.root) `
            -RelativePath ([string]$Artifact.path)
        Assert-SmokeEqual `
            -Expected ([string]$Artifact.sha256) `
            -Actual (Get-WindowsSha256 -Path $Path) `
            -Message "Decrypted payload artifact hash changed."
    }
    Remove-WindowsBackupPayloadResolution -Resolution $PayloadResolution
    $PayloadResolution = $null

    $SignaturePath = Join-Path $TestRoot "manifest.p7s"
    $SignatureBytes = [System.IO.File]::ReadAllBytes($SignaturePath)
    $SignatureBytes[$SignatureBytes.Length - 1] = (
        $SignatureBytes[$SignatureBytes.Length - 1] -bxor 0x01
    )
    [System.IO.File]::WriteAllBytes($SignaturePath, $SignatureBytes)
    Assert-SmokeThrows `
        -Action {
            Test-WindowsManifestSignature `
                -BackupRoot $TestRoot `
                -Manifest $ManifestObject
        } `
        -MessagePattern "*source signature verification failed*"

    Write-Output "Sprint 12 backup security smoke tests passed."
}
finally {
    if ($null -ne $PayloadResolution) {
        Remove-WindowsBackupPayloadResolution -Resolution $PayloadResolution
    }
    foreach ($Certificate in @($SigningCertificate, $EncryptionCertificate)) {
        if ($null -ne $Certificate) {
            Remove-Item `
                -LiteralPath "Cert:\CurrentUser\My\$($Certificate.Thumbprint)" `
                -Force `
                -ErrorAction SilentlyContinue
        }
    }
    if (Test-Path -LiteralPath $TestRoot -PathType Container) {
        Remove-Item -LiteralPath $TestRoot -Recurse -Force
    }
}
