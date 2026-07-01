from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="DRIVE_",
        extra="ignore",
    )

    app_name: str = "企业网盘"
    app_version: str = "0.1.0"
    environment: Literal["local", "test", "staging", "production"] = "local"
    debug: bool = False
    app_port: int = 18080
    api_v1_prefix: str = "/api/v1"
    secret_key: str = "dev-secret-change-me"

    request_id_header: str = "X-Request-ID"
    log_level: str = "INFO"

    trusted_hosts: list[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "testserver"]
    )
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:15173", "http://127.0.0.1:15173"]
    )

    database_url: str = (
        "postgresql+asyncpg://drive:drive_dev_password@127.0.0.1:15432/enterprise_drive"
    )
    redis_url: str = "redis://127.0.0.1:16379/0"
    s3_endpoint_url: str = "http://127.0.0.1:19000"
    s3_bucket: str = "enterprise-drive-local"
    s3_access_key_id: str = "drive-dev"
    s3_secret_access_key: str = "drive-dev-password"
    s3_region: str = "us-east-1"
    opensearch_url: str = "http://127.0.0.1:19200"
    opensearch_index_name: str = "drive_files_v1"
    celery_broker_url: str = "redis://127.0.0.1:16379/1"
    celery_result_backend: str = "redis://127.0.0.1:16379/2"
    outbox_batch_size: int = 100
    outbox_max_retries: int = 8
    upload_session_ttl_minutes: int = 1440
    upload_part_size_bytes: int = 8 * 1024 * 1024
    upload_presign_expires_seconds: int = 900
    download_presign_expires_seconds: int = 300
    default_space_quota_bytes: int = 1024 * 1024 * 1024 * 1024
    rate_limit_enabled: bool = True
    upload_init_rate_limit_count: int = 60
    upload_init_rate_limit_window_seconds: int = 60
    upload_part_presign_rate_limit_count: int = 300
    upload_part_presign_rate_limit_window_seconds: int = 60
    download_presign_rate_limit_count: int = 120
    download_presign_rate_limit_window_seconds: int = 60
    search_query_rate_limit_count: int = 60
    search_query_rate_limit_window_seconds: int = 60
    share_external_access_rate_limit_count: int = 60
    share_external_access_rate_limit_window_seconds: int = 60
    share_external_download_rate_limit_count: int = 120
    share_external_download_rate_limit_window_seconds: int = 60
    search_text_extract_max_bytes: int = 512 * 1024
    preview_max_source_bytes: int = 20 * 1024 * 1024
    preview_image_max_side: int = 1600
    preview_presign_expires_seconds: int = 300

    session_cookie_name: str = "drive_session"
    csrf_cookie_name: str = "drive_csrf"
    csrf_header_name: str = "X-CSRF-Token"
    session_cookie_path: str = "/"
    session_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    session_cookie_secure: bool = False
    session_days: int = 30

    admin_tenant_slug: str = "default"
    admin_tenant_name: str = "默认企业"
    admin_username: str = "admin"
    admin_email: str = "admin@example.com"
    admin_password: str = "change-me-before-first-run"


@lru_cache
def get_settings() -> Settings:
    return Settings()
