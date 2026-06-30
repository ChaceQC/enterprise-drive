from __future__ import annotations

from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp


class RequestIdMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, header_name: str = "X-Request-ID") -> None:
        super().__init__(app)
        self.header_name = header_name

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming_request_id = request.headers.get(self.header_name)
        request_id = incoming_request_id.strip() if incoming_request_id else f"req_{uuid4().hex}"

        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[self.header_name] = request_id
        return response
