from __future__ import annotations

import asyncio
import logging
from typing import Literal

from fastapi import FastAPI, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings

logger = logging.getLogger("enterprise_drive.health")


class HealthResponse(BaseModel):
    status: Literal["ok", "ready"]
    service: str
    version: str
    environment: str


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    service: str
    version: str
    environment: str
    checks: dict[str, Literal["ready", "unavailable"]]


async def _check_database_ready(settings: Settings) -> None:
    engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        poolclass=NullPool,
    )
    try:
        async with asyncio.timeout(3):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
    finally:
        await engine.dispose()


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
    async def readyz(response: Response) -> ReadinessResponse:
        try:
            await _check_database_ready(settings)
        except Exception:
            logger.exception("database readiness check failed")
            response.status_code = 503
            return ReadinessResponse(
                status="not_ready",
                service=settings.app_name,
                version=settings.app_version,
                environment=settings.environment,
                checks={"database": "unavailable"},
            )

        return ReadinessResponse(
            status="ready",
            service=settings.app_name,
            version=settings.app_version,
            environment=settings.environment,
            checks={"database": "ready"},
        )
