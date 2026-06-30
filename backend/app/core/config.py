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
    opensearch_url: str = "http://127.0.0.1:19200"
    celery_broker_url: str = "redis://127.0.0.1:16379/1"
    celery_result_backend: str = "redis://127.0.0.1:16379/2"
    outbox_batch_size: int = 100
    outbox_max_retries: int = 8

    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 30

    admin_tenant_slug: str = "default"
    admin_tenant_name: str = "默认企业"
    admin_username: str = "admin"
    admin_email: str = "admin@example.com"
    admin_password: str = "change-me-before-first-run"


@lru_cache
def get_settings() -> Settings:
    return Settings()
