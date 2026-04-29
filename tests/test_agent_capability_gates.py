"""Server-side can_propose/can_vote enforcement from config/agents.yaml."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.app.main import app
from apps.api.app.services import auth as auth_module
from apps.api.app.services.auth import can_agent_propose, can_agent_vote
from tests._helpers import AUTH, TEST_OPERATOR_KEY


_YAML = """
agents:
  - id: blocked-proposer
    role: telemetry
    api_key_hash: ""
    can_propose: false
    can_vote: true

  - id: blocked-voter
    role: telemetry
    api_key_hash: ""
    can_propose: true
    can_vote: false

  - id: allowed-agent
    role: code
    api_key_hash: ""
    can_propose: true
    can_vote: true

  - id: legacy-yaml-agent
    role: operator
    api_key_hash: ""
"""


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    original_path = auth_module._AGENTS_YAML_PATH
    path = tmp_path / "agents.yaml"
    path.write_text(_YAML, encoding="utf-8")
    monkeypatch.setattr(auth_module, "_AGENTS_YAML_PATH", str(path))
    monkeypatch.setenv(
        "QUORUM_API_KEYS",
        ",".join(
            [
                f"test-operator:{TEST_OPERATOR_KEY}",
                "blocked-proposer:blocked-proposer-key",
                "blocked-voter:blocked-voter-key",
                "allowed-agent:allowed-agent-key",
                "legacy-yaml-agent:legacy-yaml-key",
                "env-only-agent:env-only-key",
            ]
        ),
    )
    auth_module.reload_all_registries()
    app.state.event_log.reset()
    app.state.state_store.reset()

    try:
        yield TestClient(app)
    finally:
        app.state.event_log.reset()
        app.state.state_store.reset()
        auth_module._AGENTS_YAML_PATH = original_path
        auth_module.reload_all_registries()


def _seed_intent(client: TestClient) -> str:
    response = client.post(
        "/api/v1/intents",
        headers=AUTH,
        json={"title": "capability gate", "description": "test intent"},
    )
    assert response.status_code == 200
    return str(response.json()["id"])


def _proposal_payload(intent_id: str) -> dict[str, object]:
    return {
        "intent_id": intent_id,
        "title": "comment on issue",
        "action_type": "github.comment_issue",
        "target": "owner/repo#1",
        "rationale": "operator-visible proof",
        "rollback_steps": ["delete comment"],
        "payload": {
            "owner": "owner",
            "repo": "repo",
            "issue_number": 1,
            "body": "proof",
        },
    }


def _create_proposal(
    client: TestClient,
    intent_id: str,
    *,
    key: str = "allowed-agent-key",
) -> str:
    response = client.post(
        "/api/v1/proposals",
        headers={"Authorization": f"Bearer {key}"},
        json=_proposal_payload(intent_id),
    )
    assert response.status_code == 200
    return str(response.json()["proposal"]["id"])


def _event_count() -> int:
    return len(app.state.event_log.read_all())


def test_capability_loader_preserves_legacy_permissive_defaults(client: TestClient) -> None:
    assert client is not None
    assert can_agent_propose("blocked-proposer") is False
    assert can_agent_vote("blocked-voter") is False
    assert can_agent_propose("allowed-agent") is True
    assert can_agent_vote("allowed-agent") is True
    assert can_agent_propose("legacy-yaml-agent") is True
    assert can_agent_vote("legacy-yaml-agent") is True
    assert can_agent_propose("env-only-agent") is True
    assert can_agent_vote("env-only-agent") is True


def test_can_propose_false_blocks_before_event_log_mutation(client: TestClient) -> None:
    intent_id = _seed_intent(client)
    before = _event_count()

    response = client.post(
        "/api/v1/proposals",
        headers={"Authorization": "Bearer blocked-proposer-key"},
        json=_proposal_payload(intent_id),
    )

    assert response.status_code == 403
    assert "can_propose=false" in response.json()["detail"]
    assert _event_count() == before


def test_can_vote_false_blocks_before_event_log_mutation(client: TestClient) -> None:
    intent_id = _seed_intent(client)
    proposal_id = _create_proposal(client, intent_id)
    before = _event_count()

    response = client.post(
        "/api/v1/votes",
        headers={"Authorization": "Bearer blocked-voter-key"},
        json={
            "proposal_id": proposal_id,
            "decision": "approve",
            "reason": "looks safe",
        },
    )

    assert response.status_code == 403
    assert "can_vote=false" in response.json()["detail"]
    assert _event_count() == before


def test_configured_allowed_agent_can_propose_and_vote(client: TestClient) -> None:
    intent_id = _seed_intent(client)
    proposal_id = _create_proposal(client, intent_id)

    response = client.post(
        "/api/v1/votes",
        headers={"Authorization": "Bearer allowed-agent-key"},
        json={
            "proposal_id": proposal_id,
            "decision": "approve",
            "reason": "configured voter",
        },
    )

    assert response.status_code == 200


def test_unknown_env_only_agent_keeps_legacy_propose_and_vote(client: TestClient) -> None:
    intent_id = _seed_intent(client)
    proposal_id = _create_proposal(client, intent_id, key="env-only-key")

    response = client.post(
        "/api/v1/votes",
        headers={"Authorization": "Bearer env-only-key"},
        json={
            "proposal_id": proposal_id,
            "decision": "approve",
            "reason": "legacy env-only agent",
        },
    )

    assert response.status_code == 200


def test_missing_capability_fields_keep_legacy_permissive_behavior(client: TestClient) -> None:
    intent_id = _seed_intent(client)
    proposal_id = _create_proposal(client, intent_id, key="legacy-yaml-key")

    response = client.post(
        "/api/v1/votes",
        headers={"Authorization": "Bearer legacy-yaml-key"},
        json={
            "proposal_id": proposal_id,
            "decision": "approve",
            "reason": "legacy yaml agent",
        },
    )

    assert response.status_code == 200
