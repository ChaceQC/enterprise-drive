from __future__ import annotations

from functools import lru_cache
from ipaddress import ip_address
from typing import Literal, Self
from urllib.parse import SplitResult, unquote, urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PRODUCTION_SECRET_MARKERS = (
    "change-me",
    "change_me",
    "change me",
    "changeme",
)
_KNOWN_EXAMPLE_SECRETS = frozenset(
    {
        "change-me-before-first-run",
        "dev-secret-change-me",
        "drive-dev-password",
        "drive_dev_password",
        "minioadmin",
    }
)


def _is_loopback_host(hostname: str | None) -> bool:
    if hostname is None:
        return False

    normalized = hostname.rstrip(".").casefold()
    if normalized == "localhost" or normalized.endswith(".localhost"):
        return True
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False


def _secret_error(name: str, value: str, *, minimum_length: int) -> str | None:
    normalized = value.strip().casefold()
    if (
        len(value) < minimum_length
        or not normalized
        or normalized in _KNOWN_EXAMPLE_SECRETS
        or any(marker in normalized for marker in _PRODUCTION_SECRET_MARKERS)
        or "$" in value
    ):
        return (
            f"{name} must be a non-interpolated, non-example value of at least "
            f"{minimum_length} characters"
        )
    return None


def _password_url_error(
    name: str,
    value: str,
    *,
    allowed_schemes: frozenset[str],
) -> str | None:
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        password = unquote(parsed.password or "")
    except ValueError:
        return f"{name} must be a valid credential URL"

    if parsed.scheme not in allowed_schemes or hostname is None:
        return f"{name} must use an expected scheme and include a host"
    if parsed.username is None and parsed.password is None:
        return f"{name} must include credential user info"
    secret_error = _secret_error(name, password, minimum_length=16)
    if secret_error is not None:
        return secret_error
    return None


def _parse_http_root_url(
    name: str,
    value: str,
    errors: list[str],
) -> SplitResult | None:
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError:
        errors.append(f"{name} must be a valid HTTP(S) root URL")
        return None

    if (
        parsed.scheme not in {"http", "https"}
        or hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        errors.append(
            f"{name} must be an explicit HTTP(S) root URL without credentials, "
            "path, query, or fragment"
        )
        return None
    return parsed


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="DRIVE_",
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_name: str = "企业网盘"
    app_version: str = "0.6.0"
    service_name: str = "enterprise-drive-api"
    environment: Literal["local", "test", "staging", "production"] = "local"
    debug: bool = False
    app_port: int = 18080
    api_v1_prefix: str = "/api/v1"
    secret_key: str = "dev-secret-change-me"

    request_id_header: str = "X-Request-ID"
    log_level: str = "INFO"
    metrics_database_refresh_enabled: bool = True
    metrics_database_refresh_timeout_seconds: float = Field(default=1.0, gt=0)
    worker_metrics_port: int = Field(default=0, ge=0, le=65535)
    tracing_enabled: bool = True
    tracing_sample_ratio: float = Field(default=0.1, ge=0, le=1)
    tracing_exporter: Literal["none", "console", "otlp_http"] = "none"
    tracing_otlp_endpoint: str | None = None
    tracing_otlp_headers: dict[str, str] = Field(default_factory=dict)
    tracing_export_timeout_seconds: float = Field(default=10.0, gt=0)
    tracing_excluded_urls: str = "/healthz,/readyz,/metrics"

    trusted_hosts: list[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "testserver"]
    )
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:15173", "http://127.0.0.1:15173"]
    )

    database_url: str = (
        "postgresql+asyncpg://drive:drive_dev_password@127.0.0.1:15432/enterprise_drive"
    )
    database_pool_mode: Literal["queue", "null"] = "queue"
    database_pool_size: int = Field(default=5, ge=1)
    database_max_overflow: int = Field(default=5, ge=0)
    database_pool_timeout_seconds: int = Field(default=10, ge=1)
    redis_url: str = "redis://127.0.0.1:16379/0"
    s3_endpoint_url: str = "http://127.0.0.1:19000"
    s3_public_endpoint_url: str | None = None
    s3_bucket: str = "enterprise-drive-local"
    s3_access_key_id: str = "drive-dev"
    s3_secret_access_key: str = "drive-dev-password"
    s3_region: str = "us-east-1"
    s3_control_request_timeout_seconds: int = Field(default=30, ge=1, le=300)
    s3_control_presign_expires_seconds: int = Field(default=300, ge=60, le=3600)
    opensearch_url: str = "http://127.0.0.1:19200"
    opensearch_index_name: str = "drive_files_v1"
    celery_broker_url: str = "redis://127.0.0.1:16379/1"
    celery_result_backend: str = "redis://127.0.0.1:16379/2"
    outbox_batch_size: int = 100
    outbox_max_retries: int = 8
    outbox_dispatch_interval_seconds: int = Field(default=5, ge=1)
    maintenance_task_batch_size: int = Field(default=100, ge=1)
    file_tree_async_threshold: int = Field(default=1000, ge=2)
    file_tree_operation_batch_size: int = Field(default=500, ge=1)
    file_tree_operation_interval_seconds: int = Field(default=5, ge=1)
    upload_cleanup_interval_seconds: int = Field(default=300, ge=1)
    trash_retention_days: int = Field(default=30, ge=1)
    trash_cleanup_interval_seconds: int = Field(default=3600, ge=1)
    share_expiry_interval_seconds: int = Field(default=300, ge=1)
    blob_cleanup_interval_seconds: int = Field(default=3600, ge=1)
    orphan_object_scan_interval_seconds: int = Field(default=86400, ge=1)
    quota_reconciliation_interval_seconds: int = Field(default=86400, ge=1)
    maintenance_alert_consecutive_failures: int = Field(default=3, ge=1)
    maintenance_alert_stale_intervals: int = Field(default=3, ge=2)
    maintenance_state_ttl_seconds: int = Field(default=30 * 24 * 3600, ge=3600)
    maintenance_state_redis_timeout_seconds: float = Field(default=1.0, gt=0, le=10)
    maintenance_health_refresh_seconds: int = Field(default=30, ge=5, le=300)
    admin_export_max_rows: int = Field(default=50_000, ge=1, le=1_000_000)
    admin_export_presign_expires_seconds: int = Field(default=300, ge=60, le=3600)
    admin_export_retention_days: int = Field(default=30, ge=1, le=3650)
    admin_export_cleanup_interval_seconds: int = Field(default=86400, ge=60)
    upload_session_ttl_minutes: int = 1440
    upload_part_size_bytes: int = 8 * 1024 * 1024
    upload_presign_expires_seconds: int = 900
    upload_max_parallelism: int = Field(default=4, ge=1, le=32)
    download_presign_expires_seconds: int = 300
    download_proxy_enabled: bool = True
    download_proxy_max_range_bytes: int = Field(default=64 * 1024 * 1024, ge=1)
    download_proxy_chunk_size_bytes: int = Field(
        default=256 * 1024,
        ge=64 * 1024,
        le=4 * 1024 * 1024,
    )
    file_security_policy_enabled: bool = True
    watermark_max_source_bytes: int = Field(default=20 * 1024 * 1024, ge=1)
    default_space_quota_bytes: int = 1024 * 1024 * 1024 * 1024
    default_user_quota_bytes: int = Field(default=0, ge=0)
    default_tenant_quota_bytes: int = Field(default=0, ge=0)
    quota_policy_enabled: bool = True
    rate_limit_enabled: bool = True
    login_ip_rate_limit_count: int = Field(default=30, ge=1)
    login_account_rate_limit_count: int = Field(default=10, ge=1)
    login_rate_limit_window_seconds: int = Field(default=60, ge=1)
    upload_init_rate_limit_count: int = 60
    upload_init_rate_limit_window_seconds: int = 60
    upload_part_presign_rate_limit_count: int = 300
    upload_part_presign_rate_limit_window_seconds: int = 60
    download_presign_rate_limit_count: int = 120
    download_presign_rate_limit_window_seconds: int = 60
    download_proxy_rate_limit_count: int = 60
    download_proxy_rate_limit_window_seconds: int = 60
    download_watermark_rate_limit_count: int = 30
    download_watermark_rate_limit_window_seconds: int = 60
    search_query_rate_limit_count: int = 60
    search_query_rate_limit_window_seconds: int = 60
    share_external_access_rate_limit_count: int = 60
    share_external_access_rate_limit_window_seconds: int = 60
    share_external_download_rate_limit_count: int = 120
    share_external_download_rate_limit_window_seconds: int = 60
    search_text_extract_max_bytes: int = 512 * 1024
    search_complex_extract_max_bytes: int = Field(default=20 * 1024 * 1024, ge=1)
    search_extract_max_chars: int = Field(default=1_000_000, ge=1)
    search_ocr_enabled: bool = True
    search_ocr_command: str = "tesseract"
    search_ocr_languages: str = "eng+chi_sim"
    search_ocr_page_segmentation_mode: int = Field(default=3, ge=0, le=13)
    search_ocr_max_pages: int = Field(default=20, ge=1, le=200)
    search_ocr_pdf_dpi: int = Field(default=144, ge=72, le=300)
    search_ocr_max_pixels: int = Field(default=100_000_000, ge=1)
    search_ocr_max_rendered_bytes: int = Field(default=100 * 1024 * 1024, ge=1)
    search_ocr_command_timeout_seconds: int = Field(default=60, ge=1, le=600)
    preview_max_source_bytes: int = 20 * 1024 * 1024
    preview_image_max_side: int = 1600
    preview_office_command: str = "soffice"
    preview_office_max_pdf_bytes: int = 50 * 1024 * 1024
    preview_pdf_command: str = "pdftoppm"
    preview_pdf_dpi: int = 144
    preview_pdf_max_rendered_bytes: int = 50 * 1024 * 1024
    preview_command_timeout_seconds: int = 30
    preview_task_soft_time_limit_seconds: int = 120
    preview_task_time_limit_seconds: int = 150
    preview_task_rate_limit: str = "30/m"
    preview_presign_expires_seconds: int = 300
    preview_artifact_retention_days: int = Field(default=30, ge=1)
    preview_cleanup_interval_seconds: int = Field(default=86400, ge=1)

    session_cookie_name: str = "drive_session"
    csrf_cookie_name: str = "drive_csrf"
    csrf_header_name: str = "X-CSRF-Token"
    session_cookie_path: str = "/"
    session_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    session_cookie_secure: bool = False
    session_days: int = 30
    device_session_hours: int = Field(default=12, ge=1, le=168)
    sync_cursor_ttl_days: int = Field(default=30, ge=1, le=365)

    admin_tenant_slug: str = "default"
    admin_tenant_name: str = "默认企业"
    admin_username: str = "admin"
    admin_email: str = "admin@example.com"
    admin_password: str = "change-me-before-first-run"

    @model_validator(mode="after")
    def validate_production_security(self) -> Self:
        if self.environment != "production":
            return self

        errors: list[str] = []
        if self.debug:
            errors.append("DRIVE_DEBUG must be false in production")
        if not self.rate_limit_enabled:
            errors.append("DRIVE_RATE_LIMIT_ENABLED must be true in production")

        for name, value, minimum_length in (
            ("DRIVE_SECRET_KEY", self.secret_key, 32),
            ("DRIVE_S3_SECRET_ACCESS_KEY", self.s3_secret_access_key, 16),
            ("DRIVE_ADMIN_PASSWORD", self.admin_password, 16),
        ):
            error = _secret_error(name, value, minimum_length=minimum_length)
            if error is not None:
                errors.append(error)

        for name, value, allowed_schemes in (
            (
                "DRIVE_DATABASE_URL",
                self.database_url,
                frozenset({"postgresql", "postgresql+asyncpg"}),
            ),
            ("DRIVE_REDIS_URL", self.redis_url, frozenset({"redis", "rediss"})),
            (
                "DRIVE_CELERY_BROKER_URL",
                self.celery_broker_url,
                frozenset({"redis", "rediss"}),
            ),
            (
                "DRIVE_CELERY_RESULT_BACKEND",
                self.celery_result_backend,
                frozenset({"redis", "rediss"}),
            ),
        ):
            error = _password_url_error(name, value, allowed_schemes=allowed_schemes)
            if error is not None:
                errors.append(error)

        public_surface = False
        if not self.trusted_hosts:
            errors.append("DRIVE_TRUSTED_HOSTS must not be empty in production")
        for trusted_host in self.trusted_hosts:
            normalized_host = trusted_host.strip()
            if (
                not normalized_host
                or "*" in normalized_host
                or "://" in normalized_host
                or "/" in normalized_host
            ):
                errors.append(
                    "DRIVE_TRUSTED_HOSTS entries must be explicit host names "
                    "without wildcards, schemes, or paths"
                )
                continue
            if not _is_loopback_host(normalized_host.strip("[]")):
                public_surface = True

        parsed_origins: list[SplitResult] = []
        for origin in self.cors_origins:
            parsed_origin = _parse_http_root_url("DRIVE_CORS_ORIGINS", origin, errors)
            if parsed_origin is None:
                continue
            parsed_origins.append(parsed_origin)
            if not _is_loopback_host(parsed_origin.hostname):
                public_surface = True

        if self.s3_public_endpoint_url is None:
            errors.append("DRIVE_S3_PUBLIC_ENDPOINT_URL must be set in production")
            parsed_s3_public_endpoint = None
        else:
            parsed_s3_public_endpoint = _parse_http_root_url(
                "DRIVE_S3_PUBLIC_ENDPOINT_URL",
                self.s3_public_endpoint_url,
                errors,
            )
            if parsed_s3_public_endpoint is not None and not _is_loopback_host(
                parsed_s3_public_endpoint.hostname
            ):
                public_surface = True

        if public_surface:
            if not self.session_cookie_secure:
                errors.append(
                    "DRIVE_SESSION_COOKIE_SECURE must be true for public production hosts"
                )
            if any(origin.scheme != "https" for origin in parsed_origins):
                errors.append("Public DRIVE_CORS_ORIGINS entries must use HTTPS")
            if parsed_s3_public_endpoint is not None:
                if parsed_s3_public_endpoint.scheme != "https":
                    errors.append("Public DRIVE_S3_PUBLIC_ENDPOINT_URL must use HTTPS")
                if parsed_s3_public_endpoint.port not in {None, 443}:
                    errors.append("Public DRIVE_S3_PUBLIC_ENDPOINT_URL must use port 443")

        if self.session_cookie_samesite == "none" and not self.session_cookie_secure:
            errors.append(
                "DRIVE_SESSION_COOKIE_SAMESITE=none requires DRIVE_SESSION_COOKIE_SECURE=true"
            )

        if errors:
            raise ValueError("Production settings validation failed: " + "; ".join(errors))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
