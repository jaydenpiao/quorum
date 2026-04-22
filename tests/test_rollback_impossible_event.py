"""Event-level tests for the new ``rollback_impossible`` event type (PR C).

Covers the five create-event-type touch points:
- Identifier + record model (``RollbackImpossibleRecord``).
- Emission site (``executor._emit_rollback_impossible``) — proved via the
  end-to-end path where the actuator raises ``RollbackImpossibleError``.
- Reducer in ``StateStore`` — proposal ends in the
  ``rollback_impossible`` status.
- Docs + CHANGELOG — covered out-of-band.
- Examples — asserted here by the event payload shape.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from apps.api.app.domain.models import (
    EventEnvelope,
    HealthCheckKind,
    HealthCheckSpec,
    Proposal,
    ProposalStatus,
    RollbackImpossibleRecord,
)
from apps.api.app.services.actuators.github import (
    GitHubAppClient,
    GitHubAppConfig,
    GitHubAppLimits,
    GitHubInstallation,
)
from apps.api.app.services.event_log import EventLog
from apps.api.app.services.executor import Executor
from apps.api.app.services.policy_engine import PolicyEngine
from apps.api.app.services.state_store import StateStore


# ---------------------------------------------------------------------------
# Record model
# ---------------------------------------------------------------------------


def test_rollback_impossible_record_fields() -> None:
    rec = RollbackImpossibleRecord(
        proposal_id="proposal_abc",
        actor_id="code-agent",
        reason="merged out of band",
        actuator_state={"pr_number": 42, "merged": True},
    )
    assert rec.id.startswith("rollimp_")
    assert rec.reason == "merged out of band"
    assert rec.actuator_state == {"pr_number": 42, "merged": True}


def test_rollback_impossible_record_rejects_empty_reason() -> None:
    with pytest.raises(ValueError):
        RollbackImpossibleRecord(proposal_id="p", actor_id="a", reason="")


# ---------------------------------------------------------------------------
# State store reducer
# ---------------------------------------------------------------------------


def test_state_store_reduces_rollback_impossible(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "events.jsonl")

    # Seed a proposal so the reducer has something to flip.
    proposal = Proposal(
        intent_id="intent_abc",
        agent_id="code-agent",
        title="Open PR",
        action_type="github.open_pr",
        target="jaydenpiao/quorum",
        rationale="x",
        rollback_steps=["close PR"],
        status=ProposalStatus.executed,
    )
    log.append(
        EventEnvelope(
            event_type="proposal_created",
            entity_type="proposal",
            entity_id=proposal.id,
            payload=proposal.model_dump(mode="json"),
        )
    )
    rec = RollbackImpossibleRecord(
        proposal_id=proposal.id,
        actor_id="code-agent",
        reason="merged",
        actuator_state={"pr_number": 42},
    )
    log.append(
        EventEnvelope(
            event_type="rollback_impossible",
            entity_type="rollback_impossible",
            entity_id=rec.id,
            payload=rec.model_dump(mode="json"),
        )
    )

    store = StateStore()
    store.replay(log.read_all())

    assert store.proposals[proposal.id]["status"] == "rollback_impossible"
    assert len(store.rollbacks[proposal.id]) == 1
    assert store.rollbacks[proposal.id][0]["reason"] == "merged"


# ---------------------------------------------------------------------------
# Emission via executor — proposal ends up terminal
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def private_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")


@pytest.fixture
def http_client() -> Iterator[httpx.Client]:
    with httpx.Client() as c:
        yield c


@pytest.fixture
def gh_client(private_pem: str, http_client: httpx.Client) -> GitHubAppClient:
    cfg = GitHubAppConfig(
        app_id=42,
        installations=[GitHubInstallation(owner="jaydenpiao", repo="quorum", installation_id=7)],
        limits=GitHubAppLimits(),
    )
    return GitHubAppClient(cfg, private_key_pem=private_pem, http_client=http_client)


def _open_pr_proposal() -> Proposal:
    return Proposal(
        intent_id="intent_abc",
        agent_id="code-agent",
        title="Open patch PR",
        action_type="github.open_pr",
        target="jaydenpiao/quorum",
        rationale="x",
        rollback_steps=["close PR", "delete branch"],
        payload={
            "owner": "jaydenpiao",
            "repo": "quorum",
            "base": "feature/experiment",
            "title": "Automated patch",
            "body": "",
            "commit_message": "chore: quorum-applied patch",
            "files": [{"path": "a.py", "content": "print('a')\n"}],
        },
        health_checks=[HealthCheckSpec(name="bad", kind=HealthCheckKind.always_fail)],
        status=ProposalStatus.approved,
    )


def _token_response() -> httpx.Response:
    return httpx.Response(200, json={"token": "ghs_t", "expires_at": "2099-01-01T00:00:00Z"})


def _base_branch_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "name": "feature/experiment",
            "protected": False,
            "commit": {"sha": "base", "commit": {"tree": {"sha": "base_tree"}}},
        },
    )


def test_executor_emits_rollback_impossible_on_merged_pr(
    tmp_path: Path, gh_client: GitHubAppClient
) -> None:
    """Integration: open_pr succeeds → health check fails → rollback tries
    to close PR but finds it merged → rollback_impossible event."""
    log = EventLog(tmp_path / "events.jsonl")
    policy = PolicyEngine("config/policies.yaml")
    executor = Executor(log, policy, github_client=gh_client)
    proposal = _open_pr_proposal()
    # Seed proposal_created so the reducer below can flip status.
    log.append(
        EventEnvelope(
            event_type="proposal_created",
            entity_type="proposal",
            entity_id=proposal.id,
            payload=proposal.model_dump(mode="json"),
        )
    )

    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://api.github.com/app/installations/7/access_tokens").mock(
            return_value=_token_response()
        )
        # open_pr happy path
        mock.get("https://api.github.com/repos/jaydenpiao/quorum/branches/feature/experiment").mock(
            return_value=_base_branch_response()
        )
        mock.post("https://api.github.com/repos/jaydenpiao/quorum/git/blobs").mock(
            return_value=httpx.Response(201, json={"sha": "blob"})
        )
        mock.post("https://api.github.com/repos/jaydenpiao/quorum/git/trees").mock(
            return_value=httpx.Response(201, json={"sha": "tree"})
        )
        mock.post("https://api.github.com/repos/jaydenpiao/quorum/git/commits").mock(
            return_value=httpx.Response(201, json={"sha": "commit"})
        )
        mock.post("https://api.github.com/repos/jaydenpiao/quorum/git/refs").mock(
            return_value=httpx.Response(201, json={"ref": "refs/heads/x"})
        )
        mock.post("https://api.github.com/repos/jaydenpiao/quorum/pulls").mock(
            return_value=httpx.Response(
                201,
                json={"number": 42, "html_url": "https://github.com/jaydenpiao/quorum/pull/42"},
            )
        )
        # Rollback: PR was merged between open and rollback.
        mock.get("https://api.github.com/repos/jaydenpiao/quorum/pulls/42").mock(
            return_value=httpx.Response(200, json={"state": "closed", "merged": True, "number": 42})
        )

        outcome = executor.execute(proposal, actor_id="code-agent")

    assert outcome["status"] == "failed"
    types = [e.event_type for e in log.read_all()]
    assert "rollback_started" in types
    assert "rollback_impossible" in types
    assert "rollback_completed" not in types

    # Reducer: proposal ends in the terminal rollback_impossible status.
    store = StateStore()
    store.replay(log.read_all())
    assert store.proposals[proposal.id]["status"] == "rollback_impossible"

    # Payload carries reason + actuator_state for human reconcile.
    impossible_evt = next(e for e in log.read_all() if e.event_type == "rollback_impossible")
    assert "merged" in impossible_evt.payload["reason"].lower()
    assert impossible_evt.payload["actuator_state"]["merged"] is True
    assert impossible_evt.payload["actuator_state"]["pr_number"] == 42
