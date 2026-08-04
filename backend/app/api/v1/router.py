from __future__ import annotations

from fastapi import APIRouter, Request

from app.modules.admin.file_security_router import router as admin_file_security_router
from app.modules.admin.governance_router import router as admin_governance_router
from app.modules.admin.organization_router import router as admin_organization_router
from app.modules.admin.quota_router import router as admin_quota_router
from app.modules.admin.router import router as admin_router
from app.modules.admin.space_router import router as admin_space_router
from app.modules.auth.router import router as auth_router
from app.modules.device.router import router as device_router
from app.modules.file.acl_router import router as file_acl_router
from app.modules.file.router import router as file_router
from app.modules.identity.router import admin_router as admin_identity_router
from app.modules.identity.router import router as identity_router
from app.modules.org.directory_router import router as directory_router
from app.modules.search.router import router as search_router
from app.modules.share.router import public_router as public_share_router
from app.modules.share.router import router as share_router
from app.modules.space.router import router as space_router
from app.modules.sync.router import router as sync_router
from app.modules.upload.router import router as upload_router

router = APIRouter()
router.include_router(admin_router, prefix="/admin", tags=["admin"])
router.include_router(
    admin_governance_router,
    prefix="/admin",
    tags=["admin-governance"],
)
router.include_router(
    admin_organization_router,
    prefix="/admin",
    tags=["admin-organization"],
)
router.include_router(admin_quota_router, prefix="/admin/quotas", tags=["admin-quotas"])
router.include_router(admin_space_router, prefix="/admin/spaces", tags=["admin-spaces"])
router.include_router(
    admin_file_security_router,
    prefix="/admin/file-security",
    tags=["admin-file-security"],
)
router.include_router(
    admin_identity_router,
    prefix="/admin/identity",
    tags=["admin-identity"],
)
router.include_router(auth_router, prefix="/auth", tags=["auth"])
router.include_router(identity_router, prefix="/auth", tags=["identity"])
router.include_router(device_router, prefix="/device-sessions", tags=["device-sessions"])
router.include_router(directory_router, prefix="/directory", tags=["directory"])
router.include_router(space_router, prefix="/spaces", tags=["spaces"])
router.include_router(file_acl_router, prefix="/files", tags=["file-acl"])
router.include_router(file_router, prefix="/files", tags=["files"])
router.include_router(search_router, prefix="/search", tags=["search"])
router.include_router(sync_router, prefix="/sync", tags=["sync"])
router.include_router(share_router, prefix="/shares", tags=["shares"])
router.include_router(public_share_router, prefix="/public/shares", tags=["public-shares"])
router.include_router(upload_router, prefix="/uploads", tags=["uploads"])


@router.get("/ping", tags=["system"])
async def ping(request: Request) -> dict[str, str]:
    request_id = getattr(request.state, "request_id", "unknown")
    return {"message": "pong", "request_id": str(request_id)}
