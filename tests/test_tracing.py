"""Tests for OpenTelemetry trace instrumentation.

Covers:
- configure_tracing is a no-op when OTEL_EXPORTER_OTLP_ENDPOINT is unset
- configure_tracing creates an SDKTracerProvider when endpoint is set
- /api/v1/health and /metrics are excluded from traces (via EXCLUDED_URLS constant)
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider


# ---------------------------------------------------------------------------
# Test 1: no-op when endpoint is unset
# ---------------------------------------------------------------------------


def test_tracing_no_op_when_endpoint_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """configure_tracing must return None silently when OTEL_EXPORTER_OTLP_ENDPOINT is absent."""
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)

    from apps.api.app.tracing import configure_tracing

    app = FastAPI()
    result = configure_tracing(app)

    assert result is None, (
        "configure_tracing must return None (no-op) when endpoint env var is unset"
    )


# ---------------------------------------------------------------------------
# Test 2: SDKTracerProvider returned when endpoint is set
# ---------------------------------------------------------------------------


def test_tracing_sets_up_provider_when_endpoint_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """configure_tracing must return an SDKTracerProvider when endpoint env var is set."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318/v1/traces")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "quorum-test")

    from apps.api.app.tracing import configure_tracing

    app = FastAPI()
    provider = configure_tracing(app)

    assert provider is not None, "configure_tracing must return a provider when endpoint is set"
    assert isinstance(provider, SDKTracerProvider), (
        "configure_tracing must return an SDKTracerProvider when endpoint is set"
    )

    # Clean up: uninstrument the app to avoid polluting other tests.
    FastAPIInstrumentor().uninstrument_app(app)


# ---------------------------------------------------------------------------
# Test 3: /api/v1/health and /metrics are excluded from traces
# ---------------------------------------------------------------------------


def test_health_and_metrics_not_traced(monkeypatch: pytest.MonkeyPatch) -> None:
    """EXCLUDED_URLS must cover /metrics and /health so probes don't produce spans."""
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)

    from apps.api.app.tracing import EXCLUDED_URLS

    assert "/metrics" in EXCLUDED_URLS, "EXCLUDED_URLS must contain /metrics"
    assert "/health" in EXCLUDED_URLS, "EXCLUDED_URLS must contain /health"
