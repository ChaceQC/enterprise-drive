from __future__ import annotations

from fastapi import APIRouter, Request

from app.modules.auth.router import router as auth_router

router = APIRouter()
router.include_router(auth_router, prefix="/auth", tags=["auth"])


@router.get("/ping", tags=["system"])
async def ping(request: Request) -> dict[str, str]:
    request_id = getattr(request.state, "request_id", "unknown")
    return {"message": "pong", "request_id": str(request_id)}
