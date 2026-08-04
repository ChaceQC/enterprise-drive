function Initialize-WindowsBackupSecurityAssemblies {
    $SignedCmsType = [System.Management.Automation.PSTypeName]"System.Security.Cryptography.Pkcs.SignedCms"
    if ($null -eq $SignedCmsType.Type) {
        try {
            Add-Type -AssemblyName "System.Security.Cryptography.Pkcs"
        }
        catch {
            Add-Type -AssemblyName "System.Security"
        }
    }
    $ZipArchiveType = [System.Management.Automation.PSTypeName]"System.IO.Compression.ZipArchive"
    if ($null -eq $ZipArchiveType.Type) {
        Add-Type -AssemblyName "System.IO.Compression"
    }
}

function Get-WindowsBackupCertificate {
    param(
        [Parameter(Mandatory = $true)]
        [ValidatePattern("^[A-Fa-f0-9]{40}$")]
        [string]$Thumbprint,

        [switch]$RequirePrivateKey
    )

    $NormalizedThumbprint = $Thumbprint.ToUpperInvariant()
    $Certificate = Get-ChildItem -LiteralPath "Cert:\CurrentUser\My" |
        Where-Object {
            $_.Thumbprint.ToUpperInvariant() -eq $NormalizedThumbprint
        } |
        Select-Object -First 1
    if ($null -eq $Certificate) {
        throw "Backup certificate was not found: $NormalizedThumbprint"
    }
    if ($Certificate.NotBefore -gt (Get-Date)) {
        throw "Backup certificate is not valid yet: $NormalizedThumbprint"
    }
    if ($Certificate.NotAfter -le (Get-Date)) {
        throw "Backup certificate has expired: $NormalizedThumbprint"
    }
    if ($RequirePrivateKey -and -not $Certificate.HasPrivateKey) {
        throw "Backup certificate does not contain a private key: $NormalizedThumbprint"
    }
    return $Certificate
}

function Get-WindowsCertificateRsaPublicKey {
    param(
        [Parameter(Mandatory = $true)]
        [System.Security.Cryptography.X509Certificates.X509Certificate2]$Certificate
    )

    $Rsa = [System.Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPublicKey(
        $Certificate
    )
    if ($null -eq $Rsa) {
        throw "Backup certificate does not contain an RSA public key."
    }
    return $Rsa
}

function Get-WindowsCertificateRsaPrivateKey {
    param(
        [Parameter(Mandatory = $true)]
        [System.Security.Cryptography.X509Certificates.X509Certificate2]$Certificate
    )

    $Rsa = [System.Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPrivateKey(
        $Certificate
    )
    if ($null -eq $Rsa) {
        throw "Backup certificate does not contain an RSA private key."
    }
    return $Rsa
}

function New-WindowsManifestSignature {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ManifestPath,

        [Parameter(Mandatory = $true)]
        [string]$SignaturePath,

        [Parameter(Mandatory = $true)]
        [ValidatePattern("^[A-Fa-f0-9]{40}$")]
        [string]$CertificateThumbprint
    )

    Initialize-WindowsBackupSecurityAssemblies
    $Certificate = Get-WindowsBackupCertificate `
        -Thumbprint $CertificateThumbprint `
        -RequirePrivateKey
    $ManifestBytes = [System.IO.File]::ReadAllBytes($ManifestPath)
    $ContentInfo = New-Object `
        -TypeName "System.Security.Cryptography.Pkcs.ContentInfo" `
        -ArgumentList (, $ManifestBytes)
    $SignedCms = New-Object `
        -TypeName "System.Security.Cryptography.Pkcs.SignedCms" `
        -ArgumentList @($ContentInfo, $true)
    $Signer = New-Object `
        -TypeName "System.Security.Cryptography.Pkcs.CmsSigner" `
        -ArgumentList (, $Certificate)
    $Signer.IncludeOption = (
        [System.Security.Cryptography.X509Certificates.X509IncludeOption]::EndCertOnly
    )
    $Signer.DigestAlgorithm = New-Object `
        System.Security.Cryptography.Oid("2.16.840.1.101.3.4.2.1")
    $SignedCms.ComputeSignature($Signer)
    [System.IO.File]::WriteAllBytes($SignaturePath, $SignedCms.Encode())

    return [ordered]@{
        included = $true
        protection = "cms-detached"
        digest_algorithm = "sha256"
        signed_artifact = "manifest.json"
        signature_path = "manifest.p7s"
        certificate_thumbprint = $Certificate.Thumbprint.ToUpperInvariant()
        certificate_subject = [string]$Certificate.Subject
        certificate_not_after_utc = $Certificate.NotAfter.ToUniversalTime().ToString("o")
    }
}

function Test-WindowsManifestSignature {
    param(
        [Parameter(Mandatory = $true)]
        [string]$BackupRoot,

        [Parameter(Mandatory = $true)]
        [object]$Manifest
    )

    $AuthenticationProperty = $Manifest.PSObject.Properties["source_authentication"]
    if ($null -eq $AuthenticationProperty) {
        if ([int64]$Manifest.format_version -eq 1) {
            return
        }
        throw "Backup manifest is missing 'source_authentication'."
    }
    $Authentication = $AuthenticationProperty.Value
    foreach ($PropertyName in @(
        "included",
        "protection",
        "digest_algorithm",
        "signed_artifact",
        "signature_path",
        "certificate_thumbprint",
        "certificate_subject",
        "certificate_not_after_utc"
    )) {
        if ($null -eq $Authentication.PSObject.Properties[$PropertyName]) {
            throw "Backup source authentication is missing '$PropertyName'."
        }
    }
    if ($Authentication.included -isnot [bool]) {
        throw "Backup source authentication included flag must be Boolean."
    }
    if (-not [bool]$Authentication.included) {
        if (
            [string]$Authentication.protection -ne "skipped" -or
            -not [string]::IsNullOrWhiteSpace(
                [string]$Authentication.certificate_thumbprint
            ) -or
            -not [string]::IsNullOrWhiteSpace(
                [string]$Authentication.signature_path
            )
        ) {
            throw "Skipped backup source authentication metadata is invalid."
        }
        return
    }
    if (
        [string]$Authentication.protection -ne "cms-detached" -or
        [string]$Authentication.digest_algorithm -ne "sha256" -or
        [string]$Authentication.signed_artifact -ne "manifest.json" -or
        [string]$Authentication.signature_path -ne "manifest.p7s" -or
        [string]$Authentication.certificate_thumbprint -notmatch
        "^[A-Fa-f0-9]{40}$"
    ) {
        throw "Backup source authentication metadata is invalid."
    }

    Initialize-WindowsBackupSecurityAssemblies
    $ManifestPath = Join-Path $BackupRoot "manifest.json"
    $SignaturePath = Resolve-WindowsBackupArtifactPath `
        -BackupRoot $BackupRoot `
        -RelativePath ([string]$Authentication.signature_path)
    if (-not (Test-Path -LiteralPath $SignaturePath -PathType Leaf)) {
        throw "Backup manifest signature is missing: $SignaturePath"
    }
    Assert-WindowsNoReparsePoint `
        -Path $SignaturePath `
        -Label "Backup manifest signature"
    $ManifestBytes = [System.IO.File]::ReadAllBytes($ManifestPath)
    $ContentInfo = New-Object `
        -TypeName "System.Security.Cryptography.Pkcs.ContentInfo" `
        -ArgumentList (, $ManifestBytes)
    $SignedCms = New-Object `
        -TypeName "System.Security.Cryptography.Pkcs.SignedCms" `
        -ArgumentList @($ContentInfo, $true)
    try {
        $SignedCms.Decode([System.IO.File]::ReadAllBytes($SignaturePath))
        $SignedCms.CheckSignature($true)
    }
    catch {
        throw "Backup manifest source signature verification failed: $($_.Exception.Message)"
    }
    if ($SignedCms.SignerInfos.Count -ne 1) {
        throw "Backup manifest signature must contain exactly one signer."
    }
    $SignerCertificate = $SignedCms.SignerInfos[0].Certificate
    if ($null -eq $SignerCertificate) {
        throw "Backup manifest signature does not contain a signer certificate."
    }
    if (
        $SignerCertificate.Thumbprint.ToUpperInvariant() -ne
        ([string]$Authentication.certificate_thumbprint).ToUpperInvariant()
    ) {
        throw "Backup manifest signer thumbprint does not match metadata."
    }
    if ([string]$SignerCertificate.Subject -ne [string]$Authentication.certificate_subject) {
        throw "Backup manifest signer subject does not match metadata."
    }
    if (
        $SignerCertificate.NotAfter.ToUniversalTime().ToString("o") -ne
        [string]$Authentication.certificate_not_after_utc
    ) {
        throw "Backup manifest signer validity does not match metadata."
    }
    if (
        [string]$SignedCms.SignerInfos[0].DigestAlgorithm.Value -ne
        "2.16.840.1.101.3.4.2.1"
    ) {
        throw "Backup manifest signature digest algorithm is not SHA-256."
    }
}

function New-WindowsPayloadZip {
    param(
        [Parameter(Mandatory = $true)]
        [string]$StagingRoot,

        [Parameter(Mandatory = $true)]
        [string]$ZipPath,

        [Parameter(Mandatory = $true)]
        [string[]]$PayloadDirectories
    )

    Initialize-WindowsBackupSecurityAssemblies
    $ZipStream = [System.IO.File]::Open(
        $ZipPath,
        [System.IO.FileMode]::CreateNew,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
    try {
        $Archive = New-Object `
            -TypeName "System.IO.Compression.ZipArchive" `
            -ArgumentList @(
                $ZipStream,
                [System.IO.Compression.ZipArchiveMode]::Create,
                $true,
                [System.Text.Encoding]::UTF8
            )
        try {
            foreach ($DirectoryName in $PayloadDirectories) {
                $DirectoryPath = Join-Path $StagingRoot $DirectoryName
                if (-not (Test-Path -LiteralPath $DirectoryPath -PathType Container)) {
                    throw "Backup payload directory is missing: $DirectoryName"
                }
                Assert-WindowsNoReparsePoint `
                    -Path $DirectoryPath `
                    -Label "Backup package payload"
                foreach (
                    $File in @(
                        Get-ChildItem `
                            -LiteralPath $DirectoryPath `
                            -Recurse `
                            -File `
                            -Force |
                            Sort-Object FullName
                    )
                ) {
                    Assert-WindowsNoReparsePoint `
                        -Path $File.FullName `
                        -Label "Backup package payload file"
                    $RelativePath = Get-WindowsRelativeArtifactPath `
                        -Root $StagingRoot `
                        -Path $File.FullName
                    $EntryName = $RelativePath.Replace("\", "/")
                    $Entry = $Archive.CreateEntry(
                        $EntryName,
                        [System.IO.Compression.CompressionLevel]::Optimal
                    )
                    $Entry.LastWriteTime = New-Object System.DateTimeOffset(
                        1980,
                        1,
                        1,
                        0,
                        0,
                        0,
                        [System.TimeSpan]::Zero
                    )
                    $SourceStream = [System.IO.File]::OpenRead($File.FullName)
                    try {
                        $EntryStream = $Entry.Open()
                        try {
                            $SourceStream.CopyTo($EntryStream)
                        }
                        finally {
                            $EntryStream.Dispose()
                        }
                    }
                    finally {
                        $SourceStream.Dispose()
                    }
                }
            }
        }
        finally {
            $Archive.Dispose()
        }
    }
    finally {
        $ZipStream.Dispose()
    }
}

function Get-WindowsHmacSha256Hex {
    param(
        [Parameter(Mandatory = $true)]
        [byte[]]$Key,

        [Parameter(Mandatory = $true)]
        [byte[]]$Prefix,

        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $Hmac = New-Object System.Security.Cryptography.HMACSHA256(, $Key)
    try {
        if ($Prefix.Length -gt 0) {
            $null = $Hmac.TransformBlock(
                $Prefix,
                0,
                $Prefix.Length,
                $Prefix,
                0
            )
        }
        $Stream = [System.IO.File]::OpenRead($Path)
        try {
            $Buffer = New-Object byte[] 1048576
            while (($Read = $Stream.Read($Buffer, 0, $Buffer.Length)) -gt 0) {
                $null = $Hmac.TransformBlock(
                    $Buffer,
                    0,
                    $Read,
                    $Buffer,
                    0
                )
            }
        }
        finally {
            $Stream.Dispose()
        }
        $null = $Hmac.TransformFinalBlock((New-Object byte[] 0), 0, 0)
        return -join ($Hmac.Hash | ForEach-Object { $_.ToString("x2") })
    }
    finally {
        $Hmac.Dispose()
    }
}

function New-WindowsEncryptedBackupPackage {
    param(
        [Parameter(Mandatory = $true)]
        [string]$StagingRoot,

        [Parameter(Mandatory = $true)]
        [ValidatePattern("^[A-Fa-f0-9]{40}$")]
        [string]$CertificateThumbprint,

        [Parameter(Mandatory = $true)]
        [string[]]$PayloadDirectories
    )

    Initialize-WindowsBackupSecurityAssemblies
    $Certificate = Get-WindowsBackupCertificate `
        -Thumbprint $CertificateThumbprint
    $PackageDirectory = Join-Path $StagingRoot "package"
    $null = New-Item -ItemType Directory -Path $PackageDirectory -Force
    $ZipPath = Join-Path $PackageDirectory ".payload.zip.partial"
    $PayloadPath = Join-Path $PackageDirectory "payload.enc"
    $EnvelopePath = Join-Path $PackageDirectory "envelope.json"
    New-WindowsPayloadZip `
        -StagingRoot $StagingRoot `
        -ZipPath $ZipPath `
        -PayloadDirectories $PayloadDirectories

    $PlaintextSize = [int64](Get-Item -LiteralPath $ZipPath).Length
    $PlaintextSha256 = Get-WindowsSha256 -Path $ZipPath
    $EncryptionKey = New-Object byte[] 32
    $HmacKey = New-Object byte[] 32
    $Aes = [System.Security.Cryptography.Aes]::Create()
    $Random = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $Random.GetBytes($EncryptionKey)
        $Random.GetBytes($HmacKey)
        $Aes.KeySize = 256
        $Aes.BlockSize = 128
        $Aes.Mode = [System.Security.Cryptography.CipherMode]::CBC
        $Aes.Padding = [System.Security.Cryptography.PaddingMode]::PKCS7
        $Aes.GenerateIV()
        $Aes.Key = $EncryptionKey

        $InputStream = [System.IO.File]::OpenRead($ZipPath)
        $OutputStream = [System.IO.File]::Open(
            $PayloadPath,
            [System.IO.FileMode]::CreateNew,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::None
        )
        try {
            $CryptoStream = New-Object `
                -TypeName "System.Security.Cryptography.CryptoStream" `
                -ArgumentList @(
                    $OutputStream,
                    $Aes.CreateEncryptor(),
                    [System.Security.Cryptography.CryptoStreamMode]::Write
                )
            try {
                $InputStream.CopyTo($CryptoStream)
                $CryptoStream.FlushFinalBlock()
            }
            finally {
                $CryptoStream.Dispose()
            }
        }
        finally {
            $InputStream.Dispose()
            $OutputStream.Dispose()
        }

        $KeyMaterial = New-Object byte[] 64
        [System.Buffer]::BlockCopy($EncryptionKey, 0, $KeyMaterial, 0, 32)
        [System.Buffer]::BlockCopy($HmacKey, 0, $KeyMaterial, 32, 32)
        $Rsa = Get-WindowsCertificateRsaPublicKey -Certificate $Certificate
        try {
            $WrappedKey = $Rsa.Encrypt(
                $KeyMaterial,
                [System.Security.Cryptography.RSAEncryptionPadding]::OaepSHA256
            )
        }
        finally {
            $Rsa.Dispose()
        }
        $HmacHex = Get-WindowsHmacSha256Hex `
            -Key $HmacKey `
            -Prefix $Aes.IV `
            -Path $PayloadPath
        $Envelope = [ordered]@{
            format_version = 1
            content_algorithm = "aes-256-cbc"
            authentication_algorithm = "hmac-sha256"
            key_wrap_algorithm = "rsa-oaep-sha256"
            certificate_thumbprint = $Certificate.Thumbprint.ToUpperInvariant()
            iv_base64 = [System.Convert]::ToBase64String($Aes.IV)
            wrapped_key_base64 = [System.Convert]::ToBase64String($WrappedKey)
            hmac_sha256 = $HmacHex
            plaintext_size_bytes = $PlaintextSize
            plaintext_sha256 = $PlaintextSha256
            ciphertext_size_bytes = [int64](Get-Item -LiteralPath $PayloadPath).Length
            ciphertext_sha256 = Get-WindowsSha256 -Path $PayloadPath
        }
        Write-WindowsUtf8File `
            -Path $EnvelopePath `
            -Content (($Envelope | ConvertTo-Json -Depth 6) + "`n")
    }
    finally {
        $Random.Dispose()
        $Aes.Dispose()
        [System.Array]::Clear($EncryptionKey, 0, $EncryptionKey.Length)
        [System.Array]::Clear($HmacKey, 0, $HmacKey.Length)
        if (Test-Path -LiteralPath $ZipPath -PathType Leaf) {
            Remove-Item -LiteralPath $ZipPath -Force
        }
    }

    foreach ($DirectoryName in $PayloadDirectories) {
        $DirectoryPath = [System.IO.Path]::GetFullPath(
            (Join-Path $StagingRoot $DirectoryName)
        )
        if (
            -not (Test-WindowsPathWithin -Parent $StagingRoot -Candidate $DirectoryPath)
        ) {
            throw "Refusing to remove an encrypted payload directory outside staging."
        }
        Assert-WindowsNoReparsePoint `
            -Path $DirectoryPath `
            -Label "Encrypted backup plaintext cleanup"
        Remove-Item -LiteralPath $DirectoryPath -Recurse -Force
    }

    return [ordered]@{
        included = $true
        protection = "aes-256-cbc-hmac-sha256+rsa-oaep-sha256"
        certificate_thumbprint = $Certificate.Thumbprint.ToUpperInvariant()
        certificate_subject = [string]$Certificate.Subject
        payload_path = "package/payload.enc"
        payload_size_bytes = [int64](Get-Item -LiteralPath $PayloadPath).Length
        payload_sha256 = Get-WindowsSha256 -Path $PayloadPath
        envelope_path = "package/envelope.json"
        envelope_sha256 = Get-WindowsSha256 -Path $EnvelopePath
    }
}

function Get-WindowsBackupSecurityJson {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $StrictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)
    $Text = [System.IO.File]::ReadAllText($Path, $StrictUtf8)
    return $Text | ConvertFrom-Json -ErrorAction Stop
}

function Expand-WindowsEncryptedBackupPackage {
    param(
        [Parameter(Mandatory = $true)]
        [string]$BackupRoot,

        [Parameter(Mandatory = $true)]
        [object]$PackageEncryption
    )

    foreach ($PropertyName in @(
        "included",
        "protection",
        "certificate_thumbprint",
        "certificate_subject",
        "payload_path",
        "payload_size_bytes",
        "payload_sha256",
        "envelope_path",
        "envelope_sha256"
    )) {
        if ($null -eq $PackageEncryption.PSObject.Properties[$PropertyName]) {
            throw "Backup package encryption is missing '$PropertyName'."
        }
    }
    if (
        [string]$PackageEncryption.protection -ne
        "aes-256-cbc-hmac-sha256+rsa-oaep-sha256"
    ) {
        throw "Backup package encryption protection is unsupported."
    }
    $PayloadPath = Resolve-WindowsBackupArtifactPath `
        -BackupRoot $BackupRoot `
        -RelativePath ([string]$PackageEncryption.payload_path)
    $EnvelopePath = Resolve-WindowsBackupArtifactPath `
        -BackupRoot $BackupRoot `
        -RelativePath ([string]$PackageEncryption.envelope_path)
    foreach ($Path in @($PayloadPath, $EnvelopePath)) {
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
            throw "Encrypted backup package artifact is missing: $Path"
        }
        Assert-WindowsNoReparsePoint `
            -Path $Path `
            -Label "Encrypted backup package artifact"
    }
    if (
        [int64](Get-Item -LiteralPath $PayloadPath).Length -ne
        [int64]$PackageEncryption.payload_size_bytes -or
        (Get-WindowsSha256 -Path $PayloadPath) -ne
        [string]$PackageEncryption.payload_sha256
    ) {
        throw "Encrypted backup payload metadata verification failed."
    }
    if (
        (Get-WindowsSha256 -Path $EnvelopePath) -ne
        [string]$PackageEncryption.envelope_sha256
    ) {
        throw "Encrypted backup envelope metadata verification failed."
    }

    $Envelope = Get-WindowsBackupSecurityJson -Path $EnvelopePath
    foreach ($PropertyName in @(
        "format_version",
        "content_algorithm",
        "authentication_algorithm",
        "key_wrap_algorithm",
        "certificate_thumbprint",
        "iv_base64",
        "wrapped_key_base64",
        "hmac_sha256",
        "plaintext_size_bytes",
        "plaintext_sha256",
        "ciphertext_size_bytes",
        "ciphertext_sha256"
    )) {
        if ($null -eq $Envelope.PSObject.Properties[$PropertyName]) {
            throw "Encrypted backup envelope is missing '$PropertyName'."
        }
    }
    if (
        [int64]$Envelope.format_version -ne 1 -or
        [string]$Envelope.content_algorithm -ne "aes-256-cbc" -or
        [string]$Envelope.authentication_algorithm -ne "hmac-sha256" -or
        [string]$Envelope.key_wrap_algorithm -ne "rsa-oaep-sha256" -or
        [string]$Envelope.certificate_thumbprint -ne
        [string]$PackageEncryption.certificate_thumbprint -or
        [string]$Envelope.ciphertext_sha256 -ne
        [string]$PackageEncryption.payload_sha256 -or
        [int64]$Envelope.ciphertext_size_bytes -ne
        [int64]$PackageEncryption.payload_size_bytes
    ) {
        throw "Encrypted backup envelope metadata does not match the manifest."
    }

    $Certificate = Get-WindowsBackupCertificate `
        -Thumbprint ([string]$Envelope.certificate_thumbprint) `
        -RequirePrivateKey
    $Rsa = Get-WindowsCertificateRsaPrivateKey -Certificate $Certificate
    try {
        $KeyMaterial = $Rsa.Decrypt(
            [System.Convert]::FromBase64String(
                [string]$Envelope.wrapped_key_base64
            ),
            [System.Security.Cryptography.RSAEncryptionPadding]::OaepSHA256
        )
    }
    finally {
        $Rsa.Dispose()
    }
    if ($KeyMaterial.Length -ne 64) {
        throw "Encrypted backup package key material has an invalid length."
    }
    $EncryptionKey = New-Object byte[] 32
    $HmacKey = New-Object byte[] 32
    [System.Buffer]::BlockCopy($KeyMaterial, 0, $EncryptionKey, 0, 32)
    [System.Buffer]::BlockCopy($KeyMaterial, 32, $HmacKey, 0, 32)
    [System.Array]::Clear($KeyMaterial, 0, $KeyMaterial.Length)
    $Iv = [System.Convert]::FromBase64String([string]$Envelope.iv_base64)
    if ($Iv.Length -ne 16) {
        throw "Encrypted backup package IV has an invalid length."
    }
    $ActualHmac = Get-WindowsHmacSha256Hex `
        -Key $HmacKey `
        -Prefix $Iv `
        -Path $PayloadPath
    if ($ActualHmac -ne [string]$Envelope.hmac_sha256) {
        throw "Encrypted backup package HMAC verification failed."
    }

    $TemporaryRoot = Join-Path (
        [System.IO.Path]::GetTempPath()
    ) (
        "enterprise-drive-backup-payload-" +
        [Guid]::NewGuid().ToString("N")
    )
    $ZipPath = Join-Path $TemporaryRoot "payload.zip"
    $PayloadRoot = Join-Path $TemporaryRoot "payload"
    $null = New-Item -ItemType Directory -Path $TemporaryRoot
    Set-WindowsRestrictedAcl -Path $TemporaryRoot -Directory
    $null = New-Item -ItemType Directory -Path $PayloadRoot
    try {
        $Aes = [System.Security.Cryptography.Aes]::Create()
        try {
            $Aes.KeySize = 256
            $Aes.BlockSize = 128
            $Aes.Mode = [System.Security.Cryptography.CipherMode]::CBC
            $Aes.Padding = [System.Security.Cryptography.PaddingMode]::PKCS7
            $Aes.Key = $EncryptionKey
            $Aes.IV = $Iv
            $InputStream = [System.IO.File]::OpenRead($PayloadPath)
            $OutputStream = [System.IO.File]::Open(
                $ZipPath,
                [System.IO.FileMode]::CreateNew,
                [System.IO.FileAccess]::Write,
                [System.IO.FileShare]::None
            )
            try {
                $CryptoStream = New-Object `
                    -TypeName "System.Security.Cryptography.CryptoStream" `
                    -ArgumentList @(
                        $InputStream,
                        $Aes.CreateDecryptor(),
                        [System.Security.Cryptography.CryptoStreamMode]::Read
                    )
                try {
                    $CryptoStream.CopyTo($OutputStream)
                }
                finally {
                    $CryptoStream.Dispose()
                }
            }
            finally {
                $InputStream.Dispose()
                $OutputStream.Dispose()
            }
        }
        finally {
            $Aes.Dispose()
        }
        if (
            [int64](Get-Item -LiteralPath $ZipPath).Length -ne
            [int64]$Envelope.plaintext_size_bytes -or
            (Get-WindowsSha256 -Path $ZipPath) -ne
            [string]$Envelope.plaintext_sha256
        ) {
            throw "Decrypted backup package verification failed."
        }

        Initialize-WindowsBackupSecurityAssemblies
        $ZipStream = [System.IO.File]::OpenRead($ZipPath)
        try {
            $Archive = New-Object `
                -TypeName "System.IO.Compression.ZipArchive" `
                -ArgumentList @(
                    $ZipStream,
                    [System.IO.Compression.ZipArchiveMode]::Read,
                    $true,
                    [System.Text.Encoding]::UTF8
                )
            try {
                foreach ($Entry in $Archive.Entries) {
                    if ([string]::IsNullOrWhiteSpace([string]$Entry.Name)) {
                        continue
                    }
                    $RelativePath = [string]$Entry.FullName
                    $DestinationPath = Resolve-WindowsBackupArtifactPath `
                        -BackupRoot $PayloadRoot `
                        -RelativePath $RelativePath
                    $Parent = [System.IO.Path]::GetDirectoryName($DestinationPath)
                    if (-not (Test-Path -LiteralPath $Parent -PathType Container)) {
                        $null = New-Item -ItemType Directory -Path $Parent -Force
                    }
                    if (Test-Path -LiteralPath $DestinationPath) {
                        throw "Encrypted backup package contains a duplicate path: $RelativePath"
                    }
                    $EntryStream = $Entry.Open()
                    try {
                        $DestinationStream = [System.IO.File]::Open(
                            $DestinationPath,
                            [System.IO.FileMode]::CreateNew,
                            [System.IO.FileAccess]::Write,
                            [System.IO.FileShare]::None
                        )
                        try {
                            $EntryStream.CopyTo($DestinationStream)
                        }
                        finally {
                            $DestinationStream.Dispose()
                        }
                    }
                    finally {
                        $EntryStream.Dispose()
                    }
                }
            }
            finally {
                $Archive.Dispose()
            }
        }
        finally {
            $ZipStream.Dispose()
        }
        Remove-Item -LiteralPath $ZipPath -Force
        Assert-WindowsRestrictedAcl -Path $TemporaryRoot
        return [pscustomobject][ordered]@{
            root = $PayloadRoot
            cleanup_path = $TemporaryRoot
            encrypted = $true
        }
    }
    catch {
        if (Test-Path -LiteralPath $TemporaryRoot -PathType Container) {
            Remove-Item -LiteralPath $TemporaryRoot -Recurse -Force
        }
        throw
    }
    finally {
        [System.Array]::Clear($EncryptionKey, 0, $EncryptionKey.Length)
        [System.Array]::Clear($HmacKey, 0, $HmacKey.Length)
    }
}

function Resolve-WindowsBackupPayload {
    param(
        [Parameter(Mandatory = $true)]
        [string]$BackupRoot,

        [Parameter(Mandatory = $true)]
        [object]$Manifest
    )

    $EncryptionProperty = $Manifest.PSObject.Properties["package_encryption"]
    if ($null -eq $EncryptionProperty) {
        $FormatProperty = $Manifest.PSObject.Properties["format_version"]
        if (
            $null -eq $FormatProperty -or
            [int64]$FormatProperty.Value -eq 1
        ) {
            return [pscustomobject][ordered]@{
                root = $BackupRoot
                cleanup_path = ""
                encrypted = $false
            }
        }
        throw "Backup manifest is missing 'package_encryption'."
    }
    $Encryption = $EncryptionProperty.Value
    if ($null -eq $Encryption.PSObject.Properties["included"]) {
        throw "Backup package encryption is missing 'included'."
    }
    if ($Encryption.included -isnot [bool]) {
        throw "Backup package encryption included flag must be Boolean."
    }
    if (-not [bool]$Encryption.included) {
        if (
            [string]$Encryption.protection -ne "skipped" -or
            -not [string]::IsNullOrWhiteSpace(
                [string]$Encryption.certificate_thumbprint
            )
        ) {
            throw "Skipped backup package encryption metadata is invalid."
        }
        return [pscustomobject][ordered]@{
            root = $BackupRoot
            cleanup_path = ""
            encrypted = $false
        }
    }
    return Expand-WindowsEncryptedBackupPackage `
        -BackupRoot $BackupRoot `
        -PackageEncryption $Encryption
}

function Remove-WindowsBackupPayloadResolution {
    param(
        [AllowNull()]
        [object]$Resolution
    )

    if (
        $null -eq $Resolution -or
        [string]::IsNullOrWhiteSpace([string]$Resolution.cleanup_path)
    ) {
        return
    }
    $Path = [System.IO.Path]::GetFullPath([string]$Resolution.cleanup_path)
    $Name = [System.IO.Path]::GetFileName($Path)
    if (-not $Name.StartsWith("enterprise-drive-backup-payload-")) {
        throw "Refusing to remove an invalid backup payload path: $Path"
    }
    if (Test-Path -LiteralPath $Path -PathType Container) {
        Assert-WindowsNoReparsePoint `
            -Path $Path `
            -Label "Backup payload cleanup"
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}
