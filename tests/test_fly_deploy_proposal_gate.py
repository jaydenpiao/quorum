"""Route-level gates for ``fly.deploy`` proposal safety."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.api.app.main import app
from tests._helpers import AUTH


client = TestClient(app)

_DIGEST = "sha256:" + "a" * 64


def _create_intent() -> str:
    response = client.post(
        "/api/v1/intents",
        headers=AUTH,
        json={
            "title": "Deploy main image",
            "description": "Exercise the Fly deploy proposal gate",
        },
    )
    assert response.status_code == 200
    return str(response.json()["id"])


def _proposal_body(intent_id: str, **updates: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "intent_id": intent_id,
        "title": "Deploy staging",
        "action_type": "fly.deploy",
        "target": "quorum-staging",
        "environment": "staging",
        "risk": "medium",
        "rationale": "A pushed image needs a staged deploy before prod.",
        "evidence_refs": ["evt_image_push"],
        "rollback_steps": ["redeploy previous image digest captured at deploy time"],
        "payload": {
            "app": "quorum-staging",
            "image_digest": _DIGEST,
            "strategy": "rolling",
        },
    }
    body.update(updates)
    return body


@pytest.mark.parametrize("health_checks", [None, []])
def test_fly_deploy_proposal_requires_health_checks_before_logging(
    health_checks: list[dict[str, Any]] | None,
) -> None:
    intent_id = _create_intent()
    before = client.get("/api/v1/events/verify").json()["event_count"]

    body = _proposal_body(intent_id)
    if health_checks is not None:
        body["health_checks"] = health_checks

    response = client.post("/api/v1/proposals", headers=AUTH, json=body)

    assert response.status_code == 422
    assert "fly.deploy proposals require health_checks" in str(response.json()["detail"])
    after = client.get("/api/v1/events/verify").json()["event_count"]
    assert after == before


def test_fly_deploy_proposal_accepts_explicit_health_checks() -> None:
    intent_id = _create_intent()

    response = client.post(
        "/api/v1/proposals",
        headers=AUTH,
        json=_proposal_body(
            intent_id,
            health_checks=[
                {
                    "name": "staging-readiness",
                    "kind": "http",
                    "url": "https://quorum-staging.fly.dev/readiness",
                    "expected_status": 200,
                    "timeout_seconds": 10.0,
                }
            ],
        ),
    )

    assert response.status_code == 200
    proposal = response.json()["proposal"]
    assert proposal["action_type"] == "fly.deploy"
    assert proposal["health_checks"][0]["name"] == "staging-readiness"
