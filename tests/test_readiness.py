"""Tests for the ``GET /readiness`` endpoint.

Readiness differs from liveness:

- ``/health`` is a trivial "process is up" check.
- ``/readiness`` returns 200 only when the event-log hash chain has been
  verified (implicit: the FastAPI module only imports cleanly when
  ``event_log.verify()`` returns without raising) AND, if configured, the
  Postgres projection is reachable (``SELECT 1``).

These tests exercise all three branches by monkey-patching
``app.state.pg_engine`` — same pattern used by
``tests/test_history_endpoints.py``.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> Iterator[TestClient]:
    from apps.api.app.main import app

    with TestClient(app) as c:
        yield c


def test_readiness_200_when_pg_engine_is_none(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.app.main import app

    # No DATABASE_URL configured → readiness is satisfied by the
    # implicit chain-verify invariant alone.
    monkeypatch.setattr(app.state, "pg_engine", None, raising=False)

    response = client.get("/readiness")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_readiness_200_when_db_ping_succeeds(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real-looking engine whose ``SELECT 1`` returns happily → 200."""
    from apps.api.app.main import app

    fake_conn = MagicMock()
    fake_conn.execute.return_value = MagicMock()

    @contextmanager
    def connect() -> Iterator[MagicMock]:
        yield fake_conn

    fake_engine = MagicMock()
    fake_engine.connect = connect

    monkeypatch.setattr(app.state, "pg_engine", fake_engine, raising=False)

    response = client.get("/readiness")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert fake_conn.execute.called


def test_readiness_503_when_db_ping_raises(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Engine that raises on connect() → 503 with a non-leaky detail."""
    from apps.api.app.main import app

    class Boom(RuntimeError):
        pass

    def connect_raises() -> Any:
        raise Boom("network unreachable: 10.0.0.1:5432")

    fake_engine = MagicMock()
    fake_engine.connect = connect_raises

    monkeypatch.setattr(app.state, "pg_engine", fake_engine, raising=False)

    response = client.get("/readiness")
    assert response.status_code == 503
    body = response.json()
    assert body == {"detail": "projection not ready"}
    # The detail string must not leak the original exception (which could
    # contain connection strings, hostnames, or credentials).
    assert "10.0.0.1" not in response.text
    assert "network unreachable" not in response.text


def test_readiness_is_not_rate_limited(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fly.io polls /readiness every ~15s; it must not trip the rate limiter
    at burst frequencies. Hit it a bunch and confirm no 429.
    """
    from apps.api.app.main import app

    monkeypatch.setattr(app.state, "pg_engine", None, raising=False)

    for _ in range(30):
        response = client.get("/readiness")
        assert response.status_code == 200
