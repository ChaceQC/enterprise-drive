from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class OidcProviderConfig:
    id: UUID
    issuer_url: str
    client_id: str
    client_secret: str | None
    scopes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OidcIdentity:
    issuer: str
    subject: str
    nonce: str
    email: str | None
    email_verified: bool | None
    display_name: str | None
    preferred_username: str | None


@dataclass(frozen=True, slots=True)
class OidcProviderMetadata:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    end_session_endpoint: str | None


class OidcProviderAdapter(Protocol):
    async def test_connection(self, config: OidcProviderConfig) -> OidcProviderMetadata: ...

    async def build_authorization_url(
        self,
        *,
        config: OidcProviderConfig,
        redirect_uri: str,
        state: str,
        nonce: str,
        code_challenge: str,
    ) -> str: ...

    async def exchange_code(
        self,
        *,
        config: OidcProviderConfig,
        redirect_uri: str,
        code: str,
        code_verifier: str,
    ) -> OidcIdentity: ...

    async def build_logout_url(
        self,
        *,
        config: OidcProviderConfig,
        post_logout_redirect_uri: str,
        state: str,
    ) -> str | None: ...


@dataclass(frozen=True, slots=True)
class LdapUserRecord:
    external_id: str
    username: str
    display_name: str
    email: str | None = None
    enabled: bool = True
    department_external_ids: tuple[str, ...] = ()
    group_external_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LdapDepartmentRecord:
    external_id: str
    name: str
    parent_external_id: str | None = None
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class LdapGroupRecord:
    external_id: str
    slug: str
    name: str
    member_external_ids: tuple[str, ...] = ()
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class LdapDirectorySnapshot:
    users: tuple[LdapUserRecord, ...] = ()
    departments: tuple[LdapDepartmentRecord, ...] = ()
    groups: tuple[LdapGroupRecord, ...] = ()
    next_cursor: str | None = None
    diagnostics: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LdapSourceConfig:
    id: UUID
    server_url: str
    base_dn: str
    bind_dn: str | None
    bind_password: str | None
    user_base_dn: str
    user_filter: str
    department_base_dn: str | None
    department_filter: str | None
    group_base_dn: str | None
    group_filter: str | None
    attribute_mapping: dict[str, str]


class LdapProviderAdapter(Protocol):
    async def test_connection(self, config: LdapSourceConfig) -> dict[str, object]: ...

    async def read_directory(
        self,
        *,
        config: LdapSourceConfig,
        mode: str,
        cursor: str | None,
        page_size: int,
    ) -> LdapDirectorySnapshot: ...


class SecretResolver(Protocol):
    def resolve(self, secret_ref: str | None) -> str | None: ...
