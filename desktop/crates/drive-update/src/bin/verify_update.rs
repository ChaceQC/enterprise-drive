use std::path::PathBuf;

use drive_update::{SignedUpdateManifest, UpdateVerifier};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let arguments = std::env::args().skip(1).collect::<Vec<_>>();
    let manifest_path = PathBuf::from(required_argument(&arguments, "--manifest")?);
    let package_path = PathBuf::from(required_argument(&arguments, "--package")?);
    let rollback_package_path = PathBuf::from(required_argument(&arguments, "--rollback-package")?);
    let public_key_path = PathBuf::from(required_argument(&arguments, "--public-key")?);
    let manifest: SignedUpdateManifest = serde_json::from_slice(&std::fs::read(manifest_path)?)?;
    let package = std::fs::read(&package_path)?;
    let rollback_package = std::fs::read(&rollback_package_path)?;
    let public_key = std::fs::read_to_string(public_key_path)?;
    let verifier = UpdateVerifier::from_base64(&public_key)?;
    verifier.verify_manifest(&manifest)?;
    verifier.verify_package(&manifest.payload.package, &package)?;
    verifier.verify_authenticode(&manifest.payload.package, &package_path)?;
    let rollback_manifest_package = manifest
        .payload
        .rollback_package
        .as_ref()
        .ok_or("manifest rollback package is missing")?;
    verifier.verify_package(rollback_manifest_package, &rollback_package)?;
    verifier.verify_authenticode(rollback_manifest_package, &rollback_package_path)?;
    Ok(())
}

fn required_argument(
    arguments: &[String],
    name: &str,
) -> Result<String, Box<dyn std::error::Error>> {
    arguments
        .windows(2)
        .find(|pair| pair[0] == name)
        .map(|pair| pair[1].clone())
        .ok_or_else(|| format!("missing argument {name}").into())
}
