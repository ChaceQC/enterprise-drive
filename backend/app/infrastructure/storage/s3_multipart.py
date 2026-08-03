from __future__ import annotations

from datetime import timedelta
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.request import OpenerDirector, ProxyHandler, Request, build_opener
from xml.etree import ElementTree

from defusedxml import ElementTree as DefusedElementTree
from defusedxml.common import DefusedXmlException
from minio import Minio

from app.infrastructure.storage.base import CompletedUploadPart


class S3MultipartControlError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int | None = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status_code = status_code


class S3MultipartControlClient:
    """Use public presigning plus standard S3 HTTP multipart control requests."""

    def __init__(
        self,
        *,
        client: Minio,
        request_timeout_seconds: int,
        presign_expires_seconds: int,
        opener: OpenerDirector | None = None,
    ) -> None:
        self._client = client
        self._request_timeout_seconds = request_timeout_seconds
        self._presign_expires_seconds = presign_expires_seconds
        self._opener = opener or build_opener(ProxyHandler({}))

    def create(
        self,
        *,
        bucket: str,
        storage_key: str,
        content_type: str | None,
    ) -> str:
        response_body = self._request(
            method="POST",
            url=self._presigned_url(
                method="POST",
                bucket=bucket,
                storage_key=storage_key,
                query_params={"uploads": ""},
            ),
            headers={"Content-Type": content_type or "application/octet-stream"},
        )
        upload_id = _xml_text(response_body, "UploadId")
        if not upload_id:
            raise S3MultipartControlError(
                code="InvalidCreateMultipartUploadResponse",
                message="S3 response did not include UploadId",
            )
        return upload_id

    def complete(
        self,
        *,
        bucket: str,
        storage_key: str,
        provider_upload_id: str,
        parts: list[CompletedUploadPart],
    ) -> str | None:
        response_body = self._request(
            method="POST",
            url=self._presigned_url(
                method="POST",
                bucket=bucket,
                storage_key=storage_key,
                query_params={"uploadId": provider_upload_id},
            ),
            body=_complete_multipart_body(parts),
            headers={"Content-Type": "application/xml"},
        )
        root = _parse_xml(response_body)
        if _local_name(root.tag) == "Error":
            code = _find_element_text(root, "Code") or "CompleteMultipartUploadFailed"
            message = _find_element_text(root, "Message") or "S3 returned an error response"
            raise S3MultipartControlError(code=code, message=message, status_code=200)
        return _find_element_text(root, "ETag")

    def abort(
        self,
        *,
        bucket: str,
        storage_key: str,
        provider_upload_id: str,
    ) -> None:
        try:
            self._request(
                method="DELETE",
                url=self._presigned_url(
                    method="DELETE",
                    bucket=bucket,
                    storage_key=storage_key,
                    query_params={"uploadId": provider_upload_id},
                ),
            )
        except S3MultipartControlError as exc:
            if exc.status_code == 404 or exc.code in {"NoSuchKey", "NoSuchUpload"}:
                return
            raise

    def _presigned_url(
        self,
        *,
        method: str,
        bucket: str,
        storage_key: str,
        query_params: dict[str, str | list[str] | tuple[str]],
    ) -> str:
        return str(
            self._client.get_presigned_url(
                method,
                bucket,
                storage_key,
                expires=timedelta(seconds=self._presign_expires_seconds),
                extra_query_params=query_params,
            )
        )

    def _request(
        self,
        *,
        method: str,
        url: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> bytes:
        request = Request(url, data=body, headers=headers or {}, method=method)
        try:
            with self._opener.open(
                request,
                timeout=self._request_timeout_seconds,
            ) as response:
                return cast(bytes, response.read())
        except HTTPError as exc:
            response_body = bytes(exc.read())
            code, message = _error_details(response_body)
            raise S3MultipartControlError(
                code=code,
                message=message,
                status_code=exc.code,
            ) from exc
        except URLError as exc:
            raise S3MultipartControlError(
                code="S3ControlRequestFailed",
                message=str(exc.reason),
            ) from exc


def _complete_multipart_body(parts: list[CompletedUploadPart]) -> bytes:
    root = ElementTree.Element("CompleteMultipartUpload")
    for part in sorted(parts, key=lambda item: item.part_no):
        part_element = ElementTree.SubElement(root, "Part")
        ElementTree.SubElement(part_element, "PartNumber").text = str(part.part_no)
        normalized_etag = part.etag.strip('"')
        ElementTree.SubElement(part_element, "ETag").text = f'"{normalized_etag}"'
    return cast(bytes, ElementTree.tostring(root, encoding="utf-8"))


def _xml_text(response_body: bytes, name: str) -> str | None:
    return _find_element_text(_parse_xml(response_body), name)


def _parse_xml(response_body: bytes) -> ElementTree.Element:
    try:
        return DefusedElementTree.fromstring(response_body)
    except (ElementTree.ParseError, DefusedXmlException) as exc:
        raise S3MultipartControlError(
            code="InvalidS3XmlResponse",
            message="S3 response was not valid XML",
        ) from exc


def _find_element_text(root: ElementTree.Element, name: str) -> str | None:
    for element in root.iter():
        if _local_name(element.tag) == name and element.text:
            return element.text.strip()
    return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _error_details(response_body: bytes) -> tuple[str, str]:
    try:
        root = DefusedElementTree.fromstring(response_body)
    except (ElementTree.ParseError, DefusedXmlException):
        return "S3ControlRequestFailed", "S3 returned an HTTP error"
    return (
        _find_element_text(root, "Code") or "S3ControlRequestFailed",
        _find_element_text(root, "Message") or "S3 returned an HTTP error",
    )
