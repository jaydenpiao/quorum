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

    assert payload["event_count"] >= 15
    assert len(payload["intents"]) == 1
    assert len(payload["findings"]) == 2
    assert len(payload["proposals"]) == 1
    assert len(payload["image_pushes"]) == 1

    proposal = payload["proposals"][0]
    assert proposal["action_type"] == "fly.deploy"
    assert proposal["target"] == "quorum-prod"
    assert proposal["environment"] == "prod"
    assert proposal["status"] == "executed"
    assert proposal["payload"]["app"] == "quorum-prod"
    assert proposal["payload"]["image_digest"].startswith("sha256:")
    assert [check["name"] for check in proposal["health_checks"]] == [
        "prod-readiness",
        "prod-api-health",
    ]

    image_push = payload["image_pushes"][0]
    assert image_push["prod_image_ref"].startswith("registry.fly.io/quorum-prod@sha256:")

    policy = payload["policy_decisions"][proposal["id"]]
    assert policy["allowed"] is True
    assert policy["requires_human"] is True
    assert policy["votes_required"] == 2

    votes = payload["votes"][proposal["id"]]
    assert [vote["decision"] for vote in votes] == ["approve", "approve"]

    approvals = payload["human_approvals"][proposal["id"]]
    assert [entry.get("decision", "requested") for entry in approvals] == [
        "requested",
        "granted",
    ]

    executions = payload["executions"][proposal["id"]]
    assert executions[-1]["status"] == "succeeded"
    assert executions[-1]["result"]["released_image_digest"] == proposal["payload"]["image_digest"]
    assert executions[-1]["result"]["previous_image_digest"].startswith("sha256:")

    health_checks = [
        check for checks in payload["health_check_results"].values() for check in checks
    ]
    assert [check["name"] for check in health_checks] == ["prod-readiness", "prod-api-health"]
    assert all(check["passed"] for check in health_checks)

    events = client.get("/api/v1/events").json()
    assert [event["event_type"] for event in events] == [
        "image_push_completed",
        "intent_created",
        "finding_created",
        "finding_created",
        "proposal_created",
        "policy_evaluated",
        "human_approval_requested",
        "proposal_voted",
        "proposal_voted",
        "proposal_approved",
        "human_approval_granted",
        "execution_started",
        "health_check_completed",
        "health_check_completed",
        "execution_succeeded",
    ]


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
