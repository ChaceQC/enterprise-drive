from __future__ import annotations

import asyncio
import ssl
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from ldap3 import ALL, BASE, SUBTREE, Connection, Server, Tls  # type: ignore[import-untyped]
from ldap3.core.exceptions import LDAPException  # type: ignore[import-untyped]
from ldap3.utils.conv import escape_filter_chars  # type: ignore[import-untyped]

from app.api.errors import ApiError
from app.infrastructure.identity.base import (
    LdapDepartmentRecord,
    LdapDirectorySnapshot,
    LdapGroupRecord,
    LdapSourceConfig,
    LdapUserRecord,
)


class Ldap3ProviderAdapter:
    def __init__(self, *, timeout_seconds: float = 10.0) -> None:
        self.timeout_seconds = timeout_seconds

    async def test_connection(self, config: LdapSourceConfig) -> dict[str, object]:
        return await asyncio.to_thread(self._test_connection, config)

    async def read_directory(
        self,
        *,
        config: LdapSourceConfig,
        mode: str,
        cursor: str | None,
        page_size: int,
    ) -> LdapDirectorySnapshot:
        return await asyncio.to_thread(
            self._read_directory,
            config,
            mode,
            cursor,
            page_size,
        )

    def _test_connection(self, config: LdapSourceConfig) -> dict[str, object]:
        connection = self._connect(config)
        try:
            ok = connection.search(
                search_base=config.base_dn,
                search_filter="(objectClass=*)",
                search_scope=BASE,
                attributes=["1.1"],
                size_limit=1,
            )
            if not ok:
                raise _ldap_error(connection, "LDAP_CONNECTION_TEST_FAILED")
            return {
                "connected": True,
                "server": _safe_server_label(config.server_url),
                "base_dn_found": bool(connection.entries),
            }
        finally:
            connection.unbind()

    def _read_directory(
        self,
        config: LdapSourceConfig,
        mode: str,
        cursor: str | None,
        page_size: int,
    ) -> LdapDirectorySnapshot:
        if mode not in {"full", "incremental"}:
            raise ApiError("LDAP_SYNC_MODE_INVALID", "LDAP 同步模式不合法", status_code=422)
        if mode == "incremental" and not cursor:
            mode = "full"

        snapshot_started_at = datetime.now(UTC).strftime("%Y%m%d%H%M%SZ")
        connection = self._connect(config)
        try:
            user_attributes = _attributes(
                config.attribute_mapping,
                (
                    "user_external_id",
                    "user_username",
                    "user_display_name",
                    "user_email",
                    "user_disabled",
                    "user_department_ids",
                    "modify_timestamp",
                ),
            )
            user_entries = self._paged_search(
                connection=connection,
                search_base=config.user_base_dn,
                search_filter=_sync_filter(
                    config.user_filter,
                    mode=mode,
                    cursor=cursor,
                    modify_attribute=config.attribute_mapping.get("modify_timestamp"),
                ),
                attributes=user_attributes,
                page_size=page_size,
            )

            department_entries: list[dict[str, Any]] = []
            if config.department_base_dn and config.department_filter:
                department_entries = self._paged_search(
                    connection=connection,
                    search_base=config.department_base_dn,
                    search_filter=_sync_filter(
                        config.department_filter,
                        mode=mode,
                        cursor=cursor,
                        modify_attribute=config.attribute_mapping.get("modify_timestamp"),
                    ),
                    attributes=_attributes(
                        config.attribute_mapping,
                        (
                            "department_external_id",
                            "department_name",
                            "department_parent_id",
                            "department_disabled",
                            "modify_timestamp",
                        ),
                    ),
                    page_size=page_size,
                )

            group_entries: list[dict[str, Any]] = []
            if config.group_base_dn and config.group_filter:
                group_entries = self._paged_search(
                    connection=connection,
                    search_base=config.group_base_dn,
                    search_filter=_sync_filter(
                        config.group_filter,
                        mode=mode,
                        cursor=cursor,
                        modify_attribute=config.attribute_mapping.get("modify_timestamp"),
                    ),
                    attributes=_attributes(
                        config.attribute_mapping,
                        (
                            "group_external_id",
                            "group_slug",
                            "group_name",
                            "group_members",
                            "group_disabled",
                            "modify_timestamp",
                        ),
                    ),
                    page_size=page_size,
                )
        finally:
            connection.unbind()

        users, user_dn_map = _normalize_users(
            entries=user_entries,
            mapping=config.attribute_mapping,
        )
        departments = _normalize_departments(
            entries=department_entries,
            mapping=config.attribute_mapping,
        )
        groups = _normalize_groups(
            entries=group_entries,
            mapping=config.attribute_mapping,
            user_dn_map=user_dn_map,
        )
        return LdapDirectorySnapshot(
            users=tuple(users),
            departments=tuple(departments),
            groups=tuple(groups),
            next_cursor=snapshot_started_at,
            diagnostics={
                "users": len(users),
                "departments": len(departments),
                "groups": len(groups),
                "mode": mode,
            },
        )

    def _connect(self, config: LdapSourceConfig) -> Connection:
        host, port, use_ssl = _server_parts(config.server_url)
        server = Server(
            host,
            port=port,
            use_ssl=use_ssl,
            connect_timeout=self.timeout_seconds,
            get_info=ALL,
            tls=Tls(validate=ssl.CERT_REQUIRED) if use_ssl else None,
        )
        try:
            connection = Connection(
                server,
                user=config.bind_dn,
                password=config.bind_password,
                auto_bind=True,
                receive_timeout=self.timeout_seconds,
                raise_exceptions=True,
            )
        except LDAPException as exc:
            raise ApiError(
                "LDAP_CONNECTION_FAILED",
                "LDAP 目录连接失败",
                status_code=502,
            ) from exc
        return connection

    @staticmethod
    def _paged_search(
        *,
        connection: Connection,
        search_base: str,
        search_filter: str,
        attributes: list[str],
        page_size: int,
    ) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        cookie: bytes | None = None
        try:
            while True:
                ok = connection.search(
                    search_base=search_base,
                    search_filter=search_filter,
                    search_scope=SUBTREE,
                    attributes=attributes,
                    paged_size=page_size,
                    paged_cookie=cookie,
                )
                if not ok:
                    raise _ldap_error(connection, "LDAP_SEARCH_FAILED")
                for entry in connection.entries:
                    entries.append(
                        {
                            "dn": str(entry.entry_dn),
                            "attributes": dict(entry.entry_attributes_as_dict),
                        }
                    )
                controls = connection.result.get("controls", {})
                page_control = controls.get("1.2.840.113556.1.4.319", {})
                value = page_control.get("value", {})
                raw_cookie = value.get("cookie")
                cookie = raw_cookie if isinstance(raw_cookie, bytes) else None
                if not cookie:
                    break
        except LDAPException as exc:
            raise ApiError(
                "LDAP_SEARCH_FAILED",
                "LDAP 目录读取失败",
                status_code=502,
            ) from exc
        return entries


def _server_parts(server_url: str) -> tuple[str, int, bool]:
    parsed = urlsplit(server_url.strip())
    if parsed.username is not None or parsed.password is not None or parsed.path not in {"", "/"}:
        raise ApiError("LDAP_SERVER_URL_INVALID", "LDAP 服务地址不合法", status_code=422)
    if parsed.scheme == "ldaps" and parsed.hostname:
        return parsed.hostname, parsed.port or 636, True
    if parsed.scheme == "ldap" and parsed.hostname in {"127.0.0.1", "::1", "localhost"}:
        return parsed.hostname, parsed.port or 389, False
    raise ApiError(
        "LDAP_SERVER_URL_INVALID",
        "LDAP 服务必须使用 LDAPS",
        status_code=422,
    )


def _sync_filter(
    base_filter: str,
    *,
    mode: str,
    cursor: str | None,
    modify_attribute: str | None,
) -> str:
    if mode != "incremental" or not cursor or not modify_attribute:
        return base_filter
    escaped_cursor = escape_filter_chars(cursor)
    return f"(&{base_filter}({modify_attribute}>={escaped_cursor}))"


def _attributes(mapping: dict[str, str], keys: tuple[str, ...]) -> list[str]:
    values = {mapping[key] for key in keys if mapping.get(key)}
    if not values:
        raise ApiError(
            "LDAP_ATTRIBUTE_MAPPING_INVALID",
            "LDAP 属性映射不完整",
            status_code=422,
        )
    return sorted(values)


def _normalize_users(
    *,
    entries: list[dict[str, Any]],
    mapping: dict[str, str],
) -> tuple[list[LdapUserRecord], dict[str, str]]:
    external_key = _mapping_value(mapping, "user_external_id")
    username_key = _mapping_value(mapping, "user_username")
    display_key = mapping.get("user_display_name") or username_key
    email_key = mapping.get("user_email")
    disabled_key = mapping.get("user_disabled")
    departments_key = mapping.get("user_department_ids")

    records: list[LdapUserRecord] = []
    dn_map: dict[str, str] = {}
    for entry in entries:
        attributes = _entry_attributes(entry)
        external_id = _required_attribute(attributes, external_key)
        username = _required_attribute(attributes, username_key)
        display_name = _first_attribute(attributes, display_key) or username
        record = LdapUserRecord(
            external_id=external_id,
            username=username,
            display_name=display_name,
            email=_first_attribute(attributes, email_key),
            enabled=not _attribute_truthy(attributes, disabled_key),
            department_external_ids=tuple(_attribute_values(attributes, departments_key)),
        )
        records.append(record)
        dn_map[str(entry["dn"]).casefold()] = external_id
    records.sort(key=lambda item: item.external_id)
    return records, dn_map


def _normalize_departments(
    *,
    entries: list[dict[str, Any]],
    mapping: dict[str, str],
) -> list[LdapDepartmentRecord]:
    if not entries:
        return []
    external_key = _mapping_value(mapping, "department_external_id")
    name_key = _mapping_value(mapping, "department_name")
    parent_key = mapping.get("department_parent_id")
    disabled_key = mapping.get("department_disabled")
    records = [
        LdapDepartmentRecord(
            external_id=_required_attribute(_entry_attributes(entry), external_key),
            name=_required_attribute(_entry_attributes(entry), name_key),
            parent_external_id=_first_attribute(_entry_attributes(entry), parent_key),
            enabled=not _attribute_truthy(_entry_attributes(entry), disabled_key),
        )
        for entry in entries
    ]
    records.sort(key=lambda item: item.external_id)
    return records


def _normalize_groups(
    *,
    entries: list[dict[str, Any]],
    mapping: dict[str, str],
    user_dn_map: dict[str, str],
) -> list[LdapGroupRecord]:
    if not entries:
        return []
    external_key = _mapping_value(mapping, "group_external_id")
    slug_key = mapping.get("group_slug") or external_key
    name_key = _mapping_value(mapping, "group_name")
    members_key = mapping.get("group_members")
    disabled_key = mapping.get("group_disabled")
    records: list[LdapGroupRecord] = []
    for entry in entries:
        attributes = _entry_attributes(entry)
        raw_members = _attribute_values(attributes, members_key)
        members = [user_dn_map.get(member.casefold(), member) for member in raw_members]
        records.append(
            LdapGroupRecord(
                external_id=_required_attribute(attributes, external_key),
                slug=_required_attribute(attributes, slug_key),
                name=_required_attribute(attributes, name_key),
                member_external_ids=tuple(sorted(set(members))),
                enabled=not _attribute_truthy(attributes, disabled_key),
            )
        )
    records.sort(key=lambda item: item.external_id)
    return records


def _mapping_value(mapping: dict[str, str], key: str) -> str:
    value = mapping.get(key)
    if not value:
        raise ApiError(
            "LDAP_ATTRIBUTE_MAPPING_INVALID",
            "LDAP 属性映射不完整",
            status_code=422,
        )
    return value


def _entry_attributes(entry: dict[str, Any]) -> dict[str, Any]:
    attributes = entry.get("attributes")
    if not isinstance(attributes, dict):
        return {}
    return attributes


def _required_attribute(attributes: dict[str, Any], key: str) -> str:
    value = _first_attribute(attributes, key)
    if value is None:
        raise ApiError(
            "LDAP_ENTRY_INVALID",
            "LDAP 条目缺少稳定标识或必需属性",
            status_code=422,
        )
    return value


def _first_attribute(attributes: dict[str, Any], key: str | None) -> str | None:
    values = _attribute_values(attributes, key)
    return values[0] if values else None


def _attribute_values(attributes: dict[str, Any], key: str | None) -> list[str]:
    if not key:
        return []
    value = attributes.get(key)
    raw_values = value if isinstance(value, (list, tuple, set)) else [value]
    result: list[str] = []
    for item in raw_values:
        if item is None:
            continue
        normalized = item.hex() if isinstance(item, bytes) else str(item).strip()
        if normalized:
            result.append(normalized)
    return result


def _attribute_truthy(attributes: dict[str, Any], key: str | None) -> bool:
    value = _first_attribute(attributes, key)
    return value is not None and value.casefold() in {
        "1",
        "true",
        "yes",
        "disabled",
        "inactive",
        "locked",
    }


def _ldap_error(connection: Connection, code: str) -> ApiError:
    description = str(connection.result.get("description") or "ldap_error")
    return ApiError(
        code,
        "LDAP 目录操作失败",
        status_code=502,
        details={"reason": description},
    )


def _safe_server_label(server_url: str) -> str:
    parsed = urlsplit(server_url)
    host = parsed.hostname or "unknown"
    return f"{parsed.scheme}://{host}:{parsed.port or (636 if parsed.scheme == 'ldaps' else 389)}"
