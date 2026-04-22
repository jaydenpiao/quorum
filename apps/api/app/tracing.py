"""OpenTelemetry trace instrumentation for the Quorum control plane.

Export is env-gated: set ``OTEL_EXPORTER_OTLP_ENDPOINT`` to enable.
When the variable is absent or empty the function returns immediately so
local development runs with zero telemetry config and no network calls.

Environment variables
---------------------
OTEL_EXPORTER_OTLP_ENDPOINT
    Full OTLP/HTTP endpoint, e.g. ``http://localhost:4318/v1/traces``.
    Required to enable tracing.  If unset/empty, this module is a no-op.
OTEL_SERVICE_NAME
    Logical service name reported in every span.  Defaults to ``"quorum"``.
OTEL_RESOURCE_ATTRIBUTES
    Comma-separated ``key=value`` pairs forwarded verbatim to the SDK's
    ``Resource.create()`` (standard OTEL env-var passthrough).

Excluded paths
--------------
``/metrics`` and ``/health`` are excluded so Prometheus scrapes and
liveness probes do not produce spans.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

# Comma-separated regex patterns passed to FastAPIInstrumentor as excluded_urls.
# Paths that match are NOT traced, keeping liveness probes and scrape targets clean.
EXCLUDED_URLS = "/metrics,/health"

# Package version — kept as a literal to avoid import-time I/O.
_SERVICE_VERSION = "0.1.0"


def configure_tracing(app: FastAPI) -> TracerProvider | None:
    """Wire OpenTelemetry tracing into *app*.

    Parameters
    ----------
    app:
        The FastAPI application instance to instrument.

    Returns
    -------
    TracerProvider | None
        The newly created :class:`~opentelemetry.sdk.trace.TracerProvider`
        when tracing was enabled, or ``None`` when the endpoint env var was
        absent (no-op path).
    """
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        # Off by default in dev — no endpoint, no export, no warnings.
        return None

    service_name = os.environ.get("OTEL_SERVICE_NAME", "quorum").strip() or "quorum"

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": _SERVICE_VERSION,
        }
    )

    provider = TracerProvider(resource=resource)

    exporter = OTLPSpanExporter(endpoint=endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=provider,
        excluded_urls=EXCLUDED_URLS,
    )

    return provider
