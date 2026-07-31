from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings

POSTGRES_PASSWORD = "PostgresStrongSecret2026"
REDIS_PASSWORD = "RedisStrongSecret2026"


def _production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "production",
        "debug": False,
        "secret_key": "0123456789abcdef0123456789abcdef01234567",
        "database_url": (
            f"postgresql+asyncpg://drive:{POSTGRES_PASSWORD}@postgres:5432/enterprise_drive"
        ),
        "redis_url": f"redis://:{REDIS_PASSWORD}@redis:6379/0",
        "celery_broker_url": f"redis://:{REDIS_PASSWORD}@redis:6379/1",
        "celery_result_backend": f"redis://:{REDIS_PASSWORD}@redis:6379/2",
        "s3_public_endpoint_url": "http://localhost:19000",
        "s3_secret_access_key": "MinioStrongSecret2026",
        "trusted_hosts": ["localhost", "127.0.0.1"],
        "cors_origins": ["http://localhost:15173"],
        "session_cookie_secure": False,
        "rate_limit_enabled": True,
        "admin_password": "AdminStrongSecret2026",
    }
    values.update(overrides)
    return Settings(**values)


def test_local_production_baseline_allows_loopback_http() -> None:
    settings = _production_settings()

    assert settings.environment == "production"
    assert settings.session_cookie_secure is False


def test_public_production_baseline_requires_https_and_secure_cookie() -> None:
    settings = _production_settings(
        trusted_hosts=["drive.example.com", "storage.example.com"],
        cors_origins=["https://app.example.com"],
        s3_public_endpoint_url="https://storage.example.com",
        session_cookie_secure=True,
    )

    assert settings.session_cookie_secure is True


@pytest.mark.parametrize(
    ("overrides", "expected_message"),
    [
        ({"debug": True}, "DRIVE_DEBUG must be false"),
        (
            {"rate_limit_enabled": False},
            "DRIVE_RATE_LIMIT_ENABLED must be true",
        ),
        (
            {"secret_key": "change-me-use-a-long-random-secret"},
            "DRIVE_SECRET_KEY",
        ),
        (
            {"s3_secret_access_key": "drive-dev-password"},
            "DRIVE_S3_SECRET_ACCESS_KEY",
        ),
        (
            {"admin_password": "change-me-admin-password"},
            "DRIVE_ADMIN_PASSWORD",
        ),
        (
            {"database_url": "postgresql+asyncpg://drive:short@postgres:5432/drive"},
            "DRIVE_DATABASE_URL",
        ),
        (
            {"redis_url": "redis://redis:6379/0"},
            "DRIVE_REDIS_URL",
        ),
        (
            {"trusted_hosts": ["*", "drive.example.com"]},
            "DRIVE_TRUSTED_HOSTS",
        ),
        (
            {"cors_origins": ["https://user:pass@app.example.com/private"]},
            "DRIVE_CORS_ORIGINS",
        ),
        (
            {"s3_public_endpoint_url": "https://user:pass@storage.example.com/"},
            "DRIVE_S3_PUBLIC_ENDPOINT_URL",
        ),
    ],
)
def test_production_rejects_insecure_values(
    overrides: dict[str, object],
    expected_message: str,
) -> None:
    with pytest.raises(ValidationError, match=expected_message):
        _production_settings(**overrides)


def test_public_production_rejects_insecure_cookie_and_http_origins() -> None:
    with pytest.raises(ValidationError) as error:
        _production_settings(
            trusted_hosts=["drive.example.com"],
            cors_origins=["http://app.example.com"],
            s3_public_endpoint_url="http://storage.example.com:9000",
            session_cookie_secure=False,
        )

    message = str(error.value)
    assert "DRIVE_SESSION_COOKIE_SECURE" in message
    assert "Public DRIVE_CORS_ORIGINS entries must use HTTPS" in message
    assert "Public DRIVE_S3_PUBLIC_ENDPOINT_URL must use HTTPS" in message
    assert "Public DRIVE_S3_PUBLIC_ENDPOINT_URL must use port 443" in message


def test_public_api_rejects_loopback_http_s3_endpoint() -> None:
    with pytest.raises(
        ValidationError,
        match="Public DRIVE_S3_PUBLIC_ENDPOINT_URL must use HTTPS",
    ):
        _production_settings(
            trusted_hosts=["drive.example.com"],
            cors_origins=["https://app.example.com"],
            s3_public_endpoint_url="http://localhost:19000",
            session_cookie_secure=True,
        )


def test_samesite_none_requires_secure_cookie() -> None:
    with pytest.raises(ValidationError, match="DRIVE_SESSION_COOKIE_SAMESITE=none"):
        _production_settings(session_cookie_samesite="none")


def test_validation_errors_do_not_echo_secret_inputs() -> None:
    leaked_value = "short-private-value"

    with pytest.raises(ValidationError) as error:
        _production_settings(secret_key=leaked_value)

    assert leaked_value not in str(error.value)
