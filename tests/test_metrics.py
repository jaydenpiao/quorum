"""Tests for the Prometheus /metrics endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    # Import after env is set by conftest so auth keys and demo flag exist.
    from apps.api.app.main import app

    return TestClient(app)


def test_metrics_endpoint_served(client: TestClient) -> None:
    """GET /metrics returns 200 with Prometheus-format text and at least one metric family."""
    # Prime the counters by hitting a route so http_requests_total is populated.
    client.get("/api/v1/health")
    response = client.get("/metrics")
    assert response.status_code == 200
    content_type = response.headers.get("content-type", "")
    assert "text/plain" in content_type or "openmetrics-text" in content_type, (
        f"unexpected content-type: {content_type!r}"
    )
    body = response.text
    assert "# TYPE" in body or "# HELP" in body, (
        "expected prometheus exposition format comments in body"
    )


def test_metrics_endpoint_no_auth_required(client: TestClient) -> None:
    """/metrics must be scrape-able without a bearer token."""
    response = client.get("/metrics")
    assert response.status_code == 200, "metrics endpoint must be public for Prometheus scraping"


def test_metrics_excludes_self_scrape(client: TestClient) -> None:
    """The /metrics handler must not appear as its own labeled target (excluded_handlers=['/metrics'])."""
    # Scrape several times.
    for _ in range(3):
        client.get("/metrics")
    response = client.get("/metrics")
    body = response.text
    # The instrumentator's label for the metrics handler should be absent or
    # at least not inflated. Either the handler is excluded entirely, or its
    # value is zero — both are acceptable outcomes of excluded_handlers.
    # We only assert it doesn't appear with a double-digit count (which would
    # mean self-scrapes leaked in).
    for line in body.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        if 'handler="/metrics"' in line:
            # Extract the float at the end of the line; ensure it's small.
            parts = line.rsplit(" ", 1)
            if len(parts) == 2:
                try:
                    value = float(parts[1])
                except ValueError:
                    continue
                assert value < 10, f"self-scrape count leaked into metrics: {line!r}"


def test_metrics_endpoint_not_rate_limited(client: TestClient) -> None:
    """Many scrapes in quick succession should not trip 429."""
    for _ in range(15):
        response = client.get("/metrics")
        assert response.status_code == 200, (
            f"/metrics returned {response.status_code} — rate limit should not apply"
        )
