from __future__ import annotations

import logging
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("enterprise_drive")


class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str
    details: Any | None = None


class ApiError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: Any | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)


def _request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    if isinstance(value, str) and value:
        return value
    return "unknown"


def _response(
    *,
    status_code: int,
    code: str,
    message: str,
    request_id: str,
    details: Any | None = None,
) -> JSONResponse:
    payload = ErrorResponse(
        code=code,
        message=message,
        request_id=request_id,
        details=details,
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(exclude_none=True),
        headers={"X-Request-ID": request_id},
    )


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    api_error = cast(ApiError, exc)
    return _response(
        status_code=api_error.status_code,
        code=api_error.code,
        message=api_error.message,
        request_id=_request_id(request),
        details=api_error.details,
    )


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    http_error = cast(StarletteHTTPException, exc)
    code = "NOT_FOUND" if http_error.status_code == 404 else f"HTTP_{http_error.status_code}"
    message = "资源不存在" if http_error.status_code == 404 else str(http_error.detail)
    return _response(
        status_code=http_error.status_code,
        code=code,
        message=message,
        request_id=_request_id(request),
    )


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    validation_error = cast(RequestValidationError, exc)
    return _response(
        status_code=422,
        code="VALIDATION_ERROR",
        message="请求参数不合法",
        request_id=_request_id(request),
        details=jsonable_encoder(validation_error.errors()),
    )


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("未处理异常", exc_info=exc)
    return _response(
        status_code=500,
        code="INTERNAL_ERROR",
        message="服务暂时不可用",
        request_id=_request_id(request),
    )
