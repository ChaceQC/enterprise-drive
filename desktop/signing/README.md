# 桌面发布签名

- 更新清单和安装包 detached signature 使用 `desktop/update-public-key.txt` 中的 Ed25519 公钥验证。
- Windows 安装包使用 `desktop-code-signing.pem` 对应私钥做 Authenticode 签名。
- 证书 DER SHA-256：`765e82aba7bd3276f18eeadddd7b33257a68b7a1ddcdac6d4fc7f7bc639a3ca5`。
- Ed25519 私钥、PKCS#12 和口令只保存在 GitHub Actions Secrets：
  - `DRIVE_UPDATE_SIGNING_KEY_BASE64`
  - `DRIVE_WINDOWS_SIGNING_PFX_BASE64`
  - `DRIVE_WINDOWS_SIGNING_PFX_PASSWORD`

仓库不保存任何发布私钥。CI 会验证 Authenticode 状态、证书指纹、清单签名、包签名和 SHA-256。
