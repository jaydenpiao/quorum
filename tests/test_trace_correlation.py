"""Tests for log↔trace correlation in RequestContextMiddleware.

The middleware binds ``trace_id`` and ``span_id`` into structlog contextvars
when — and only when — a valid OpenTelemetry span is active. When tracing
is not configured the bind is a no-op, so dev logs stay clean.
"""

from __future__ import annotations

import re

import structlog
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from apps.api.app.request_context import _bind_trace_ids_if_active

_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_HEX16 = re.compile(r"^[0-9a-f]{16}$")


def test_bind_is_noop_when_no_span_active() -> None:
    """Without an active span, the helper leaves contextvars alone."""
    structlog.contextvars.clear_contextvars()
    _bind_trace_ids_if_active()
    ctx = structlog.contextvars.get_contextvars()
    assert "trace_id" not in ctx
    assert "span_id" not in ctx


def test_bind_populates_ids_inside_span() -> None:
    """Inside a real SDK span, trace_id (32 hex) and span_id (16 hex) are bound."""
    # A locally-scoped TracerProvider avoids clobbering the global one.
    local_provider = TracerProvider()
    tracer = local_provider.get_tracer("test")

    structlog.contextvars.clear_contextvars()
    with tracer.start_as_current_span("unit-test-span"):
        _bind_trace_ids_if_active()
        ctx = structlog.contextvars.get_contextvars()
        assert _HEX32.match(ctx.get("trace_id", "")), f"bad trace_id: {ctx.get('trace_id')!r}"
        assert _HEX16.match(ctx.get("span_id", "")), f"bad span_id: {ctx.get('span_id')!r}"
    structlog.contextvars.clear_contextvars()


def test_unrelated_contextvars_are_not_stomped() -> None:
    """Binding trace ids must not clear the request_id already in context."""
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id="abc-123", method="GET")

    local_provider = TracerProvider()
    tracer = local_provider.get_tracer("test")
    with tracer.start_as_current_span("inner"):
        _bind_trace_ids_if_active()
        ctx = structlog.contextvars.get_contextvars()
        assert ctx.get("request_id") == "abc-123"
        assert ctx.get("method") == "GET"
        assert "trace_id" in ctx

    structlog.contextvars.clear_contextvars()


def test_get_current_span_default_is_noop() -> None:
    """Regression: default behavior of `trace.get_current_span()` is a non-recording span."""
    span_context = trace.get_current_span().get_span_context()
    assert not span_context.is_valid, (
        "Default should be NonRecordingSpan.INVALID — otherwise our no-op branch never fires"
    )
