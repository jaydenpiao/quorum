"""Image-push evidence events for the deploy-agent dog-food loop."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.app.domain.models import EventEnvelope
from apps.api.app.main import app
from apps.api.app.services.state_store import StateStore
from tests._helpers import AUTH


client = TestClient(app)

_DIGEST = "sha256:" + "a" * 64


def _payload() -> dict[str, str]:
    return {
        "commit_sha": "d" * 40,
        "workflow_run_id": "24922064550",
        "workflow_url": "https://github.com/jaydenpiao/quorum/actions/runs/24922064550",
        "staging_image_ref": f"registry.fly.io/quorum-staging@{_DIGEST}",
        "staging_digest": _DIGEST,
        "prod_image_ref": f"registry.fly.io/quorum-prod@{_DIGEST}",
        "prod_digest": _DIGEST,
    }


def test_image_push_evidence_route_emits_event_and_reduces_state() -> None:
    client.post("/api/v1/demo/incident", headers=AUTH)

    response = client.post("/api/v1/image-pushes", json=_payload(), headers=AUTH)

    assert response.status_code == 200
    record = response.json()
    assert record["id"].startswith("imgpush_")
    assert record["reported_by"] == "test-operator"
    assert record["staging_image_ref"] == f"registry.fly.io/quorum-staging@{_DIGEST}"
    assert record["prod_image_ref"] == f"registry.fly.io/quorum-prod@{_DIGEST}"

    events = client.get("/api/v1/events").json()
    image_events = [e for e in events if e["event_type"] == "image_push_completed"]
    assert len(image_events) == 2
    assert image_events[-1]["entity_type"] == "image_push"
    assert image_events[-1]["entity_id"] == record["id"]
    assert image_events[-1]["payload"] == record

    state = client.get("/api/v1/state").json()
    assert record in state["image_pushes"]


def test_image_push_evidence_rejects_mutable_tags() -> None:
    payload = _payload()
    payload["staging_image_ref"] = "registry.fly.io/quorum-staging:latest"

    response = client.post("/api/v1/image-pushes", json=payload, headers=AUTH)

    assert response.status_code == 422
    assert "sha256" in response.text


def test_image_push_evidence_requires_authentication() -> None:
    response = client.post("/api/v1/image-pushes", json=_payload())

    assert response.status_code == 401


def test_state_store_reduces_image_push_completed() -> None:
    store = StateStore()
    payload = {
        **_payload(),
        "id": "imgpush_abc123",
        "reported_by": "deploy-llm-agent",
        "created_at": "2026-04-25T00:00:00Z",
    }
    event = EventEnvelope(
        event_type="image_push_completed",
        entity_type="image_push",
        entity_id="imgpush_abc123",
        payload=payload,
    )

    store.apply(event)

    assert store.snapshot()["image_pushes"] == [payload]
