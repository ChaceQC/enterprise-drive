use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{Duration, Instant};

use base64::engine::general_purpose::STANDARD as BASE64;
use base64::Engine;
use chrono::{DateTime, Utc};
use drive_platform::atomic_replace;
use ed25519_dalek::{Signature, Signer, SigningKey, Verifier, VerifyingKey};
use semver::Version;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use thiserror::Error;

pub type Result<T> = std::result::Result<T, UpdateError>;

#[derive(Debug, Error)]
pub enum UpdateError {
    #[error("update HTTP request failed: {0}")]
    Http(#[from] reqwest::Error),
    #[error("update file operation failed: {0}")]
    Io(#[from] std::io::Error),
    #[error("update platform operation failed: {0}")]
    Platform(#[from] drive_platform::PlatformError),
    #[error("update manifest JSON failed: {0}")]
    Json(#[from] serde_json::Error),
    #[error("update version is invalid: {0}")]
    Version(#[from] semver::Error),
    #[error("update signing key or signature is invalid")]
    InvalidSignatureEncoding,
    #[error("update manifest signature verification failed")]
    ManifestSignatureInvalid,
    #[error("update package signature verification failed")]
    PackageSignatureInvalid,
    #[error("update package SHA-256 does not match the signed manifest")]
    PackageHashMismatch,
    #[error("update package Authenticode certificate SHA-256 is invalid")]
    InvalidAuthenticodeCertificateHash,
    #[error("update package Authenticode verification failed with status 0x{0:08x}")]
    AuthenticodeSignatureInvalid(u32),
    #[error("update package Authenticode signer certificate is unavailable")]
    AuthenticodeSignerUnavailable,
    #[error("update package Authenticode signer certificate does not match the signed manifest")]
    AuthenticodeCertificateMismatch,
    #[error("update package Authenticode verification is only available on Windows")]
    AuthenticodeUnsupported,
    #[error("update URL must use HTTPS")]
    InsecureUrl,
    #[error("update manifest target does not match this client")]
    TargetMismatch,
    #[error("update manifest does not include a rollback package")]
    RollbackPackageUnavailable,
    #[error(
        "update rollback package version {actual} does not match the current client version {expected}"
    )]
    RollbackVersionMismatch { expected: String, actual: String },
    #[error("staged update journal is unavailable")]
    JournalUnavailable,
    #[error("update helper arguments are invalid")]
    InvalidWatchdogArguments,
    #[error("update package process failed to start")]
    InstallLaunchFailed,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct UpdatePackage {
    pub version: String,
    pub target: String,
    pub url: String,
    pub sha256: String,
    pub signature: String,
    pub authenticode_certificate_sha256: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct UpdateManifestPayload {
    pub schema_version: u32,
    pub published_at: DateTime<Utc>,
    pub package: UpdatePackage,
    pub rollback_package: Option<UpdatePackage>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SignedUpdateManifest {
    pub payload: UpdateManifestPayload,
    pub signature: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum UpdateStage {
    Verified,
    Installing,
    Healthy,
    Failed,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct UpdateJournal {
    pub current_version: String,
    pub target_version: String,
    pub target_package_path: PathBuf,
    pub rollback_package_path: Option<PathBuf>,
    pub health_marker_path: PathBuf,
    pub stage: UpdateStage,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct StagedUpdate {
    pub version: String,
    pub package_path: PathBuf,
    pub rollback_package_path: Option<PathBuf>,
    pub health_marker_path: PathBuf,
}

#[derive(Clone)]
pub struct UpdateVerifier {
    public_key: VerifyingKey,
}

impl UpdateVerifier {
    pub fn from_base64(public_key: &str) -> Result<Self> {
        let bytes = BASE64
            .decode(public_key.trim())
            .map_err(|_| UpdateError::InvalidSignatureEncoding)?;
        let bytes: [u8; 32] = bytes
            .try_into()
            .map_err(|_| UpdateError::InvalidSignatureEncoding)?;
        let public_key =
            VerifyingKey::from_bytes(&bytes).map_err(|_| UpdateError::InvalidSignatureEncoding)?;
        Ok(Self { public_key })
    }

    pub fn verify_manifest(&self, manifest: &SignedUpdateManifest) -> Result<()> {
        let payload = serde_json::to_vec(&manifest.payload)?;
        let signature = decode_signature(&manifest.signature)?;
        self.public_key
            .verify(&payload, &signature)
            .map_err(|_| UpdateError::ManifestSignatureInvalid)
    }

    pub fn verify_package(&self, package: &UpdatePackage, bytes: &[u8]) -> Result<()> {
        let actual_hash = hex::encode(Sha256::digest(bytes));
        if !actual_hash.eq_ignore_ascii_case(&package.sha256) {
            return Err(UpdateError::PackageHashMismatch);
        }
        let signature = decode_signature(&package.signature)?;
        self.public_key
            .verify(bytes, &signature)
            .map_err(|_| UpdateError::PackageSignatureInvalid)
    }

    pub fn verify_authenticode(&self, package: &UpdatePackage, path: &Path) -> Result<()> {
        verify_authenticode_package(path, &package.authenticode_certificate_sha256)
    }
}

#[derive(Clone)]
pub struct UpdateManager {
    http: reqwest::Client,
    verifier: UpdateVerifier,
    manifest_url: String,
    data_dir: PathBuf,
    current_version: Version,
    expected_target: String,
}

impl UpdateManager {
    pub fn new(
        manifest_url: impl Into<String>,
        data_dir: impl Into<PathBuf>,
        current_version: &str,
        expected_target: impl Into<String>,
        public_key: &str,
    ) -> Result<Self> {
        let manifest_url = manifest_url.into();
        ensure_https(&manifest_url)?;
        Ok(Self {
            http: reqwest::Client::builder()
                .user_agent(concat!(
                    "enterprise-drive-updater/",
                    env!("CARGO_PKG_VERSION")
                ))
                .build()?,
            verifier: UpdateVerifier::from_base64(public_key)?,
            manifest_url,
            data_dir: data_dir.into(),
            current_version: Version::parse(current_version)?,
            expected_target: expected_target.into(),
        })
    }

    pub async fn check_and_stage(&self) -> Result<Option<StagedUpdate>> {
        let manifest = self
            .http
            .get(&self.manifest_url)
            .send()
            .await?
            .error_for_status()?
            .json::<SignedUpdateManifest>()
            .await?;
        self.verifier.verify_manifest(&manifest)?;
        if manifest.payload.package.target != self.expected_target {
            return Err(UpdateError::TargetMismatch);
        }
        let target_version = Version::parse(&manifest.payload.package.version)?;
        if target_version <= self.current_version {
            return Ok(None);
        }
        let rollback_package = manifest
            .payload
            .rollback_package
            .as_ref()
            .ok_or(UpdateError::RollbackPackageUnavailable)?;
        if rollback_package.target != self.expected_target {
            return Err(UpdateError::TargetMismatch);
        }
        let rollback_version = Version::parse(&rollback_package.version)?;
        if rollback_version != self.current_version {
            return Err(UpdateError::RollbackVersionMismatch {
                expected: self.current_version.to_string(),
                actual: rollback_version.to_string(),
            });
        }
        let staging_dir = self
            .data_dir
            .join("updates")
            .join("staging")
            .join(target_version.to_string());
        tokio::fs::create_dir_all(&staging_dir).await?;
        let package_path = staging_dir.join("enterprise-drive-update.exe");
        self.download_and_verify(&manifest.payload.package, &package_path)
            .await?;
        let rollback_path = staging_dir.join("enterprise-drive-rollback.exe");
        self.download_and_verify(rollback_package, &rollback_path)
            .await?;
        let rollback_package_path = Some(rollback_path);
        let health_marker_path = self
            .data_dir
            .join("updates")
            .join("health")
            .join(format!("{target_version}.ok"));
        let journal = UpdateJournal {
            current_version: self.current_version.to_string(),
            target_version: target_version.to_string(),
            target_package_path: package_path.clone(),
            rollback_package_path: rollback_package_path.clone(),
            health_marker_path: health_marker_path.clone(),
            stage: UpdateStage::Verified,
            updated_at: Utc::now(),
        };
        self.write_journal(&journal)?;
        Ok(Some(StagedUpdate {
            version: target_version.to_string(),
            package_path,
            rollback_package_path,
            health_marker_path,
        }))
    }

    pub fn launch_install(&self, staged: &StagedUpdate, current_executable: &Path) -> Result<()> {
        if let Some(parent) = staged.health_marker_path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        if staged.health_marker_path.exists() {
            std::fs::remove_file(&staged.health_marker_path)?;
        }
        let mut journal = self
            .read_journal()?
            .ok_or(UpdateError::JournalUnavailable)?;
        journal.stage = UpdateStage::Installing;
        journal.updated_at = Utc::now();
        self.write_journal(&journal)?;

        let rollback_package = staged
            .rollback_package_path
            .as_ref()
            .filter(|path| path.is_file())
            .ok_or(UpdateError::RollbackPackageUnavailable)?;
        Command::new(current_executable)
            .arg("--drive-update-watchdog")
            .arg(&staged.health_marker_path)
            .arg(rollback_package)
            .arg("300")
            .spawn()
            .map_err(|_| UpdateError::InstallLaunchFailed)?;
        Command::new(&staged.package_path)
            .arg("/S")
            .spawn()
            .map_err(|_| UpdateError::InstallLaunchFailed)?;
        Ok(())
    }

    pub fn mark_current_healthy(&self) -> Result<bool> {
        let Some(mut journal) = self.read_journal()? else {
            return Ok(false);
        };
        if journal.target_version != self.current_version.to_string()
            || journal.stage != UpdateStage::Installing
        {
            return Ok(false);
        }
        if let Some(parent) = journal.health_marker_path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        std::fs::write(
            &journal.health_marker_path,
            self.current_version.to_string(),
        )?;
        journal.stage = UpdateStage::Healthy;
        journal.updated_at = Utc::now();
        self.write_journal(&journal)?;
        Ok(true)
    }

    pub fn rollback_package(&self) -> Result<Option<PathBuf>> {
        Ok(self
            .read_journal()?
            .and_then(|journal| journal.rollback_package_path))
    }

    pub fn launch_rollback(&self) -> Result<bool> {
        let Some(package) = self.rollback_package()? else {
            return Ok(false);
        };
        Command::new(package)
            .arg("/S")
            .spawn()
            .map_err(|_| UpdateError::InstallLaunchFailed)?;
        Ok(true)
    }

    fn journal_path(&self) -> PathBuf {
        self.data_dir.join("updates").join("journal.json")
    }

    fn read_journal(&self) -> Result<Option<UpdateJournal>> {
        let path = self.journal_path();
        if !path.exists() {
            return Ok(None);
        }
        Ok(Some(serde_json::from_slice(&std::fs::read(path)?)?))
    }

    fn write_journal(&self, journal: &UpdateJournal) -> Result<()> {
        let path = self.journal_path();
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let temporary = path.with_extension("json.tmp");
        std::fs::write(&temporary, serde_json::to_vec_pretty(journal)?)?;
        if path.exists() {
            atomic_replace(temporary, path)?;
        } else {
            std::fs::rename(temporary, path)?;
        }
        Ok(())
    }

    async fn download_and_verify(&self, package: &UpdatePackage, destination: &Path) -> Result<()> {
        ensure_https(&package.url)?;
        let bytes = self
            .http
            .get(&package.url)
            .send()
            .await?
            .error_for_status()?
            .bytes()
            .await?;
        self.verifier.verify_package(package, &bytes)?;
        // Keep an executable suffix so Windows selects the PE/Authenticode SIP
        // when WinVerifyTrust inspects the staged file.
        let temporary = destination.with_extension("partial.exe");
        tokio::fs::write(&temporary, &bytes).await?;
        if let Err(error) = self.verifier.verify_authenticode(package, &temporary) {
            let _ = tokio::fs::remove_file(&temporary).await;
            return Err(error);
        }
        if destination.exists() {
            atomic_replace(temporary, destination)?;
        } else {
            tokio::fs::rename(temporary, destination).await?;
        }
        Ok(())
    }
}

pub fn run_watchdog_from_args() -> Result<bool> {
    let arguments = std::env::args_os().collect::<Vec<_>>();
    if arguments.get(1).and_then(|value| value.to_str()) != Some("--drive-update-watchdog") {
        return Ok(false);
    }
    if arguments.len() != 5 {
        return Err(UpdateError::InvalidWatchdogArguments);
    }
    let health_marker = PathBuf::from(&arguments[2]);
    let rollback_package = PathBuf::from(&arguments[3]);
    let timeout_seconds = arguments[4]
        .to_str()
        .and_then(|value| value.parse::<u64>().ok())
        .ok_or(UpdateError::InvalidWatchdogArguments)?;
    let deadline = Instant::now() + Duration::from_secs(timeout_seconds.clamp(10, 900));
    while Instant::now() < deadline {
        if health_marker.exists() {
            return Ok(true);
        }
        std::thread::sleep(Duration::from_secs(2));
    }
    if !health_marker.exists() {
        if !rollback_package.is_file() {
            return Err(UpdateError::RollbackPackageUnavailable);
        }
        Command::new(rollback_package)
            .arg("/S")
            .spawn()
            .map_err(|_| UpdateError::InstallLaunchFailed)?;
    }
    Ok(true)
}

pub fn sign_package(signing_key: &[u8; 32], bytes: &[u8]) -> String {
    let key = SigningKey::from_bytes(signing_key);
    BASE64.encode(key.sign(bytes).to_bytes())
}

pub fn sign_manifest(
    signing_key: &[u8; 32],
    payload: UpdateManifestPayload,
) -> Result<SignedUpdateManifest> {
    let key = SigningKey::from_bytes(signing_key);
    let signature = key.sign(&serde_json::to_vec(&payload)?);
    Ok(SignedUpdateManifest {
        payload,
        signature: BASE64.encode(signature.to_bytes()),
    })
}

fn decode_signature(value: &str) -> Result<Signature> {
    let bytes = BASE64
        .decode(value.trim())
        .map_err(|_| UpdateError::InvalidSignatureEncoding)?;
    Signature::from_slice(&bytes).map_err(|_| UpdateError::InvalidSignatureEncoding)
}

fn ensure_https(url: &str) -> Result<()> {
    let url = reqwest::Url::parse(url).map_err(|_| UpdateError::InsecureUrl)?;
    if url.scheme() != "https" {
        return Err(UpdateError::InsecureUrl);
    }
    Ok(())
}

fn verify_authenticode_certificate_hash(expected: &str, certificate_der: &[u8]) -> Result<()> {
    let expected = normalize_certificate_hash(expected)?;
    let actual = hex::encode(Sha256::digest(certificate_der));
    if actual != expected {
        return Err(UpdateError::AuthenticodeCertificateMismatch);
    }
    Ok(())
}

fn normalize_certificate_hash(value: &str) -> Result<String> {
    let value = value.trim();
    if value.len() != 64 || !value.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(UpdateError::InvalidAuthenticodeCertificateHash);
    }
    Ok(value.to_ascii_lowercase())
}

#[cfg(windows)]
fn verify_authenticode_package(path: &Path, expected_certificate_hash: &str) -> Result<()> {
    use std::ffi::c_void;
    use std::mem::size_of;
    use std::os::windows::ffi::OsStrExt;
    use std::slice;

    use windows_sys::Win32::Foundation::{CERT_E_CHAINING, CERT_E_UNTRUSTEDROOT};
    use windows_sys::Win32::Security::WinTrust::{
        WTHelperGetProvCertFromChain, WTHelperGetProvSignerFromChain,
        WTHelperProvDataFromStateData, WinVerifyTrust, WINTRUST_ACTION_GENERIC_VERIFY_V2,
        WINTRUST_DATA, WINTRUST_DATA_0, WINTRUST_FILE_INFO, WTD_CACHE_ONLY_URL_RETRIEVAL,
        WTD_CHOICE_FILE, WTD_REVOKE_NONE, WTD_STATEACTION_CLOSE, WTD_STATEACTION_VERIFY,
        WTD_UICONTEXT_INSTALL, WTD_UI_NONE,
    };

    normalize_certificate_hash(expected_certificate_hash)?;
    let path = path
        .as_os_str()
        .encode_wide()
        .chain(std::iter::once(0))
        .collect::<Vec<_>>();
    let mut file_info = WINTRUST_FILE_INFO {
        cbStruct: size_of::<WINTRUST_FILE_INFO>() as u32,
        pcwszFilePath: path.as_ptr(),
        hFile: std::ptr::null_mut(),
        pgKnownSubject: std::ptr::null_mut(),
    };
    let mut trust_data = WINTRUST_DATA {
        cbStruct: size_of::<WINTRUST_DATA>() as u32,
        pPolicyCallbackData: std::ptr::null_mut(),
        pSIPClientData: std::ptr::null_mut(),
        dwUIChoice: WTD_UI_NONE,
        fdwRevocationChecks: WTD_REVOKE_NONE,
        dwUnionChoice: WTD_CHOICE_FILE,
        Anonymous: WINTRUST_DATA_0 {
            pFile: &mut file_info,
        },
        dwStateAction: WTD_STATEACTION_VERIFY,
        hWVTStateData: std::ptr::null_mut(),
        pwszURLReference: std::ptr::null_mut(),
        dwProvFlags: WTD_CACHE_ONLY_URL_RETRIEVAL,
        dwUIContext: WTD_UICONTEXT_INSTALL,
        pSignatureSettings: std::ptr::null_mut(),
    };
    let mut action = WINTRUST_ACTION_GENERIC_VERIFY_V2;
    let status = unsafe {
        WinVerifyTrust(
            std::ptr::null_mut(),
            &mut action,
            &mut trust_data as *mut WINTRUST_DATA as *mut c_void,
        )
    };
    let status_is_acceptable =
        status == 0 || status == CERT_E_UNTRUSTEDROOT || status == CERT_E_CHAINING;
    let certificate = if status_is_acceptable {
        unsafe {
            let provider_data = WTHelperProvDataFromStateData(trust_data.hWVTStateData);
            if provider_data.is_null() {
                Err(UpdateError::AuthenticodeSignerUnavailable)
            } else {
                let signer = WTHelperGetProvSignerFromChain(provider_data, 0, 0, 0);
                if signer.is_null() {
                    Err(UpdateError::AuthenticodeSignerUnavailable)
                } else {
                    let provider_certificate = WTHelperGetProvCertFromChain(signer, 0);
                    if provider_certificate.is_null()
                        || (*provider_certificate).pCert.is_null()
                        || (*(*provider_certificate).pCert).pbCertEncoded.is_null()
                        || (*(*provider_certificate).pCert).cbCertEncoded == 0
                    {
                        Err(UpdateError::AuthenticodeSignerUnavailable)
                    } else {
                        let certificate = (*provider_certificate).pCert;
                        Ok(slice::from_raw_parts(
                            (*certificate).pbCertEncoded,
                            (*certificate).cbCertEncoded as usize,
                        )
                        .to_vec())
                    }
                }
            }
        }
    } else {
        Err(UpdateError::AuthenticodeSignatureInvalid(status as u32))
    };
    trust_data.dwStateAction = WTD_STATEACTION_CLOSE;
    unsafe {
        WinVerifyTrust(
            std::ptr::null_mut(),
            &mut action,
            &mut trust_data as *mut WINTRUST_DATA as *mut c_void,
        );
    }
    verify_authenticode_certificate_hash(expected_certificate_hash, &certificate?)
}

#[cfg(not(windows))]
fn verify_authenticode_package(_path: &Path, expected_certificate_hash: &str) -> Result<()> {
    normalize_certificate_hash(expected_certificate_hash)?;
    Err(UpdateError::AuthenticodeUnsupported)
}

#[cfg(test)]
mod tests {
    use chrono::Utc;
    use ed25519_dalek::SigningKey;

    use super::{
        sign_manifest, sign_package, verify_authenticode_certificate_hash, SignedUpdateManifest,
        UpdateError, UpdateManifestPayload, UpdatePackage, UpdateVerifier,
    };
    use base64::engine::general_purpose::STANDARD as BASE64;
    use base64::Engine;
    use sha2::Digest;

    #[test]
    fn signed_manifest_and_package_reject_tampering() {
        let secret = [7_u8; 32];
        let public_key = BASE64.encode(SigningKey::from_bytes(&secret).verifying_key().to_bytes());
        let package_bytes = b"signed enterprise drive installer";
        let package = UpdatePackage {
            version: "0.5.1".to_string(),
            target: "x86_64-pc-windows-msvc".to_string(),
            url: "https://github.com/example/release/setup.exe".to_string(),
            sha256: hex::encode(sha2::Sha256::digest(package_bytes)),
            signature: sign_package(&secret, package_bytes),
            authenticode_certificate_sha256: "ab".repeat(32),
        };
        let manifest = sign_manifest(
            &secret,
            UpdateManifestPayload {
                schema_version: 1,
                published_at: Utc::now(),
                package,
                rollback_package: None,
            },
        )
        .unwrap();
        let verifier = UpdateVerifier::from_base64(&public_key).unwrap();

        verifier.verify_manifest(&manifest).unwrap();
        verifier
            .verify_package(&manifest.payload.package, package_bytes)
            .unwrap();
        assert!(verifier
            .verify_package(&manifest.payload.package, b"tampered")
            .is_err());

        let mut tampered: SignedUpdateManifest = manifest;
        tampered.payload.package.url = "https://attacker.invalid/setup.exe".to_string();
        assert!(verifier.verify_manifest(&tampered).is_err());
    }

    #[test]
    fn authenticode_certificate_hash_is_pinned_to_der_bytes() {
        let certificate_der = b"test signer certificate";
        let expected = hex::encode(sha2::Sha256::digest(certificate_der)).to_ascii_uppercase();

        verify_authenticode_certificate_hash(&expected, certificate_der).unwrap();
        assert!(matches!(
            verify_authenticode_certificate_hash(&"ab".repeat(32), certificate_der),
            Err(UpdateError::AuthenticodeCertificateMismatch)
        ));
        assert!(matches!(
            verify_authenticode_certificate_hash("not-a-sha256", certificate_der),
            Err(UpdateError::InvalidAuthenticodeCertificateHash)
        ));
    }

    #[test]
    fn signed_manifest_preserves_the_rollback_package() {
        let secret = [9_u8; 32];
        let rollback_bytes = b"previous enterprise drive installer";
        let rollback_package = UpdatePackage {
            version: "0.9.0".to_string(),
            target: "x86_64-pc-windows-msvc".to_string(),
            url: "https://github.com/example/release/rollback.exe".to_string(),
            sha256: hex::encode(sha2::Sha256::digest(rollback_bytes)),
            signature: sign_package(&secret, rollback_bytes),
            authenticode_certificate_sha256: "cd".repeat(32),
        };
        let package = UpdatePackage {
            version: "1.0.0".to_string(),
            target: rollback_package.target.clone(),
            url: "https://github.com/example/release/setup.exe".to_string(),
            sha256: hex::encode(sha2::Sha256::digest(b"current installer")),
            signature: sign_package(&secret, b"current installer"),
            authenticode_certificate_sha256: "ab".repeat(32),
        };

        let manifest = sign_manifest(
            &secret,
            UpdateManifestPayload {
                schema_version: 1,
                published_at: Utc::now(),
                package,
                rollback_package: Some(rollback_package.clone()),
            },
        )
        .unwrap();

        assert_eq!(manifest.payload.rollback_package, Some(rollback_package));
    }
}
