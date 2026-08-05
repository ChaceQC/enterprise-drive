from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import uuid4

import httpx
from minio import Minio
from minio.commonconfig import Tags


class ObjectStorageAdminError(RuntimeError):
    """对象存储管理命令的受控失败。"""


@dataclass(frozen=True)
class S3Connection:
    endpoint_url: str
    access_key: str
    secret_key: str
    bucket: str
    region: str = "us-east-1"

    @property
    def public_description(self) -> dict[str, str]:
        return {
            "endpoint_url": _public_endpoint_url(self.endpoint_url),
            "bucket": self.bucket,
            "region": self.region,
        }

    @property
    def storage_identity(self) -> tuple[str, str]:
        endpoint = self.endpoint_url.rstrip("/").lower()
        return endpoint, self.bucket


def build_client(connection: S3Connection) -> Minio:
    parsed_endpoint = urlsplit(connection.endpoint_url)
    endpoint = parsed_endpoint.netloc or parsed_endpoint.path
    if not endpoint:
        raise ObjectStorageAdminError("S3 endpoint is empty")
    return Minio(
        endpoint,
        access_key=connection.access_key,
        secret_key=connection.secret_key,
        region=connection.region,
        secure=parsed_endpoint.scheme == "https",
    )


def ensure_bucket(client: Minio, connection: S3Connection) -> bool:
    try:
        if client.bucket_exists(connection.bucket):
            return False
        client.make_bucket(connection.bucket, location=connection.region)
        return True
    except Exception as exc:
        raise ObjectStorageAdminError(
            f"bucket initialization failed: {type(exc).__name__}"
        ) from None


def initialize_storage(
    client: Minio,
    connection: S3Connection,
    *,
    allowed_origin: str,
    denied_origin: str,
    http_client: httpx.Client | None = None,
) -> dict[str, Any]:
    if not allowed_origin.strip():
        raise ObjectStorageAdminError("allowed CORS origin is required")
    if allowed_origin == denied_origin:
        raise ObjectStorageAdminError("allowed and denied CORS origins must differ")

    created = ensure_bucket(client, connection)
    probe_key = f"_admin/probe-{uuid4()}.txt"
    probe_content = f"enterprise-drive-s3-probe:{uuid4()}".encode()
    owned_http_client = http_client is None
    requester = http_client or httpx.Client(timeout=15, follow_redirects=False)
    cleanup_required = False
    checks: dict[str, bool] = {}

    try:
        put_url = _presigned_url(client, "PUT", connection.bucket, probe_key)
        put_response = requester.put(
            put_url,
            content=probe_content,
            headers={"Content-Type": "text/plain"},
        )
        _require_status(put_response, {200, 201, 204}, "signed PUT")
        cleanup_required = True
        checks["signed_put"] = True

        get_url = _presigned_url(client, "GET", connection.bucket, probe_key)
        get_response = requester.get(get_url)
        _require_status(get_response, {200}, "signed GET")
        if get_response.content != probe_content:
            raise ObjectStorageAdminError("signed GET content mismatch")
        checks["signed_get"] = True

        unsigned_bucket = requester.get(_bucket_url(connection))
        _require_status(unsigned_bucket, {401, 403}, "unsigned bucket rejection")
        checks["unsigned_bucket_rejected"] = True

        unsigned_object = requester.get(_object_url(connection, probe_key))
        _require_status(unsigned_object, {401, 403}, "unsigned object rejection")
        checks["unsigned_object_rejected"] = True

        preflight_headers = {
            "Origin": allowed_origin,
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "content-type",
        }
        positive_cors = requester.options(put_url, headers=preflight_headers)
        _require_status(positive_cors, {200, 204}, "allowed CORS preflight")
        allowed_origin_header = positive_cors.headers.get("access-control-allow-origin", "")
        allowed_methods = {
            item.strip().upper()
            for item in positive_cors.headers.get("access-control-allow-methods", "").split(",")
            if item.strip()
        }
        if allowed_origin_header not in {allowed_origin, "*"} or "PUT" not in allowed_methods:
            raise ObjectStorageAdminError("allowed CORS origin or method was not accepted")
        checks["cors_allowed_origin"] = True

        negative_headers = dict(preflight_headers)
        negative_headers["Origin"] = denied_origin
        negative_cors = requester.options(put_url, headers=negative_headers)
        denied_origin_header = negative_cors.headers.get("access-control-allow-origin", "")
        if denied_origin_header in {denied_origin, "*"}:
            raise ObjectStorageAdminError("denied CORS origin was accepted")
        checks["cors_denied_origin"] = True

        delete_url = _presigned_url(client, "DELETE", connection.bucket, probe_key)
        delete_response = requester.delete(delete_url)
        _require_status(delete_response, {200, 202, 204}, "signed DELETE")
        cleanup_required = False
        checks["signed_delete"] = True

        deleted_get = requester.get(get_url)
        _require_status(deleted_get, {404}, "signed GET after DELETE")
        checks["delete_verified"] = True
    except ObjectStorageAdminError:
        raise
    except Exception as exc:
        raise ObjectStorageAdminError(
            f"storage initialization failed: {type(exc).__name__}"
        ) from None
    finally:
        if cleanup_required:
            with suppress(Exception):
                client.remove_object(connection.bucket, probe_key)
        if owned_http_client:
            requester.close()

    return {
        "status": "ok",
        "storage": connection.public_description,
        "bucket_created": created,
        "checks": checks,
    }


def inventory_storage(
    client: Minio,
    connection: S3Connection,
    *,
    prefix: str = "",
) -> dict[str, Any]:
    objects: list[dict[str, Any]] = []
    try:
        listed_objects = client.list_objects(connection.bucket, prefix=prefix, recursive=True)
        for listed in listed_objects:
            key = listed.object_name
            if key is None:
                continue
            stat = client.stat_object(connection.bucket, key)
            tags = client.get_object_tags(connection.bucket, key)
            objects.append(
                {
                    "key": key,
                    "size": int(stat.size or 0),
                    "sha256": _object_sha256(client, connection.bucket, key),
                    "content_type": _content_type(stat),
                    "user_metadata": _user_metadata(stat),
                    "tags": dict(sorted((tags or {}).items())),
                }
            )
    except Exception as exc:
        raise ObjectStorageAdminError(f"inventory failed: {type(exc).__name__}") from None

    objects.sort(key=lambda item: str(item["key"]))
    return {
        "status": "ok",
        "storage": connection.public_description,
        "prefix": prefix,
        "object_count": len(objects),
        "total_size": sum(int(item["size"]) for item in objects),
        "objects": objects,
    }


def migrate_storage(
    source_client: Minio,
    source: S3Connection,
    target_client: Minio,
    target: S3Connection,
    *,
    apply: bool = False,
    prefix: str = "",
) -> dict[str, Any]:
    if source.storage_identity == target.storage_identity:
        raise ObjectStorageAdminError("source and target storage locations are identical")

    multipart_report = _inspect_incomplete_multipart_uploads(
        source_client,
        source.bucket,
        prefix=prefix,
    )
    if apply and (
        multipart_report.get("detection") != "complete" or int(multipart_report.get("count", 0)) > 0
    ):
        return {
            "status": "failed",
            "mode": "apply",
            "source": source.public_description,
            "target": target.public_description,
            "prefix": prefix,
            "multipart_uploads": multipart_report,
            "object_count": 0,
            "records": [],
            "blocker": "incomplete multipart state must be empty and fully detectable",
        }

    if apply:
        ensure_bucket(target_client, target)

    records: list[dict[str, Any]] = []
    failed = False

    try:
        source_objects = source_client.list_objects(source.bucket, prefix=prefix, recursive=True)
        for listed in source_objects:
            key = listed.object_name
            if key is None:
                continue
            stat = source_client.stat_object(source.bucket, key)
            source_size = int(stat.size or 0)
            source_hash = _object_sha256(source_client, source.bucket, key)
            content_type = _content_type(stat)
            metadata = _user_metadata(stat)
            source_tags = source_client.get_object_tags(source.bucket, key)
            tag_values = dict(sorted((source_tags or {}).items()))
            record: dict[str, Any] = {
                "key": key,
                "source_size": source_size,
                "source_sha256": source_hash,
                "content_type": content_type,
                "user_metadata": metadata,
                "tags": tag_values,
                "action": "would_copy" if not apply else "copied",
            }

            if apply:
                _stream_copy_object(
                    source_client,
                    source,
                    target_client,
                    target,
                    key=key,
                    size=source_size,
                    content_type=content_type,
                    metadata=metadata,
                    tags=tag_values,
                )
                target_stat = target_client.stat_object(target.bucket, key)
                target_hash = _object_sha256(target_client, target.bucket, key)
                target_metadata = _user_metadata(target_stat)
                target_tags = dict(
                    sorted((target_client.get_object_tags(target.bucket, key) or {}).items())
                )
                verification = {
                    "size": int(target_stat.size or 0) == source_size,
                    "sha256": target_hash == source_hash,
                    "content_type": _content_type(target_stat) == content_type,
                    "user_metadata": target_metadata == metadata,
                    "tags": target_tags == tag_values,
                }
                record["target_size"] = int(target_stat.size or 0)
                record["target_sha256"] = target_hash
                record["verification"] = verification
                if not all(verification.values()):
                    record["action"] = "verification_failed"
                    failed = True
            records.append(record)
            if failed:
                break
    except Exception as exc:
        records.append(
            {
                "action": "failed",
                "error_type": type(exc).__name__,
            }
        )
        failed = True

    return {
        "status": "failed" if failed else "ok",
        "mode": "apply" if apply else "dry-run",
        "source": source.public_description,
        "target": target.public_description,
        "prefix": prefix,
        "multipart_uploads": multipart_report,
        "object_count": len([record for record in records if "key" in record]),
        "records": records,
    }


def probe_put(
    client: Minio,
    connection: S3Connection,
    *,
    key: str,
    value: bytes,
    content_type: str,
) -> None:
    if not key:
        raise ObjectStorageAdminError("probe key is required")
    ensure_bucket(client, connection)
    try:
        client.put_object(
            connection.bucket,
            key,
            BytesIO(value),
            length=len(value),
            content_type=content_type,
        )
    except Exception as exc:
        raise ObjectStorageAdminError(f"probe PUT failed: {type(exc).__name__}") from None


def probe_get(client: Minio, connection: S3Connection, *, key: str) -> bytes:
    if not key:
        raise ObjectStorageAdminError("probe key is required")
    response = None
    try:
        response = client.get_object(connection.bucket, key)
        return bytes(response.read())
    except Exception as exc:
        raise ObjectStorageAdminError(f"probe GET failed: {type(exc).__name__}") from None
    finally:
        if response is not None:
            response.close()
            response.release_conn()


def _stream_copy_object(
    source_client: Minio,
    source: S3Connection,
    target_client: Minio,
    target: S3Connection,
    *,
    key: str,
    size: int,
    content_type: str,
    metadata: dict[str, str],
    tags: dict[str, str],
) -> None:
    response = source_client.get_object(source.bucket, key)
    try:
        target_client.put_object(
            target.bucket,
            key,
            response,
            length=size,
            content_type=content_type,
            metadata=metadata,
            tags=_object_tags(tags),
            num_parallel_uploads=1,
        )
    finally:
        response.close()
        response.release_conn()


def _object_sha256(client: Minio, bucket: str, key: str) -> str:
    response = client.get_object(bucket, key)
    digest = hashlib.sha256()
    try:
        for chunk in response.stream(1024 * 1024):
            if chunk:
                digest.update(chunk)
    finally:
        response.close()
        response.release_conn()
    return digest.hexdigest()


def _user_metadata(stat: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_key, raw_value in dict(stat.metadata or {}).items():
        key = str(raw_key)
        if key.lower().startswith("x-amz-meta-"):
            result[key[len("x-amz-meta-") :].lower()] = str(raw_value)
    return dict(sorted(result.items()))


def _content_type(stat: Any) -> str:
    if stat.content_type:
        return str(stat.content_type)
    for raw_key, raw_value in dict(stat.metadata or {}).items():
        if str(raw_key).lower() == "content-type":
            return str(raw_value)
    return "application/octet-stream"


def _object_tags(values: dict[str, str]) -> Tags | None:
    if not values:
        return None
    tags = Tags.new_object_tags()
    for key, value in values.items():
        tags[key] = value
    return tags


def _inspect_incomplete_multipart_uploads(
    client: Minio,
    bucket: str,
    *,
    prefix: str,
) -> dict[str, Any]:
    list_uploads = getattr(client, "_list_multipart_uploads", None)
    if not callable(list_uploads):
        return {
            "migrated": False,
            "detection": "unavailable",
            "reason": "client_has_no_list_multipart_uploads_api",
        }
    try:
        result = list_uploads(bucket, prefix=prefix, max_uploads=1000)
        uploads = [
            {
                "key": upload.object_name,
                "upload_id": upload.upload_id,
            }
            for upload in result.uploads
        ]
        return {
            "migrated": False,
            "detection": "complete" if not result.is_truncated else "truncated",
            "count": len(uploads),
            "uploads": uploads,
            "note": "incomplete multipart uploads are reported but never migrated",
        }
    except Exception as exc:
        return {
            "migrated": False,
            "detection": "unavailable",
            "reason": f"list_multipart_uploads_failed:{type(exc).__name__}",
            "note": "incomplete multipart uploads are not migrated",
        }


def _presigned_url(client: Minio, method: str, bucket: str, key: str) -> str:
    try:
        return str(
            client.get_presigned_url(
                method,
                bucket,
                key,
                expires=timedelta(minutes=5),
            )
        )
    except Exception as exc:
        raise ObjectStorageAdminError(f"{method} presign failed: {type(exc).__name__}") from None


def _bucket_url(connection: S3Connection) -> str:
    return f"{connection.endpoint_url.rstrip('/')}/{quote(connection.bucket, safe='')}"


def _object_url(connection: S3Connection, key: str) -> str:
    return f"{_bucket_url(connection)}/{quote(key, safe='/')}"


def _public_endpoint_url(endpoint_url: str) -> str:
    parsed = urlsplit(endpoint_url)
    if not parsed.scheme:
        return endpoint_url.split("?", 1)[0].split("#", 1)[0]
    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = f"{hostname}:{parsed.port}" if parsed.port is not None else hostname
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def _require_status(response: httpx.Response, accepted: set[int], check: str) -> None:
    if response.status_code not in accepted:
        raise ObjectStorageAdminError(f"{check} failed with HTTP {response.status_code}")


def _add_connection_arguments(
    parser: argparse.ArgumentParser,
    *,
    prefix: str = "",
) -> None:
    option_prefix = f"{prefix}-" if prefix else ""
    destination_prefix = f"{prefix}_" if prefix else ""
    env_prefix = f"{prefix.upper()}_" if prefix else ""
    parser.add_argument(
        f"--{option_prefix}endpoint",
        dest=f"{destination_prefix}endpoint",
        default=_env_value(f"DRIVE_{env_prefix}S3_ENDPOINT_URL"),
    )
    parser.add_argument(
        f"--{option_prefix}access-key",
        dest=f"{destination_prefix}access_key",
        default=_env_value(f"DRIVE_{env_prefix}S3_ACCESS_KEY_ID"),
    )
    parser.add_argument(
        f"--{option_prefix}secret-key",
        dest=f"{destination_prefix}secret_key",
        default=_env_value(f"DRIVE_{env_prefix}S3_SECRET_ACCESS_KEY"),
    )
    parser.add_argument(
        f"--{option_prefix}bucket",
        dest=f"{destination_prefix}bucket",
        default=_env_value(f"DRIVE_{env_prefix}S3_BUCKET"),
    )
    parser.add_argument(
        f"--{option_prefix}region",
        dest=f"{destination_prefix}region",
        default=_env_value(f"DRIVE_{env_prefix}S3_REGION", "us-east-1"),
    )


def _connection_from_args(args: argparse.Namespace, *, prefix: str = "") -> S3Connection:
    destination_prefix = f"{prefix}_" if prefix else ""
    values = {
        name: str(getattr(args, f"{destination_prefix}{name}", "") or "").strip()
        for name in ("endpoint", "access_key", "secret_key", "bucket", "region")
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ObjectStorageAdminError("missing S3 connection fields: " + ", ".join(sorted(missing)))
    return S3Connection(
        endpoint_url=values["endpoint"],
        access_key=values["access_key"],
        secret_key=values["secret_key"],
        bucket=values["bucket"],
        region=values["region"],
    )


def _env_value(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _allowed_origin_default() -> str:
    raw_value = _env_value(
        "DRIVE_S3_ALLOWED_ORIGIN",
        _env_value("DRIVE_S3_CORS_ALLOWED_ORIGINS"),
    ).strip()
    if not raw_value:
        return ""
    if raw_value.startswith("["):
        with suppress(json.JSONDecodeError):
            values = json.loads(raw_value)
            if isinstance(values, list) and values:
                return str(values[0]).strip()
    return raw_value.split(",", 1)[0].strip()


def _write_json_report(report: dict[str, Any], output: str | None) -> None:
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized, encoding="utf-8")
    else:
        print(serialized, end="")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="S3-compatible object storage administration")
    commands = parser.add_subparsers(dest="command", required=True)

    init_parser = commands.add_parser("init", help="initialize and validate private S3 storage")
    _add_connection_arguments(init_parser)
    init_parser.add_argument(
        "--allowed-origin",
        default=_allowed_origin_default(),
    )
    init_parser.add_argument(
        "--denied-origin",
        default=_env_value("DRIVE_S3_DENIED_ORIGIN", "https://denied.invalid"),
    )
    init_parser.add_argument("--output")

    inventory_parser = commands.add_parser("inventory", help="inventory S3 objects")
    _add_connection_arguments(inventory_parser)
    inventory_parser.add_argument("--prefix", default="")
    inventory_parser.add_argument("--output")

    migrate_parser = commands.add_parser("migrate", help="migrate completed S3 objects")
    _add_connection_arguments(migrate_parser, prefix="source")
    _add_connection_arguments(migrate_parser, prefix="target")
    migrate_parser.add_argument("--prefix", default="")
    migrate_parser.add_argument("--apply", action="store_true")
    migrate_parser.add_argument("--output")

    put_parser = commands.add_parser("probe-put", help="write one probe object")
    _add_connection_arguments(put_parser)
    put_parser.add_argument("--key", default=_env_value("DRIVE_S3_PROBE_KEY"))
    put_parser.add_argument("--value", default=_env_value("DRIVE_S3_PROBE_VALUE"))
    put_parser.add_argument(
        "--content-type",
        default=_env_value("DRIVE_S3_PROBE_CONTENT_TYPE", "application/octet-stream"),
    )

    get_parser = commands.add_parser("probe-get", help="read one probe object")
    _add_connection_arguments(get_parser)
    get_parser.add_argument("--key", default=_env_value("DRIVE_S3_PROBE_KEY"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "migrate":
            source = _connection_from_args(args, prefix="source")
            target = _connection_from_args(args, prefix="target")
            report = migrate_storage(
                build_client(source),
                source,
                build_client(target),
                target,
                apply=bool(args.apply),
                prefix=str(args.prefix),
            )
            _write_json_report(report, args.output)
            return 0 if report["status"] == "ok" else 1

        connection = _connection_from_args(args)
        client = build_client(connection)
        if args.command == "init":
            report = initialize_storage(
                client,
                connection,
                allowed_origin=str(args.allowed_origin),
                denied_origin=str(args.denied_origin),
            )
            _write_json_report(report, args.output)
        elif args.command == "inventory":
            report = inventory_storage(client, connection, prefix=str(args.prefix))
            _write_json_report(report, args.output)
        elif args.command == "probe-put":
            probe_put(
                client,
                connection,
                key=str(args.key),
                value=str(args.value).encode("utf-8"),
                content_type=str(args.content_type),
            )
        elif args.command == "probe-get":
            sys.stdout.buffer.write(probe_get(client, connection, key=str(args.key)))
        else:
            raise ObjectStorageAdminError("unsupported command")
        return 0
    except ObjectStorageAdminError as exc:
        print(
            json.dumps(
                {"status": "failed", "error": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
