from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet
from joserfc.jwt import JWTClaimsRegistry

from app.api.errors import ApiError
from app.infrastructure.identity.base import (
    OidcIdentity,
    OidcProviderConfig,
    OidcProviderMetadata,
)

_ALLOWED_ID_TOKEN_ALGORITHMS = ("RS256", "ES256")


class HttpOidcProviderAdapter:
    def __init__(self, *, timeout_seconds: float = 10.0) -> None:
        self.timeout_seconds = timeout_seconds

    async def test_connection(self, config: OidcProviderConfig) -> OidcProviderMetadata:
        metadata = await self._load_metadata(config)
        await self._load_jwks(metadata)
        return metadata

    async def build_authorization_url(
        self,
        *,
        config: OidcProviderConfig,
        redirect_uri: str,
        state: str,
        nonce: str,
        code_challenge: str,
    ) -> str:
        metadata = await self._load_metadata(config)
        query = urlencode(
            {
                "response_type": "code",
                "client_id": config.client_id,
                "redirect_uri": redirect_uri,
                "scope": " ".join(config.scopes),
                "state": state,
                "nonce": nonce,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{metadata.authorization_endpoint}?{query}"

    async def exchange_code(
        self,
        *,
        config: OidcProviderConfig,
        redirect_uri: str,
        code: str,
        code_verifier: str,
    ) -> OidcIdentity:
        metadata = await self._load_metadata(config)
        token_payload: dict[str, str] = {
            "grant_type": "authorization_code",
            "client_id": config.client_id,
            "redirect_uri": redirect_uri,
            "code": code,
            "code_verifier": code_verifier,
        }
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                follow_redirects=False,
            ) as client:
                if config.client_secret is not None:
                    response = await client.post(
                        metadata.token_endpoint,
                        data=token_payload,
                        auth=(config.client_id, config.client_secret),
                        headers={"Accept": "application/json"},
                    )
                else:
                    response = await client.post(
                        metadata.token_endpoint,
                        data=token_payload,
                        headers={"Accept": "application/json"},
                    )
                response.raise_for_status()
                token_response = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ApiError(
                "OIDC_TOKEN_EXCHANGE_FAILED",
                "OIDC 登录回调失败",
                status_code=502,
            ) from exc

        if not isinstance(token_response, dict):
            raise ApiError(
                "OIDC_TOKEN_RESPONSE_INVALID",
                "OIDC 登录回调失败",
                status_code=502,
            )
        id_token = token_response.get("id_token")
        if not isinstance(id_token, str) or not id_token:
            raise ApiError(
                "OIDC_ID_TOKEN_MISSING",
                "OIDC 登录回调缺少身份令牌",
                status_code=502,
            )

        claims = await self._verify_id_token(
            config=config,
            metadata=metadata,
            id_token=id_token,
        )
        nonce = claims.get("nonce")
        if not isinstance(nonce, str) or not nonce:
            raise ApiError(
                "OIDC_NONCE_INVALID",
                "OIDC 登录状态校验失败",
                status_code=400,
            )

        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise ApiError(
                "OIDC_SUBJECT_INVALID",
                "OIDC 身份标识无效",
                status_code=502,
            )
        email = _optional_string(claims.get("email"))
        display_name = _optional_string(claims.get("name"))
        preferred_username = _optional_string(claims.get("preferred_username"))
        email_verified_value = claims.get("email_verified")
        email_verified = email_verified_value if isinstance(email_verified_value, bool) else None
        return OidcIdentity(
            issuer=metadata.issuer,
            subject=subject,
            nonce=nonce,
            email=email,
            email_verified=email_verified,
            display_name=display_name,
            preferred_username=preferred_username,
        )

    async def build_logout_url(
        self,
        *,
        config: OidcProviderConfig,
        post_logout_redirect_uri: str,
        state: str,
    ) -> str | None:
        metadata = await self._load_metadata(config)
        if metadata.end_session_endpoint is None:
            return None
        query = urlencode(
            {
                "client_id": config.client_id,
                "post_logout_redirect_uri": post_logout_redirect_uri,
                "state": state,
            }
        )
        return f"{metadata.end_session_endpoint}?{query}"

    async def _load_metadata(self, config: OidcProviderConfig) -> OidcProviderMetadata:
        issuer = _normalize_issuer(config.issuer_url)
        discovery_url = f"{issuer}/.well-known/openid-configuration"
        payload = await self._get_json(discovery_url, error_code="OIDC_DISCOVERY_FAILED")
        discovered_issuer = _required_url(payload, "issuer")
        if discovered_issuer.rstrip("/") != issuer:
            raise ApiError(
                "OIDC_ISSUER_MISMATCH",
                "OIDC 提供商 issuer 不匹配",
                status_code=502,
            )
        authorization_endpoint = _required_url(payload, "authorization_endpoint")
        token_endpoint = _required_url(payload, "token_endpoint")
        jwks_uri = _required_url(payload, "jwks_uri")
        end_session_endpoint = _optional_url(payload, "end_session_endpoint")
        return OidcProviderMetadata(
            issuer=discovered_issuer.rstrip("/"),
            authorization_endpoint=authorization_endpoint,
            token_endpoint=token_endpoint,
            jwks_uri=jwks_uri,
            end_session_endpoint=end_session_endpoint,
        )

    async def _load_jwks(self, metadata: OidcProviderMetadata) -> dict[str, Any]:
        payload = await self._get_json(metadata.jwks_uri, error_code="OIDC_JWKS_FAILED")
        keys = payload.get("keys")
        if not isinstance(keys, list) or not keys:
            raise ApiError(
                "OIDC_JWKS_INVALID",
                "OIDC 提供商签名密钥无效",
                status_code=502,
            )
        return payload

    async def _verify_id_token(
        self,
        *,
        config: OidcProviderConfig,
        metadata: OidcProviderMetadata,
        id_token: str,
    ) -> dict[str, Any]:
        jwks = await self._load_jwks(metadata)
        try:
            key_set = KeySet.import_key_set(jwks)  # type: ignore[arg-type]
            token = jwt.decode(
                id_token,
                key_set,
                algorithms=_ALLOWED_ID_TOKEN_ALGORITHMS,
            )
            claims = dict(token.claims)
            registry = JWTClaimsRegistry(
                leeway=60,
                iss={"essential": True, "value": metadata.issuer},
                sub={"essential": True, "allow_blank": False},
                aud={"essential": True, "value": config.client_id},
                exp={"essential": True},
                iat={"essential": True},
            )
            registry.validate(claims)
        except (JoseError, ValueError, TypeError, KeyError) as exc:
            raise ApiError(
                "OIDC_ID_TOKEN_INVALID",
                "OIDC 身份令牌校验失败",
                status_code=400,
            ) from exc

        audience = claims.get("aud")
        if isinstance(audience, list) and len(audience) > 1:
            authorized_party = claims.get("azp")
            if authorized_party != config.client_id:
                raise ApiError(
                    "OIDC_AUTHORIZED_PARTY_INVALID",
                    "OIDC 身份令牌校验失败",
                    status_code=400,
                )
        return claims

    async def _get_json(self, url: str, *, error_code: str) -> dict[str, Any]:
        _validate_endpoint_url(url)
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.get(url, headers={"Accept": "application/json"})
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ApiError(
                error_code,
                "OIDC 提供商连接失败",
                status_code=502,
            ) from exc
        if not isinstance(payload, dict):
            raise ApiError(
                error_code,
                "OIDC 提供商响应无效",
                status_code=502,
            )
        return payload


def create_pkce_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    import base64

    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _normalize_issuer(value: str) -> str:
    issuer = value.strip().rstrip("/")
    _validate_endpoint_url(issuer)
    return issuer


def _required_url(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ApiError(
            "OIDC_DISCOVERY_INVALID",
            "OIDC 提供商发现文档无效",
            status_code=502,
        )
    _validate_endpoint_url(value)
    return value


def _optional_url(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ApiError(
            "OIDC_DISCOVERY_INVALID",
            "OIDC 提供商发现文档无效",
            status_code=502,
        )
    _validate_endpoint_url(value)
    return value


def _validate_endpoint_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.username is not None or parsed.password is not None:
        raise ApiError(
            "OIDC_ENDPOINT_INVALID",
            "OIDC 提供商端点不合法",
            status_code=422,
        )
    if parsed.scheme == "https" and parsed.hostname:
        return
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "::1", "localhost"}:
        return
    raise ApiError(
        "OIDC_ENDPOINT_INVALID",
        "OIDC 提供商端点必须使用 HTTPS",
        status_code=422,
    )


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
