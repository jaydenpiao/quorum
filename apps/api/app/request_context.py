"""Request-context middleware for Quorum.

Generates a UUID4 per request, binds it (plus ``method`` and ``path``) into
structlog's contextvars so that every log line emitted during the request
automatically carries ``request_id``, ``method``, and ``path``.

The same ``request_id`` is echoed back to the caller via the
``X-Request-ID`` response header, making distributed tracing trivial.

Contextvars are cleared after every request so that IDs never bleed across
requests in the same worker.
"""

from __future__ import annotations

import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind request_id, method, and path into structlog contextvars.

    Adds an ``X-Request-ID`` header to every response.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        structlog.contextvars.clear_contextvars()
        request_id = str(uuid.uuid4())
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        try:
            response: Response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()

        response.headers["X-Request-ID"] = request_id
        return response
