"""Tests for structured JSON logging and request-id middleware.

Covers:
- configure_logging emits valid JSON lines to stdout
- X-Request-ID header is present and UUID-shaped on every response
- Each request gets a distinct ID
- Bearer token never leaks into log output
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
import structlog
from fastapi.testclient import TestClient

from apps.api.app.logging_config import configure_logging, get_logger
from tests._helpers import AUTH


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

UUID4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


@pytest.fixture
def client() -> TestClient:
    # Import after env is set by conftest
    from apps.api.app.main import app

    return TestClient(app)


# ---------------------------------------------------------------------------
# Test 1: configure_logging emits valid JSON to stdout
# ---------------------------------------------------------------------------


def test_configure_logging_emits_json(capsys: pytest.CaptureFixture) -> None:
    """A log call after configure_logging() writes a parseable JSON line."""
    configure_logging(level="DEBUG")
    log = get_logger("test")
    log.info("hello world", answer=42)
    captured = capsys.readouterr()
    # structlog writes to stdout; grab the first non-empty line
    lines = [ln for ln in captured.out.splitlines() if ln.strip()]
    assert lines, "Expected at least one log line on stdout"
    obj: dict[str, Any] = json.loads(lines[-1])
    assert "event" in obj
    assert "timestamp" in obj
    assert "level" in obj


# ---------------------------------------------------------------------------
# Test 2: X-Request-ID header is present and UUID4-shaped
# ---------------------------------------------------------------------------


def test_request_id_in_response_header(client: TestClient) -> None:
    """Every response must carry an X-Request-ID header that is a valid UUID4."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    rid = response.headers.get("X-Request-ID")
    assert rid is not None, "X-Request-ID header missing"
    assert UUID4_RE.match(rid), f"X-Request-ID is not a valid UUID4: {rid!r}"


# ---------------------------------------------------------------------------
# Test 3: Each request gets a different ID
# ---------------------------------------------------------------------------


def test_request_id_differs_per_request(client: TestClient) -> None:
    """Two sequential requests must produce two distinct request IDs."""
    r1 = client.get("/api/v1/health")
    r2 = client.get("/api/v1/health")
    id1 = r1.headers.get("X-Request-ID")
    id2 = r2.headers.get("X-Request-ID")
    assert id1 is not None and id2 is not None
    assert id1 != id2, "Two requests should not share the same request_id"


# ---------------------------------------------------------------------------
# Test 4: Bearer token must never appear in log events
# ---------------------------------------------------------------------------


def test_log_does_not_leak_bearer_token(client: TestClient) -> None:
    """No captured structlog event may contain the plaintext bearer token."""
    captured_events: list[dict[str, Any]] = []

    original_get_logger = structlog.get_logger

    def capturing_logger(*args, **kwargs):
        base = original_get_logger(*args, **kwargs)
        # Wrap bound methods to capture event dicts
        return base

    # We capture via a structlog processor instead
    captured_events.clear()

    def capture_processor(logger, method, event_dict):
        captured_events.append(dict(event_dict))
        return event_dict

    # Re-configure structlog with a capture processor inserted early
    configure_logging(level="DEBUG")
    existing_processors = structlog.get_config().get("processors", [])

    structlog.configure(
        processors=[capture_processor] + list(existing_processors),
    )

    try:
        client.post(
            "/api/v1/intents",
            json={
                "title": "test intent",
                "description": "desc",
                "environment": "local",
                "requested_by": "test-operator",
            },
            headers=AUTH,
        )
    finally:
        # Restore clean logging config
        configure_logging(level="DEBUG")

    token = AUTH["Authorization"].replace("Bearer ", "")
    for evt in captured_events:
        for value in evt.values():
            assert token not in str(value), f"Bearer token leaked into log event: {evt}"
