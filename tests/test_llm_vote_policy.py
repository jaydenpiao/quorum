"""Safety gates and policy caps for LLM-authored votes."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.api.app.domain.models import PolicyDecision
from apps.api.app.main import app
from apps.api.app.services import auth as auth_module
from apps.api.app.services.policy_engine import PolicyEngine
from apps.api.app.services.quorum_engine import QuorumEngine
from tests._helpers import AUTH, TEST_CODE_KEY, TEST_OPERATOR_KEY


AUTH_CODE = {"Authorization": f"Bearer {TEST_CODE_KEY}"}
AUTH_REVIEW = {"Authorization": "Bearer review-llm-key"}
AUTH_SECOND_REVIEW = {"Authorization": "Bearer second-review-llm-key"}
AUTH_DUAL_LLM = {"Authorization": "Bearer dual-llm-key"}

PROMPT_HASH = "a" * 64

_AGENTS_YAML = """
agents:
  - id: test-operator
    role: human
    can_vote: true
    can_propose: true
    api_key_hash: ""

  - id: code-agent
    role: code
    can_vote: true
    can_propose: true
    api_key_hash: ""

  - id: review-llm-agent
    role: review
    can_vote: true
    can_propose: false
    api_key_hash: ""
    allowed_vote_action_types:
      - github.add_labels
      - github.comment_issue
    llm:
      provider: anthropic
      model: claude-opus-4-7
      system_prompt_ref: prompts/review-agent.md

  - id: second-review-llm-agent
    role: review
    can_vote: true
    can_propose: false
    api_key_hash: ""
    allowed_vote_action_types:
      - github.add_labels
      - github.comment_issue
    llm:
      provider: anthropic
      model: claude-opus-4-7
      system_prompt_ref: prompts/review-agent.md

  - id: dual-llm-agent
    role: review
    can_vote: true
    can_propose: true
    api_key_hash: ""
    allowed_action_types:
      - github.comment_issue
    allowed_vote_action_types:
      - github.comment_issue
    llm:
      provider: anthropic
      model: claude-opus-4-7
      system_prompt_ref: prompts/review-agent.md
"""

_POLICY_YAML = """
protected_environments:
  - prod

denied_action_types: []

risk_rules:
  low:
    votes_required: 2
    requires_human: false
  medium:
    votes_required: 2
    requires_human: false
  high:
    votes_required: 2
    requires_human: true
  critical:
    votes_required: 3
    requires_human: true

environment_overrides:
  prod:
    minimum_votes_required: 2
    force_human_approval: true

action_type_rules:
  github.add_labels:
    votes_required: 1
    requires_human: false
  github.comment_issue:
    votes_required: 1
    requires_human: false
  github.open_pr:
    votes_required: 2
    requires_human: false

llm_vote_caps:
  default_max_counted: 0
  action_type_rules:
    github.add_labels:
      max_counted: 1
    github.comment_issue:
      max_counted: 1

rollback:
  auto_on_failed_health_checks: true
"""


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    original_agents_path = auth_module._AGENTS_YAML_PATH
    original_policy_engine = app.state.policy_engine

    agents_path = tmp_path / "agents.yaml"
    agents_path.write_text(_AGENTS_YAML, encoding="utf-8")
    policy_path = tmp_path / "policies.yaml"
    policy_path.write_text(_POLICY_YAML, encoding="utf-8")

    monkeypatch.setattr(auth_module, "_AGENTS_YAML_PATH", str(agents_path))
    monkeypatch.setenv(
        "QUORUM_API_KEYS",
        ",".join(
            [
                f"test-operator:{TEST_OPERATOR_KEY}",
                f"code-agent:{TEST_CODE_KEY}",
                "review-llm-agent:review-llm-key",
                "second-review-llm-agent:second-review-llm-key",
                "dual-llm-agent:dual-llm-key",
            ]
        ),
    )
    auth_module.reload_all_registries()
    app.state.policy_engine = PolicyEngine(policy_path)
    app.state.event_log.reset()
    app.state.state_store.reset()

    try:
        yield TestClient(app)
    finally:
        app.state.event_log.reset()
        app.state.state_store.reset()
        app.state.policy_engine = original_policy_engine
        auth_module._AGENTS_YAML_PATH = original_agents_path
        auth_module.reload_all_registries()


def _seed_intent(client: TestClient) -> str:
    response = client.post(
        "/api/v1/intents",
        headers=AUTH,
        json={"title": "llm vote", "description": "exercise review vote"},
    )
    assert response.status_code == 200
    return str(response.json()["id"])


def _proposal_body(
    intent_id: str,
    *,
    action_type: str = "github.comment_issue",
    environment: str = "local",
    risk: str = "low",
) -> dict[str, Any]:
    return {
        "intent_id": intent_id,
        "title": "review target",
        "action_type": action_type,
        "target": "owner/repo#1",
        "environment": environment,
        "risk": risk,
        "rationale": "needs a review vote",
        "rollback_steps": ["undo action"],
        "payload": {
            "owner": "owner",
            "repo": "repo",
            "issue_number": 1,
            "body": "hello",
        },
    }


def _create_proposal(
    client: TestClient,
    *,
    auth: dict[str, str] = AUTH_CODE,
    **body_updates: Any,
) -> str:
    intent_id = _seed_intent(client)
    response = client.post(
        "/api/v1/proposals",
        headers=auth,
        json=_proposal_body(intent_id, **body_updates),
    )
    assert response.status_code == 200, response.text
    return str(response.json()["proposal"]["id"])


def _llm_vote_payload(proposal_id: str) -> dict[str, str]:
    return {
        "proposal_id": proposal_id,
        "decision": "approve",
        "reason": "LLM review found the proposal low risk.",
        "llm_model": "claude-opus-4-7",
        "system_prompt_sha256": PROMPT_HASH,
        "observed_event_cursor": "evt_seen123",
    }


def _event_count() -> int:
    return len(app.state.event_log.read_all())


def _votes_for(proposal_id: str) -> list[dict[str, Any]]:
    return list(app.state.state_store.votes.get(proposal_id, []))


def test_llm_vote_with_metadata_appends_counted_vote(client: TestClient) -> None:
    proposal_id = _create_proposal(client)
    before = _event_count()

    response = client.post(
        "/api/v1/votes", headers=AUTH_REVIEW, json=_llm_vote_payload(proposal_id)
    )

    assert response.status_code == 200, response.text
    assert _event_count() == before + 1
    vote = _votes_for(proposal_id)[0]
    assert vote["agent_id"] == "review-llm-agent"
    assert vote["voter_kind"] == "llm"
    assert vote["llm_model"] == "claude-opus-4-7"
    assert vote["system_prompt_sha256"] == PROMPT_HASH
    assert vote["observed_event_cursor"] == "evt_seen123"
    assert vote["counted"] is True
    assert vote["counted_reason"] == "llm_vote_counted"


def test_llm_vote_missing_metadata_returns_422_before_mutation(client: TestClient) -> None:
    proposal_id = _create_proposal(client)
    before = _event_count()

    response = client.post(
        "/api/v1/votes",
        headers=AUTH_REVIEW,
        json={"proposal_id": proposal_id, "decision": "approve", "reason": "safe"},
    )

    assert response.status_code == 422
    assert "llm_model" in response.json()["detail"]
    assert _event_count() == before


def test_non_llm_metadata_spoof_returns_422_before_mutation(client: TestClient) -> None:
    proposal_id = _create_proposal(client)
    before = _event_count()

    response = client.post("/api/v1/votes", headers=AUTH_CODE, json=_llm_vote_payload(proposal_id))

    assert response.status_code == 422
    assert "non-llm agent" in response.json()["detail"].lower()
    assert _event_count() == before


def test_disallowed_llm_vote_action_returns_403_before_mutation(client: TestClient) -> None:
    proposal_id = _create_proposal(client, action_type="github.open_pr")
    before = _event_count()

    response = client.post(
        "/api/v1/votes", headers=AUTH_REVIEW, json=_llm_vote_payload(proposal_id)
    )

    assert response.status_code == 403
    assert "not permitted to vote" in response.json()["detail"]
    assert _event_count() == before


def test_llm_self_vote_returns_403_before_mutation(client: TestClient) -> None:
    proposal_id = _create_proposal(client, auth=AUTH_DUAL_LLM)
    before = _event_count()

    response = client.post(
        "/api/v1/votes",
        headers=AUTH_DUAL_LLM,
        json=_llm_vote_payload(proposal_id),
    )

    assert response.status_code == 403
    assert "self-vote" in response.json()["detail"]
    assert _event_count() == before


def test_protected_high_risk_llm_vote_is_recorded_but_not_counted(
    client: TestClient,
) -> None:
    proposal_id = _create_proposal(client, environment="prod", risk="high")

    response = client.post(
        "/api/v1/votes", headers=AUTH_REVIEW, json=_llm_vote_payload(proposal_id)
    )

    assert response.status_code == 200, response.text
    vote = _votes_for(proposal_id)[0]
    assert vote["voter_kind"] == "llm"
    assert vote["counted"] is False
    assert vote["counted_reason"] == "llm_vote_not_counted_for_protected_or_high_risk"
    proposal = app.state.state_store.proposals[proposal_id]
    assert proposal["status"] == "pending"


def test_llm_vote_cap_allows_only_one_counted_llm_vote(client: TestClient) -> None:
    proposal_id = _create_proposal(client)

    first = client.post("/api/v1/votes", headers=AUTH_REVIEW, json=_llm_vote_payload(proposal_id))
    second = client.post(
        "/api/v1/votes",
        headers=AUTH_SECOND_REVIEW,
        json=_llm_vote_payload(proposal_id),
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    votes = _votes_for(proposal_id)
    assert [vote["counted"] for vote in votes] == [True, False]
    assert votes[1]["counted_reason"] == "llm_vote_cap_reached"
    proposal = app.state.state_store.proposals[proposal_id]
    assert proposal["status"] == "pending"


def test_vote_requires_policy_decision_before_mutation(client: TestClient) -> None:
    from apps.api.app.domain.models import EventEnvelope, Proposal

    intent_id = _seed_intent(client)
    proposal = Proposal(**_proposal_body(intent_id), agent_id="code-agent")
    app.state.event_log.append(
        EventEnvelope(
            event_type="proposal_created",
            entity_type="proposal",
            entity_id=proposal.id,
            payload=proposal.model_dump(mode="json"),
        )
    )
    app.state.state_store.replay(app.state.event_log.read_all())
    before = _event_count()

    response = client.post(
        "/api/v1/votes",
        headers=AUTH_CODE,
        json={"proposal_id": proposal.id, "decision": "approve", "reason": "safe"},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "missing policy decision"
    assert _event_count() == before


def test_quorum_engine_ignores_uncounted_votes_but_counts_historical_votes() -> None:
    decision = PolicyDecision(
        proposal_id="proposal_x",
        allowed=True,
        requires_human=False,
        votes_required=1,
    )
    engine = QuorumEngine()

    assert engine.is_approved([{"agent_id": "legacy", "decision": "approve"}], decision) is True
    assert (
        engine.is_approved(
            [{"agent_id": "llm", "decision": "approve", "counted": False}],
            decision,
        )
        is False
    )
    assert (
        engine.is_blocked(
            [
                {"agent_id": "llm-a", "decision": "reject", "counted": False},
                {"agent_id": "llm-b", "decision": "reject", "counted": False},
            ]
        )
        is False
    )


def test_vote_projection_schema_includes_llm_metadata_columns() -> None:
    from apps.api.app.db.models import VoteRow

    columns = set(VoteRow.__table__.columns.keys())
    assert {
        "voter_kind",
        "llm_model",
        "system_prompt_sha256",
        "observed_event_cursor",
        "counted",
        "counted_reason",
    }.issubset(columns)


def test_vote_projector_persists_llm_metadata_columns() -> None:
    from sqlalchemy.dialects import postgresql

    from apps.api.app.domain.models import EventEnvelope
    from apps.api.app.services.postgres_projector import _handle_proposal_voted

    class CaptureSession:
        statement: Any | None = None

        def execute(self, statement: Any) -> None:
            self.statement = statement

    session = CaptureSession()
    event = EventEnvelope(
        event_type="proposal_voted",
        entity_type="vote",
        entity_id="vote_llm",
        payload={
            "id": "vote_llm",
            "proposal_id": "proposal_low",
            "agent_id": "review-llm-agent",
            "decision": "approve",
            "reason": "safe",
            "voter_kind": "llm",
            "llm_model": "claude-opus-4-7",
            "system_prompt_sha256": PROMPT_HASH,
            "observed_event_cursor": "evt_seen123",
            "counted": True,
            "counted_reason": "llm_vote_counted",
            "created_at": datetime.now(UTC).isoformat(),
        },
    )

    _handle_proposal_voted(session, event)  # type: ignore[arg-type]

    assert session.statement is not None
    sql = str(session.statement.compile(dialect=postgresql.dialect()))
    for column in (
        "voter_kind",
        "llm_model",
        "system_prompt_sha256",
        "observed_event_cursor",
        "counted",
        "counted_reason",
    ):
        assert column in sql


def test_vote_history_endpoint_returns_llm_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.app.api import history as history_module
    from apps.api.app.db.models import VoteRow

    row = VoteRow(
        id="vote_llm",
        proposal_id="proposal_low",
        agent_id="review-llm-agent",
        decision="approve",
        reason="safe",
        voter_kind="llm",
        llm_model="claude-opus-4-7",
        system_prompt_sha256=PROMPT_HASH,
        observed_event_cursor="evt_seen123",
        counted=True,
        counted_reason="llm_vote_counted",
        created_at=datetime.now(UTC),
    )

    class FakeRows:
        def scalars(self) -> FakeRows:
            return self

        def all(self) -> list[VoteRow]:
            return [row]

    class FakeSession:
        def __enter__(self) -> FakeSession:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, _statement: Any) -> FakeRows:
            return FakeRows()

    class FakeFactory:
        def __call__(self) -> FakeSession:
            return FakeSession()

    monkeypatch.setattr(history_module, "_require_db", lambda _request: FakeFactory())

    response = TestClient(app).get("/api/v1/history/votes")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body[0]["voter_kind"] == "llm"
    assert body[0]["llm_model"] == "claude-opus-4-7"
    assert body[0]["system_prompt_sha256"] == PROMPT_HASH
    assert body[0]["observed_event_cursor"] == "evt_seen123"
    assert body[0]["counted"] is True
    assert body[0]["counted_reason"] == "llm_vote_counted"
