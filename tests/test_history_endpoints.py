"""Tests for the read-only history endpoints backed by Postgres.

Two flavors:
- Unit: when ``app.state.pg_engine is None`` (no DATABASE_URL), every
  history endpoint must return 503. These run in CI by default.
- Integration (``@pytest.mark.integration``, opt-in): populate the
  projection via PostgresProjector, then query the HTTP endpoints and
  assert filter behavior. Excluded from CI by default via the marker.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from apps.api.app.db.engine import make_engine
from apps.api.app.db.models import Base
from apps.api.app.domain.models import EventEnvelope, Finding, Intent, Proposal


# ---------------------------------------------------------------------------
# Unit: endpoint returns 503 when PG is not configured.
# ---------------------------------------------------------------------------


@pytest.fixture
def no_db_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Fresh TestClient with pg_engine explicitly None (NoOpProjector mode)."""
    from apps.api.app.main import app

    # Force 503 branch regardless of the process-level DATABASE_URL.
    monkeypatch.setattr(app.state, "pg_engine", None, raising=False)
    monkeypatch.setattr(app.state, "pg_session_factory", None, raising=False)
    return TestClient(app)


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/history/intents",
        "/api/v1/history/findings",
        "/api/v1/history/proposals",
        "/api/v1/history/votes",
        "/api/v1/history/executions",
    ],
)
def test_history_returns_503_without_database(no_db_client: TestClient, path: str) -> None:
    response = no_db_client.get(path)
    assert response.status_code == 503
    assert "postgres" in response.json()["detail"].lower()


def test_history_filters_are_bounded(no_db_client: TestClient) -> None:
    """Oversize `limit` and `offset` are rejected at the pydantic boundary."""
    response = no_db_client.get("/api/v1/history/intents?limit=9999")
    assert response.status_code == 422
    response = no_db_client.get("/api/v1/history/intents?offset=-1")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Integration: live Postgres round-trip.
# ---------------------------------------------------------------------------


def _live_engine() -> Engine | None:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return None
    return make_engine(url)


@pytest.fixture
def live_client() -> TestClient:
    engine = _live_engine()
    if engine is None:
        pytest.skip("DATABASE_URL not set; skipping history integration test")

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    from apps.api.app.main import app
    from apps.api.app.services.postgres_projector import PostgresProjector

    projector = PostgresProjector(engine)

    # Seed rows via the projector so schema ↔ handler stay in sync.
    intent = Intent(
        title="db-backed query smoke",
        description="seed for history endpoint tests",
        environment="staging",
        requested_by="integration-operator",
    )
    projector.apply(
        EventEnvelope(
            event_type="intent_created",
            entity_type="intent",
            entity_id=intent.id,
            payload=intent.model_dump(mode="json"),
        ).model_copy(update={"prev_hash": None, "hash": "h0" * 32})
    )
    finding = Finding(
        intent_id=intent.id,
        agent_id="telemetry-agent",
        summary="observed regression",
        evidence_refs=["grafana:p99"],
        confidence=0.9,
    )
    projector.apply(
        EventEnvelope(
            event_type="finding_created",
            entity_type="finding",
            entity_id=finding.id,
            payload=finding.model_dump(mode="json"),
        ).model_copy(update={"prev_hash": None, "hash": "h1" * 32})
    )
    proposal = Proposal(
        intent_id=intent.id,
        agent_id="code-agent",
        title="rollback v184",
        action_type="rollback-deploy",
        target="checkout-service",
        environment="staging",
        risk="high",
        rationale="multiple agents agree",
        evidence_refs=["deploy:v184"],
        rollback_steps=["set image to v183"],
        health_checks=[],
    )
    projector.apply(
        EventEnvelope(
            event_type="proposal_created",
            entity_type="proposal",
            entity_id=proposal.id,
            payload=proposal.model_dump(mode="json"),
        ).model_copy(update={"prev_hash": None, "hash": "h2" * 32})
    )

    app.state.pg_engine = engine
    app.state.pg_session_factory = None  # lazy-rebuild on next request
    client = TestClient(app)
    yield client
    Base.metadata.drop_all(engine)
    engine.dispose()


def _parse(client_response: Any) -> list[dict[str, Any]]:
    assert client_response.status_code == 200, client_response.text
    return list(client_response.json())


@pytest.mark.integration
def test_list_intents_filter_by_environment(live_client: TestClient) -> None:
    body = _parse(live_client.get("/api/v1/history/intents?environment=staging"))
    assert len(body) == 1
    assert body[0]["environment"] == "staging"

    body = _parse(live_client.get("/api/v1/history/intents?environment=no-such-env"))
    assert body == []


@pytest.mark.integration
def test_list_findings_filter_by_agent(live_client: TestClient) -> None:
    body = _parse(live_client.get("/api/v1/history/findings?agent_id=telemetry-agent"))
    assert len(body) == 1
    assert body[0]["agent_id"] == "telemetry-agent"
    assert body[0]["confidence"] == pytest.approx(0.9)


@pytest.mark.integration
def test_list_proposals_filter_by_status_and_risk(live_client: TestClient) -> None:
    body = _parse(live_client.get("/api/v1/history/proposals?status=pending&risk=high"))
    assert len(body) == 1
    row = body[0]
    assert row["status"] == "pending"
    assert row["risk"] == "high"
    assert row["action_type"] == "rollback-deploy"


@pytest.mark.integration
def test_list_proposals_pagination(live_client: TestClient) -> None:
    body = _parse(live_client.get("/api/v1/history/proposals?limit=1"))
    assert len(body) == 1

    body = _parse(live_client.get("/api/v1/history/proposals?limit=1&offset=1"))
    assert body == []


@pytest.mark.integration
def test_executions_endpoint_empty_until_projected(live_client: TestClient) -> None:
    body = _parse(live_client.get("/api/v1/history/executions"))
    assert body == []


@pytest.mark.integration
def test_created_at_is_iso_timestamp(live_client: TestClient) -> None:
    body = _parse(live_client.get("/api/v1/history/intents"))
    assert len(body) == 1
    # FastAPI auto-serializes datetimes to ISO 8601.
    created_at = body[0]["created_at"]
    parsed = datetime.fromisoformat(created_at)
    assert parsed.tzinfo is not None
    assert parsed.astimezone(UTC).tzinfo == UTC
