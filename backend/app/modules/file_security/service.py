from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.api.errors import ApiError
from app.modules.file.models import FileVersion
from app.modules.file_security.models import FileSecurityPolicy
from app.modules.file_security.repository import FileSecurityRepository

DeliveryMode = Literal["presigned", "proxy", "watermark"]


@dataclass(frozen=True, slots=True)
class FileSecurityDecision:
    policy_id: UUID | None
    policy_version: int | None
    classification: str
    download_mode: str
    dlp_status: str
    dlp_match_count: int
    dlp_allowed: bool
    dlp_reason: str | None
    watermark_text: str | None

    def audit_metadata(self) -> dict[str, object]:
        return {
            "security_policy_id": str(self.policy_id) if self.policy_id else None,
            "security_policy_version": self.policy_version,
            "classification": self.classification,
            "policy_download_mode": self.download_mode,
            "dlp_status": self.dlp_status,
            "dlp_match_count": self.dlp_match_count,
            "dlp_reason": self.dlp_reason,
        }


class FileSecurityService:
    def __init__(
        self,
        *,
        repository: FileSecurityRepository,
        enabled: bool = True,
    ) -> None:
        self.repository = repository
        self.enabled = enabled

    async def evaluate(
        self,
        *,
        tenant_id: UUID,
        file_name: str,
        mime_type: str | None,
        version: FileVersion,
    ) -> FileSecurityDecision:
        if not self.enabled:
            return _default_decision()
        policy = await self._matching_policy(
            tenant_id=tenant_id,
            file_name=file_name,
            mime_type=mime_type,
        )
        if policy is None:
            return _default_decision()
        dlp_status, match_count, allowed, reason = _evaluate_dlp(
            policy=policy,
            version=version,
        )
        return FileSecurityDecision(
            policy_id=policy.id,
            policy_version=policy.version,
            classification=policy.classification,
            download_mode=policy.download_mode,
            dlp_status=dlp_status,
            dlp_match_count=match_count,
            dlp_allowed=allowed,
            dlp_reason=reason,
            watermark_text=policy.watermark_text,
        )

    def ensure_delivery(
        self,
        *,
        decision: FileSecurityDecision,
        requested_mode: DeliveryMode,
    ) -> None:
        if not decision.dlp_allowed:
            if decision.dlp_reason == "scan_pending":
                raise ApiError(
                    "DLP_SCAN_PENDING",
                    "文件内容安全扫描尚未完成",
                    status_code=409,
                    details=decision.audit_metadata(),
                )
            raise ApiError(
                "DLP_DOWNLOAD_BLOCKED",
                "文件内容命中安全策略，下载已阻止",
                status_code=403,
                details=decision.audit_metadata(),
            )
        if decision.download_mode == "blocked":
            raise ApiError(
                "DOWNLOAD_BLOCKED_BY_POLICY",
                "文件安全策略禁止下载",
                status_code=403,
                details=decision.audit_metadata(),
            )
        if requested_mode == "presigned" and decision.download_mode == "proxy":
            raise ApiError(
                "DOWNLOAD_PROXY_REQUIRED",
                "文件安全策略要求受控代理下载",
                status_code=409,
                details=decision.audit_metadata(),
            )
        if requested_mode != "watermark" and decision.download_mode == "watermark":
            raise ApiError(
                "DOWNLOAD_WATERMARK_REQUIRED",
                "文件安全策略要求水印下载",
                status_code=409,
                details=decision.audit_metadata(),
            )
        if requested_mode == "watermark" and decision.download_mode != "watermark":
            raise ApiError(
                "DOWNLOAD_WATERMARK_NOT_REQUIRED",
                "当前文件策略未启用水印下载",
                status_code=409,
                details=decision.audit_metadata(),
            )

    async def _matching_policy(
        self,
        *,
        tenant_id: UUID,
        file_name: str,
        mime_type: str | None,
    ) -> FileSecurityPolicy | None:
        normalized_name = file_name.casefold()
        extension = ""
        if "." in normalized_name.rsplit("/", 1)[-1]:
            extension = "." + normalized_name.rsplit(".", 1)[-1]
        normalized_mime = (mime_type or "").split(";", 1)[0].strip().casefold()
        for policy in await self.repository.list_active_policies(tenant_id=tenant_id):
            extensions = {str(item).casefold() for item in policy.extensions}
            mime_prefixes = {str(item).casefold() for item in policy.mime_prefixes}
            if (extensions and extension in extensions) or (
                mime_prefixes
                and any(normalized_mime.startswith(prefix) for prefix in mime_prefixes)
            ):
                return policy
        return None


def _evaluate_dlp(
    *,
    policy: FileSecurityPolicy,
    version: FileVersion,
) -> tuple[str, int, bool, str | None]:
    keywords = [str(keyword).casefold() for keyword in policy.dlp_keywords if str(keyword).strip()]
    if not keywords:
        return "not_configured", 0, True, None
    if version.search_status != "indexed" or version.search_text is None:
        return (
            "pending",
            0,
            not policy.fail_closed,
            "scan_pending" if policy.fail_closed else "scan_unavailable_allowed",
        )
    normalized_text = version.search_text.casefold()
    match_count = sum(1 for keyword in keywords if keyword in normalized_text)
    if match_count == 0:
        return "passed", 0, True, None
    if policy.dlp_action == "block":
        return "blocked", match_count, False, "keyword_match"
    return "matched_audit", match_count, True, "keyword_match_audited"


def _default_decision() -> FileSecurityDecision:
    return FileSecurityDecision(
        policy_id=None,
        policy_version=None,
        classification="internal",
        download_mode="presigned",
        dlp_status="not_configured",
        dlp_match_count=0,
        dlp_allowed=True,
        dlp_reason=None,
        watermark_text=None,
    )
