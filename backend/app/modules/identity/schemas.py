from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class PublicOidcProviderResponse(BaseModel):
    slug: str
    name: str


class PublicOidcProviderListResponse(BaseModel):
    items: list[PublicOidcProviderResponse]


class OidcProviderCreateRequest(BaseModel):
    slug: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=128)
    issuer_url: str = Field(min_length=1, max_length=2048)
    client_id: str = Field(min_length=1, max_length=512)
    client_secret_ref: str | None = Field(default=None, min_length=1, max_length=1024)
    scopes: list[str] = Field(default_factory=lambda: ["openid", "profile", "email"])
    enabled: bool = True


class OidcProviderUpdateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    issuer_url: str | None = Field(default=None, min_length=1, max_length=2048)
    client_id: str | None = Field(default=None, min_length=1, max_length=512)
    client_secret_ref: str | None = Field(default=None, min_length=1, max_length=1024)
    clear_client_secret_ref: bool = False
    scopes: list[str] | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def ensure_change_requested(self) -> OidcProviderUpdateRequest:
        if self.client_secret_ref is not None and self.clear_client_secret_ref:
            raise ValueError("client_secret_ref 与 clear_client_secret_ref 不能同时提供")
        if (
            self.name is None
            and self.issuer_url is None
            and self.client_id is None
            and self.client_secret_ref is None
            and not self.clear_client_secret_ref
            and self.scopes is None
            and self.enabled is None
        ):
            raise ValueError("至少提供一个 OIDC provider 变更字段")
        return self


class OidcProviderResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    slug: str
    name: str
    issuer_url: str
    client_id: str
    client_secret_configured: bool
    scopes: list[str]
    enabled: bool
    version: int
    created_at: datetime
    updated_at: datetime


class OidcProviderListResponse(BaseModel):
    items: list[OidcProviderResponse]


class OidcProviderTestResponse(BaseModel):
    connected: Literal[True] = True
    issuer: str
    supports_logout: bool


class OidcStartResponse(BaseModel):
    authorization_url: str


class OidcIdentityLinkResponse(BaseModel):
    id: UUID
    provider_id: UUID
    provider_slug: str
    provider_name: str
    issuer: str
    subject: str
    email: str | None
    display_name: str | None
    created_at: datetime
    last_login_at: datetime | None


class OidcIdentityLinkListResponse(BaseModel):
    items: list[OidcIdentityLinkResponse]


class OidcIdentityUnlinkResponse(BaseModel):
    removed_link_id: UUID


class OidcLogoutResponse(BaseModel):
    authenticated: Literal[False] = False
    logout_url: str | None


class LdapSourceCreateRequest(BaseModel):
    slug: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=128)
    server_url: str = Field(min_length=1, max_length=2048)
    base_dn: str = Field(min_length=1, max_length=2048)
    bind_dn: str | None = Field(default=None, max_length=2048)
    bind_password_ref: str | None = Field(default=None, min_length=1, max_length=1024)
    user_base_dn: str = Field(min_length=1, max_length=2048)
    user_filter: str = Field(min_length=1, max_length=2048)
    department_base_dn: str | None = Field(default=None, max_length=2048)
    department_filter: str | None = Field(default=None, max_length=2048)
    group_base_dn: str | None = Field(default=None, max_length=2048)
    group_filter: str | None = Field(default=None, max_length=2048)
    attribute_mapping: dict[str, str]
    enabled: bool = True


class LdapSourceUpdateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    server_url: str | None = Field(default=None, min_length=1, max_length=2048)
    base_dn: str | None = Field(default=None, min_length=1, max_length=2048)
    bind_dn: str | None = Field(default=None, max_length=2048)
    clear_bind_dn: bool = False
    bind_password_ref: str | None = Field(default=None, min_length=1, max_length=1024)
    clear_bind_password_ref: bool = False
    user_base_dn: str | None = Field(default=None, min_length=1, max_length=2048)
    user_filter: str | None = Field(default=None, min_length=1, max_length=2048)
    department_base_dn: str | None = Field(default=None, max_length=2048)
    clear_department_base_dn: bool = False
    department_filter: str | None = Field(default=None, max_length=2048)
    clear_department_filter: bool = False
    group_base_dn: str | None = Field(default=None, max_length=2048)
    clear_group_base_dn: bool = False
    group_filter: str | None = Field(default=None, max_length=2048)
    clear_group_filter: bool = False
    attribute_mapping: dict[str, str] | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def validate_clear_pairs(self) -> LdapSourceUpdateRequest:
        for value_name, clear_name in (
            ("bind_dn", "clear_bind_dn"),
            ("bind_password_ref", "clear_bind_password_ref"),
            ("department_base_dn", "clear_department_base_dn"),
            ("department_filter", "clear_department_filter"),
            ("group_base_dn", "clear_group_base_dn"),
            ("group_filter", "clear_group_filter"),
        ):
            if getattr(self, value_name) is not None and getattr(self, clear_name):
                raise ValueError(f"{value_name} 与 {clear_name} 不能同时提供")
        return self


class LdapSourceResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    slug: str
    name: str
    server_url: str
    base_dn: str
    bind_dn: str | None
    bind_password_configured: bool
    user_base_dn: str
    user_filter: str
    department_base_dn: str | None
    department_filter: str | None
    group_base_dn: str | None
    group_filter: str | None
    attribute_mapping: dict[str, str]
    enabled: bool
    sync_cursor: str | None
    last_success_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime


class LdapSourceListResponse(BaseModel):
    items: list[LdapSourceResponse]


class LdapConnectionTestResponse(BaseModel):
    connected: Literal[True] = True
    server: str
    base_dn_found: bool


class LdapSyncRequest(BaseModel):
    mode: Literal["dry_run", "full", "incremental"]


class LdapSyncRunResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    source_id: UUID
    requested_by: UUID | None
    source_version: int
    mode: Literal["dry_run", "full", "incremental"]
    status: Literal["queued", "running", "succeeded", "failed"]
    cursor_before: str | None
    cursor_after: str | None
    stats: dict[str, int]
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class LdapSyncRunListResponse(BaseModel):
    items: list[LdapSyncRunResponse]


class LdapSyncConflictResponse(BaseModel):
    id: UUID
    run_id: UUID
    source_id: UUID
    object_type: Literal["user", "department", "group", "membership"]
    external_id: str
    code: str
    details: dict[str, object]
    created_at: datetime


class LdapSyncConflictListResponse(BaseModel):
    items: list[LdapSyncConflictResponse]
