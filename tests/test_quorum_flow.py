from fastapi.testclient import TestClient

from apps.api.app.main import app
from tests._helpers import AUTH, TEST_CODE_KEY, TEST_TELEMETRY_KEY


client = TestClient(app)

# Phase 2.5 binds actor_id to the authenticated agent. To post as a specific
# agent, use that agent's key. The conftest registers:
#   test-operator   -> operator-key-dev
#   telemetry-agent -> telemetry-key-dev
#   code-agent      -> code-key-dev
AUTH_CODE = {"Authorization": f"Bearer {TEST_CODE_KEY}"}
AUTH_TELEMETRY = {"Authorization": f"Bearer {TEST_TELEMETRY_KEY}"}


def test_demo_incident_flow():
    demo = client.post("/api/v1/demo/incident", headers=AUTH)
    assert demo.status_code == 200

    state = client.get("/api/v1/state")
    assert state.status_code == 200
    payload = state.json()

    assert payload["event_count"] >= 1
    assert len(payload["intents"]) == 1
    assert len(payload["proposals"]) == 1

    proposal = payload["proposals"][0]
    assert proposal["status"] in {"executed", "rolled_back", "failed"}


def test_create_intent_proposal_vote_execute():
    client.post("/api/v1/demo/incident", headers=AUTH)  # reset to known state

    intent_resp = client.post(
        "/api/v1/intents",
        json={
            "title": "Test low-risk change",
            "description": "Try a low-risk config update",
            "environment": "local",
            "requested_by": "operator",
        },
        headers=AUTH,
    )
    assert intent_resp.status_code == 200
    intent = intent_resp.json()

    proposal_resp = client.post(
        "/api/v1/proposals",
        json={
            "intent_id": intent["id"],
            "agent_id": "code-agent",
            "title": "Apply low-risk config change",
            "action_type": "update-config",
            "target": "demo-service",
            "environment": "local",
            "risk": "low",
            "rationale": "Demonstrate successful quorum-based execution",
            "evidence_refs": ["config:demo"],
            "rollback_steps": ["restore previous config"],
            "health_checks": [{"name": "smoke", "kind": "always_pass"}],
        },
        headers=AUTH_CODE,
    )
    assert proposal_resp.status_code == 200
    proposal = proposal_resp.json()["proposal"]

    vote_1 = client.post(
        "/api/v1/votes",
        json={
            "proposal_id": proposal["id"],
            "agent_id": "telemetry-agent",
            "decision": "approve",
            "reason": "Looks safe",
        },
        headers=AUTH_TELEMETRY,
    )
    assert vote_1.status_code == 200

    vote_2 = client.post(
        "/api/v1/votes",
        json={
            "proposal_id": proposal["id"],
            "agent_id": "code-agent",
            "decision": "approve",
            "reason": "Ready to apply",
        },
        headers=AUTH_CODE,
    )
    assert vote_2.status_code == 200

    state = client.get("/api/v1/state").json()
    target = [p for p in state["proposals"] if p["id"] == proposal["id"]][0]
    assert target["status"] == "approved"

    execute = client.post(
        f"/api/v1/proposals/{proposal['id']}/execute",
        json={"actor_id": "operator"},
        headers=AUTH,
    )
    assert execute.status_code == 200
    assert execute.json()["status"] == "succeeded"
