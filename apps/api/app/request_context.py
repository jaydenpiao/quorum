"""Request-context middleware for Quorum.

Generates a UUID4 per request, binds it (plus ``method`` and ``path``) into
structlog's contextvars so that every log line emitted during the request
automatically carries ``request_id``, ``method``, and ``path``.

When OpenTelemetry tracing is active (i.e. ``configure_tracing`` ran with
a valid ``OTEL_EXPORTER_OTLP_ENDPOINT`` and the FastAPI instrumentor has
started a span for the request), the current span's ``trace_id`` and
``span_id`` are also bound into structlog contextvars — so JSON logs and
OTLP traces can be joined after the fact by trace id. When tracing is
off, no trace fields appear in the log; the binding is strictly opt-in
based on whether a real span exists at middleware-entry time.

The same ``request_id`` is echoed back to the caller via the
``X-Request-ID`` response header, making client-side correlation trivial.

Contextvars are cleared after every request so that IDs never bleed across
requests in the same worker.
"""

from __future__ import annotations

import uuid

import structlog
from opentelemetry import trace
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


def _bind_trace_ids_if_active() -> None:
    """Bind ``trace_id`` and ``span_id`` contextvars when a real span exists.

    No-op when tracing is not configured: in that case
    ``trace.get_current_span()`` returns a ``NonRecordingSpan`` whose
    context is invalid, and we skip the bind so JSON log events stay
    uncluttered in dev.
    """
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return
    structlog.contextvars.bind_contextvars(
        trace_id=format(span_context.trace_id, "032x"),
        span_id=format(span_context.span_id, "016x"),
    )


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind request_id, method, path (and trace ids when tracing is on).

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
        _bind_trace_ids_if_active()
        try:
            response: Response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()

        response.headers["X-Request-ID"] = request_id
        return response
