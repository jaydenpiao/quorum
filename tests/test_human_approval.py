"""Human approval entity — end-to-end + reducer coverage.

Covers the three new event types (``human_approval_requested`` /
``_granted`` / ``_denied``), the ``POST /api/v1/approvals/{proposal_id}``
route, the execute-time gate, and the state-store reducer cases.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.app.domain.models import (
    ApprovalDecision,
    EventEnvelope,
    HumanApprovalOutcome,
    HumanApprovalRequest,
    Proposal,
    ProposalStatus,
)
from apps.api.app.services.event_log import EventLog
from apps.api.app.services.state_store import StateStore

from tests._helpers import AUTH, TEST_OPERATOR_KEY

# Keep a reference so the formatter doesn't strip the import.
__all__ = ["AUTH", "TEST_OPERATOR_KEY"]


# ---------------------------------------------------------------------------
# Reducer tests (pure state-store, no HTTP)
# ---------------------------------------------------------------------------


def _seed_proposal(log: EventLog, proposal_id: str = "proposal_abc") -> str:
    proposal = Proposal(
        id=proposal_id,
        intent_id="intent_x",
        agent_id="code-agent",
        title="t",
        action_type="config-change",
        target="svc",
        rationale="because",
        status=ProposalStatus.approved,
    )
    log.append(
        EventEnvelope(
            event_type="proposal_created",
            entity_type="proposal",
            entity_id=proposal.id,
            payload=proposal.model_dump(mode="json"),
        )
    )
    return proposal.id


def test_reducer_records_approval_request(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "events.jsonl")
    pid = _seed_proposal(log)
    req = HumanApprovalRequest(
        proposal_id=pid,
        proposer_id="code-agent",
        reasons=["environment 'prod' is protected"],
    )
    log.append(
        EventEnvelope(
            event_type="human_approval_requested",
            entity_type="human_approval_request",
            entity_id=req.id,
            payload=req.model_dump(mode="json"),
        )
    )

    store = StateStore()
    store.replay(log.read_all())
    approvals = store.human_approvals[pid]
    assert len(approvals) == 1
    assert approvals[0]["proposer_id"] == "code-agent"
    # Request alone does not grant execution.
    assert store.proposal_has_granted_approval(pid) is False


def test_reducer_unlocks_execute_on_grant(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "events.jsonl")
    pid = _seed_proposal(log)
    req = HumanApprovalRequest(proposal_id=pid, proposer_id="code-agent")
    log.append(
        EventEnvelope(
            event_type="human_approval_requested",
            entity_type="human_approval_request",
            entity_id=req.id,
            payload=req.model_dump(mode="json"),
        )
    )
    outcome = HumanApprovalOutcome(
        proposal_id=pid,
        approver_id="operator",
        decision=ApprovalDecision.granted,
        reason="reviewed the diff, LGTM",
    )
    log.append(
        EventEnvelope(
            event_type="human_approval_granted",
            entity_type="human_approval_outcome",
            entity_id=outcome.id,
            payload=outcome.model_dump(mode="json"),
        )
    )

    store = StateStore()
    store.replay(log.read_all())
    assert store.proposal_has_granted_approval(pid) is True
    # Grant does NOT flip the proposal status — execution drives it.
    assert store.proposals[pid]["status"] == ProposalStatus.approved.value


def test_reducer_flips_to_approval_denied(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "events.jsonl")
    pid = _seed_proposal(log)
    outcome = HumanApprovalOutcome(
        proposal_id=pid,
        approver_id="operator",
        decision=ApprovalDecision.denied,
        reason="too risky without incident post-mortem",
    )
    log.append(
        EventEnvelope(
            event_type="human_approval_denied",
            entity_type="human_approval_outcome",
            entity_id=outcome.id,
            payload=outcome.model_dump(mode="json"),
        )
    )

    store = StateStore()
    store.replay(log.read_all())
    assert store.proposal_has_granted_approval(pid) is False
    assert store.proposals[pid]["status"] == ProposalStatus.approval_denied.value


# ---------------------------------------------------------------------------
# Route + end-to-end tests (via TestClient against the real FastAPI app)
# ---------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    """Boot a fresh app with an isolated event log so tests don't step
    on each other's state."""
    monkeypatch.setenv(
        "QUORUM_API_KEYS",
        f"test-operator:{TEST_OPERATOR_KEY},code-agent:code-key-dev",
    )
    monkeypatch.setenv("QUORUM_ALLOW_DEMO", "true")

    # Point the app at a fresh, empty event log for this test.
    log_path = tmp_path / "events.jsonl"
    monkeypatch.setattr(
        "apps.api.app.main.system_config",
        {
            "app": {"name": "quorum", "environment": "test", "log_path": str(log_path)},
            "server": {"host": "127.0.0.1", "port": 8080},
            "ui": {"title": "t"},
            "http": {
                "cors_allowed_origins": ["http://127.0.0.1:8080"],
                "rate_limit_default": "120/minute",
                "rate_limit_demo": "5/minute",
            },
        },
        raising=False,
    )

    # Import main AFTER env is set so the EventLog picks up the tmp_path log.
    # Reloading is fiddly; use the existing app and reset its event log instead.
    from apps.api.app.main import app
    from apps.api.app.services import auth as auth_module

    auth_module.reload_all_registries()

    app.state.event_log.reset()
    app.state.state_store.reset()

    try:
        yield TestClient(app)
    finally:
        # Restore a clean auth + log state so subsequent test modules
        # (which use the conftest default env) don't see our monkeypatched
        # registry. monkeypatch restores env vars at teardown; we clear
        # the caches so the next load reads the restored env.
        auth_module.reload_all_registries()
        app.state.event_log.reset()
        app.state.state_store.reset()


def _seed_intent(client: TestClient) -> str:
    resp = client.post(
        "/api/v1/intents",
        headers=AUTH,
        json={"title": "t", "description": "d"},
    )
    assert resp.status_code == 200
    return str(resp.json()["id"])


def _post_proposal(
    client: TestClient,
    intent_id: str,
    *,
    risk: str = "high",  # high defaults to requires_human=True in policies.yaml
) -> tuple[str, bool]:
    resp = client.post(
        "/api/v1/proposals",
        headers=AUTH,
        json={
            "intent_id": intent_id,
            "title": "sensitive change",
            "action_type": "config-change",
            "target": "svc",
            "risk": risk,
            "rationale": "because",
            "rollback_steps": ["revert"],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return body["proposal"]["id"], body["policy_decision"]["requires_human"]


def _vote_through(client: TestClient, proposal_id: str) -> None:
    """Two approve votes from distinct agents to clear the risk_rules quorum."""
    for key, agent_id in (
        (TEST_OPERATOR_KEY, "test-operator"),
        ("code-key-dev", "code-agent"),
    ):
        resp = client.post(
            "/api/v1/votes",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "proposal_id": proposal_id,
                "agent_id": agent_id,
                "decision": "approve",
                "reason": "ok",
            },
        )
        assert resp.status_code == 200, resp.text


def test_requires_human_proposal_emits_approval_request(client: TestClient) -> None:
    """POST /proposals with risk=high → policy.requires_human=True →
    emits a human_approval_requested event."""
    intent_id = _seed_intent(client)
    proposal_id, requires_human = _post_proposal(client, intent_id, risk="high")
    assert requires_human is True

    events = client.get("/api/v1/events").json()
    types = [e["event_type"] for e in events]
    assert "human_approval_requested" in types


def test_execute_blocked_without_approval(client: TestClient) -> None:
    intent_id = _seed_intent(client)
    proposal_id, _ = _post_proposal(client, intent_id, risk="high")
    _vote_through(client, proposal_id)

    resp = client.post(
        f"/api/v1/proposals/{proposal_id}/execute",
        headers=AUTH,
        json={},
    )
    assert resp.status_code == 403
    assert "requires human approval" in resp.json()["detail"]


def test_execute_succeeds_after_grant(client: TestClient) -> None:
    intent_id = _seed_intent(client)
    proposal_id, _ = _post_proposal(client, intent_id, risk="high")
    _vote_through(client, proposal_id)

    grant = client.post(
        f"/api/v1/approvals/{proposal_id}",
        headers=AUTH,
        json={"decision": "granted", "reason": "diff reviewed"},
    )
    assert grant.status_code == 200
    assert grant.json()["decision"] == "granted"
    assert grant.json()["approver_id"] == "test-operator"

    exec_resp = client.post(
        f"/api/v1/proposals/{proposal_id}/execute",
        headers=AUTH,
        json={},
    )
    # Execution path runs; it may succeed or fail based on simulated checks,
    # but it's NOT 403 anymore — the gate opened.
    assert exec_resp.status_code == 200


def test_deny_flips_status_and_blocks_execute(client: TestClient) -> None:
    intent_id = _seed_intent(client)
    proposal_id, _ = _post_proposal(client, intent_id, risk="high")
    _vote_through(client, proposal_id)

    deny = client.post(
        f"/api/v1/approvals/{proposal_id}",
        headers=AUTH,
        json={"decision": "denied", "reason": "not now"},
    )
    assert deny.status_code == 200

    # Denied proposals stay not-executable. Status flipped to
    # ``approval_denied`` so the existing "must be approved" check
    # returns 409 (not 403 — 403 is for proposals that could have
    # executed but lack the approval; denied is terminal).
    exec_resp = client.post(
        f"/api/v1/proposals/{proposal_id}/execute",
        headers=AUTH,
        json={},
    )
    assert exec_resp.status_code == 409

    # Status should reflect approval_denied.
    state = client.get("/api/v1/state").json()
    target = next(p for p in state["proposals"] if p["id"] == proposal_id)
    assert target["status"] == "approval_denied"


def test_re_deciding_is_409(client: TestClient) -> None:
    intent_id = _seed_intent(client)
    proposal_id, _ = _post_proposal(client, intent_id, risk="high")

    first = client.post(
        f"/api/v1/approvals/{proposal_id}",
        headers=AUTH,
        json={"decision": "granted", "reason": "first"},
    )
    assert first.status_code == 200

    second = client.post(
        f"/api/v1/approvals/{proposal_id}",
        headers=AUTH,
        json={"decision": "denied", "reason": "wait no"},
    )
    assert second.status_code == 409
    assert "already decided" in second.json()["detail"]


def test_approval_on_non_requires_human_is_422(client: TestClient) -> None:
    """Proposals that don't need human approval reject approval attempts."""
    intent_id = _seed_intent(client)
    # risk=low → requires_human=False per policies.yaml.
    proposal_id, requires_human = _post_proposal(client, intent_id, risk="low")
    assert requires_human is False

    resp = client.post(
        f"/api/v1/approvals/{proposal_id}",
        headers=AUTH,
        json={"decision": "granted", "reason": "?"},
    )
    assert resp.status_code == 422
    assert "does not require human approval" in resp.json()["detail"]


def test_approval_on_unknown_proposal_is_404(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/approvals/proposal_does_not_exist",
        headers=AUTH,
        json={"decision": "granted"},
    )
    assert resp.status_code == 404


def test_execute_on_non_requires_human_proposal_not_blocked(client: TestClient) -> None:
    """A low-risk proposal with requires_human=False executes without
    any approval dance."""
    intent_id = _seed_intent(client)
    proposal_id, requires_human = _post_proposal(client, intent_id, risk="low")
    assert requires_human is False

    _vote_through(client, proposal_id)

    exec_resp = client.post(
        f"/api/v1/proposals/{proposal_id}/execute",
        headers=AUTH,
        json={},
    )
    assert exec_resp.status_code == 200
