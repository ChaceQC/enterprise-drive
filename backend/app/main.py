from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app.api.errors import register_exception_handlers
from app.api.middleware import RequestIdMiddleware
from app.api.v1.router import router as api_v1_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.health import register_health_routes

logger = logging.getLogger("enterprise_drive")


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    configure_logging(app_settings)

    app = FastAPI(
        title=app_settings.app_name,
        version=app_settings.app_version,
        debug=app_settings.debug,
    )
    app.state.settings = app_settings

    app.add_middleware(RequestIdMiddleware, header_name=app_settings.request_id_header)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=app_settings.trusted_hosts)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    register_health_routes(app, app_settings)
    app.include_router(api_v1_router, prefix=app_settings.api_v1_prefix)
    return app


app = create_app()
