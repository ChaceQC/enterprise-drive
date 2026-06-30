from __future__ import annotations

from fastapi import APIRouter, Request

from app.modules.auth.router import router as auth_router
from app.modules.file.router import router as file_router
from app.modules.space.router import router as space_router
from app.modules.upload.router import router as upload_router

router = APIRouter()
router.include_router(auth_router, prefix="/auth", tags=["auth"])
router.include_router(space_router, prefix="/spaces", tags=["spaces"])
router.include_router(file_router, prefix="/files", tags=["files"])
router.include_router(upload_router, prefix="/uploads", tags=["uploads"])


@router.get("/ping", tags=["system"])
async def ping(request: Request) -> dict[str, str]:
    request_id = getattr(request.state, "request_id", "unknown")
    return {"message": "pong", "request_id": str(request_id)}
