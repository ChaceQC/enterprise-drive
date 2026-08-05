use std::path::{Path, PathBuf};

use base64::engine::general_purpose::STANDARD as BASE64;
use base64::Engine;
use chrono::{DateTime, Utc};
use drive_update::{sign_manifest, sign_package, UpdateManifestPayload, UpdatePackage};
use semver::Version;
use sha2::{Digest, Sha256};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let arguments = std::env::args().skip(1).collect::<Vec<_>>();
    let package_path = PathBuf::from(required_argument(&arguments, "--package")?);
    let version = required_argument(&arguments, "--version")?;
    let target = required_argument(&arguments, "--target")?;
    let url = required_argument(&arguments, "--url")?;
    let output = PathBuf::from(required_argument(&arguments, "--output")?);
    let certificate_sha256 = required_argument(&arguments, "--certificate-sha256")?;
    let rollback_package_path = PathBuf::from(required_argument(&arguments, "--rollback-package")?);
    let rollback_version = required_argument(&arguments, "--rollback-version")?;
    let rollback_url = required_argument(&arguments, "--rollback-url")?;
    let rollback_certificate_sha256 =
        required_argument(&arguments, "--rollback-certificate-sha256")?;
    if Version::parse(&rollback_version)? >= Version::parse(&version)? {
        return Err("rollback version must be lower than the update version".into());
    }
    let published_at = optional_argument(&arguments, "--published-at")
        .map(|value| value.parse::<DateTime<Utc>>())
        .transpose()?
        .unwrap_or_else(Utc::now);
    let signing_key = BASE64.decode(std::env::var("DRIVE_UPDATE_SIGNING_KEY_BASE64")?)?;
    let signing_key: [u8; 32] = signing_key
        .try_into()
        .map_err(|_| "DRIVE_UPDATE_SIGNING_KEY_BASE64 must decode to 32 bytes")?;
    let package = package_from_path(
        &package_path,
        version,
        target.clone(),
        url,
        certificate_sha256,
        &signing_key,
    )?;
    let rollback_package = package_from_path(
        &rollback_package_path,
        rollback_version,
        target,
        rollback_url,
        rollback_certificate_sha256,
        &signing_key,
    )?;
    let manifest = sign_manifest(
        &signing_key,
        UpdateManifestPayload {
            schema_version: 1,
            published_at,
            package,
            rollback_package: Some(rollback_package),
        },
    )?;
    if let Some(parent) = output.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(output, serde_json::to_vec_pretty(&manifest)?)?;
    Ok(())
}

fn package_from_path(
    path: &Path,
    version: String,
    target: String,
    url: String,
    certificate_sha256: String,
    signing_key: &[u8; 32],
) -> Result<UpdatePackage, Box<dyn std::error::Error>> {
    let package_bytes = std::fs::read(path)?;
    Ok(UpdatePackage {
        version,
        target,
        url,
        sha256: hex::encode(Sha256::digest(&package_bytes)),
        signature: sign_package(signing_key, &package_bytes),
        authenticode_certificate_sha256: certificate_sha256,
    })
}

fn required_argument(
    arguments: &[String],
    name: &str,
) -> Result<String, Box<dyn std::error::Error>> {
    optional_argument(arguments, name).ok_or_else(|| format!("missing argument {name}").into())
}

fn optional_argument(arguments: &[String], name: &str) -> Option<String> {
    arguments
        .windows(2)
        .find(|pair| pair[0] == name)
        .map(|pair| pair[1].clone())
}
