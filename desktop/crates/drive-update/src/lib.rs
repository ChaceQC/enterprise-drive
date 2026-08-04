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
    #[error("update URL must use HTTPS")]
    InsecureUrl,
    #[error("update manifest target does not match this client")]
    TargetMismatch,
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
        let staging_dir = self
            .data_dir
            .join("updates")
            .join("staging")
            .join(target_version.to_string());
        tokio::fs::create_dir_all(&staging_dir).await?;
        let package_path = staging_dir.join("enterprise-drive-update.exe");
        self.download_and_verify(&manifest.payload.package, &package_path)
            .await?;
        let rollback_package_path =
            if let Some(package) = manifest.payload.rollback_package.as_ref() {
                if package.target != self.expected_target {
                    return Err(UpdateError::TargetMismatch);
                }
                let path = staging_dir.join("enterprise-drive-rollback.exe");
                self.download_and_verify(package, &path).await?;
                Some(path)
            } else {
                None
            };
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

        if let Some(rollback_package) = staged.rollback_package_path.as_ref() {
            Command::new(current_executable)
                .arg("--drive-update-watchdog")
                .arg(&staged.health_marker_path)
                .arg(rollback_package)
                .arg("300")
                .spawn()
                .map_err(|_| UpdateError::InstallLaunchFailed)?;
        }
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
        let temporary = destination.with_extension("exe.partial");
        tokio::fs::write(&temporary, &bytes).await?;
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
    if !health_marker.exists() && rollback_package.exists() {
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

#[cfg(test)]
mod tests {
    use chrono::Utc;
    use ed25519_dalek::SigningKey;

    use super::{
        sign_manifest, sign_package, SignedUpdateManifest, UpdateManifestPayload, UpdatePackage,
        UpdateVerifier,
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
}
