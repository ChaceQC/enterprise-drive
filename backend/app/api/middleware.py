from __future__ import annotations

import logging
from time import perf_counter
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import reset_log_context, set_log_context
from app.core.metrics import record_http_request

logger = logging.getLogger("enterprise_drive.http")


class RequestIdMiddleware:
    """Attach request identity, low-cardinality HTTP metrics and request-end logs."""

    def __init__(self, app: ASGIApp, *, header_name: str = "X-Request-ID") -> None:
        self.app = app
        self.header_name = header_name

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming_request_id = Headers(scope=scope).get(self.header_name)
        request_id = incoming_request_id.strip() if incoming_request_id else f"req_{uuid4().hex}"
        state = scope.setdefault("state", {})
        state["request_id"] = request_id

        started_at = perf_counter()
        status_code = 500
        response_started = False
        context_token = set_log_context(request_id=request_id)

        async def send_with_request_id(message: Message) -> None:
            nonlocal response_started, status_code
            if message["type"] == "http.response.start":
                response_started = True
                status_code = int(message["status"])
                headers = MutableHeaders(scope=message)
                headers[self.header_name] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            duration_seconds = max(perf_counter() - started_at, 0.0)
            route = _route_template(scope)
            if scope.get("path") != "/metrics":
                record_http_request(
                    method=str(scope.get("method", "UNKNOWN")),
                    route=route,
                    status_code=status_code if response_started else 500,
                    duration_seconds=duration_seconds,
                )
                logger.log(
                    40 if status_code >= 500 else 30 if status_code >= 400 else 20,
                    "HTTP 请求完成",
                    extra={
                        "action": "http.request",
                        "status": status_code if response_started else 500,
                        "latency_ms": round(duration_seconds * 1000, 3),
                        "route": route,
                        "method": str(scope.get("method", "UNKNOWN")),
                    },
                )
            reset_log_context(context_token)


def _route_template(scope: Scope) -> str:
    fastapi_scope = scope.get("fastapi")
    if isinstance(fastapi_scope, dict):
        effective_route = fastapi_scope.get("effective_route_context")
        effective_template = getattr(effective_route, "path_format", None)
        if isinstance(effective_template, str) and effective_template.startswith("/"):
            return effective_template
    route = scope.get("route")
    template = getattr(route, "path_format", None) or getattr(route, "path", None)
    if isinstance(template, str) and template.startswith("/"):
        return template
    return "unmatched"
