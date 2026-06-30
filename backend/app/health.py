from __future__ import annotations

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from app.core.config import Settings


class HealthResponse(BaseModel):
    status: Literal["ok", "ready"]
    service: str
    version: str
    environment: str


def register_health_routes(app: FastAPI, settings: Settings) -> None:
    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service=settings.app_name,
            version=settings.app_version,
            environment=settings.environment,
        )

    @app.get("/readyz", include_in_schema=False)
    async def readyz() -> HealthResponse:
        return HealthResponse(
            status="ready",
            service=settings.app_name,
            version=settings.app_version,
            environment=settings.environment,
        )
