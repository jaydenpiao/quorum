"""Executor dispatch on proposal.action_type (Phase 4 PR B2).

Covers the new ``_dispatch_action`` path: non-github actions pass
through, ``github.*`` actions route to the configured actuator, errors
are translated into scrubbed ``execution_failed`` events.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from apps.api.app.domain.models import (
    HealthCheckKind,
    HealthCheckSpec,
    Proposal,
    ProposalStatus,
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


# ---------------------------------------------------------------------------
# Fixtures
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


def _config() -> GitHubAppConfig:
    return GitHubAppConfig(
        app_id=42,
        installations=[GitHubInstallation(owner="jaydenpiao", repo="quorum", installation_id=7)],
        limits=GitHubAppLimits(),
    )


@pytest.fixture
def gh_client(private_pem: str, http_client: httpx.Client) -> GitHubAppClient:
    return GitHubAppClient(_config(), private_key_pem=private_pem, http_client=http_client)


@pytest.fixture
def event_log(tmp_path: Path) -> EventLog:
    return EventLog(tmp_path / "events.jsonl")


@pytest.fixture
def policy() -> PolicyEngine:
    return PolicyEngine("config/policies.yaml")


def _open_pr_proposal() -> Proposal:
    return Proposal(
        intent_id="intent_abc",
        agent_id="code-agent",
        title="Open patch PR",
        action_type="github.open_pr",
        target="jaydenpiao/quorum",
        rationale="observed finding requires patch",
        rollback_steps=["close PR", "delete branch"],
        payload={
            "owner": "jaydenpiao",
            "repo": "quorum",
            "base": "feature/experiment",
            "title": "Automated patch",
            "body": "opened by quorum",
            "commit_message": "chore: quorum-applied patch",
            "files": [
                {"path": "src/a.py", "content": "print('a')\n"},
                {"path": "src/b.py", "content": "print('b')\n"},
            ],
        },
        status=ProposalStatus.approved,
    )


def _token_response(token: str = "ghs_t", expires_in: int = 3600) -> httpx.Response:
    expires_at = (datetime.now(UTC) + timedelta(seconds=expires_in)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return httpx.Response(
        200,
        json={"token": token, "expires_at": expires_at, "permissions": {}},
    )


def _setup_happy_path(mock: respx.MockRouter) -> None:
    mock.post("https://api.github.com/app/installations/7/access_tokens").mock(
        return_value=_token_response()
    )
    mock.get("https://api.github.com/repos/jaydenpiao/quorum/branches/feature/experiment").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "feature/experiment",
                "protected": False,
                "commit": {
                    "sha": "base_commit",
                    "commit": {"tree": {"sha": "base_tree"}},
                },
            },
        )
    )
    mock.post("https://api.github.com/repos/jaydenpiao/quorum/git/blobs").mock(
        side_effect=[
            httpx.Response(201, json={"sha": "blob_a"}),
            httpx.Response(201, json={"sha": "blob_b"}),
        ]
    )
    mock.post("https://api.github.com/repos/jaydenpiao/quorum/git/trees").mock(
        return_value=httpx.Response(201, json={"sha": "tree"})
    )
    mock.post("https://api.github.com/repos/jaydenpiao/quorum/git/commits").mock(
        return_value=httpx.Response(201, json={"sha": "commit_xyz"})
    )
    mock.post("https://api.github.com/repos/jaydenpiao/quorum/git/refs").mock(
        return_value=httpx.Response(201, json={"ref": "refs/heads/quorum/x"})
    )
    mock.post("https://api.github.com/repos/jaydenpiao/quorum/pulls").mock(
        return_value=httpx.Response(
            201,
            json={"number": 17, "html_url": "https://github.com/jaydenpiao/quorum/pull/17"},
        )
    )


# ---------------------------------------------------------------------------
# Non-github action types pass through unchanged
# ---------------------------------------------------------------------------


def test_non_github_action_type_does_not_require_client(
    event_log: EventLog, policy: PolicyEngine
) -> None:
    executor = Executor(event_log, policy, github_client=None)
    proposal = Proposal(
        intent_id="intent_abc",
        agent_id="telemetry-agent",
        title="legacy action",
        action_type="config-change",
        target="svc",
        rationale="x",
        rollback_steps=["y"],
        health_checks=[HealthCheckSpec(name="ok", kind=HealthCheckKind.always_pass)],
        status=ProposalStatus.approved,
    )

    outcome = executor.execute(proposal, actor_id="telemetry-agent")

    assert outcome["status"] == "succeeded"
    assert outcome["result"] == {}
    types = [e.event_type for e in event_log.read_all()]
    assert "execution_started" in types
    assert "health_check_completed" in types
    assert "execution_succeeded" in types


# ---------------------------------------------------------------------------
# github.* action types with no client configured
# ---------------------------------------------------------------------------


def test_github_action_without_client_fails_fast(event_log: EventLog, policy: PolicyEngine) -> None:
    executor = Executor(event_log, policy, github_client=None)
    outcome = executor.execute(_open_pr_proposal(), actor_id="code-agent")

    assert outcome["status"] == "failed"
    assert "requires a configured GitHub App" in outcome["detail"]
    types = [e.event_type for e in event_log.read_all()]
    # Health checks do NOT run if dispatch failed.
    assert "health_check_completed" not in types
    assert "execution_failed" in types
    # Rollback still runs per auto_on_failed_health_checks default.
    assert "rollback_completed" in types


# ---------------------------------------------------------------------------
# Unknown github.* action type
# ---------------------------------------------------------------------------


def test_unknown_github_action_type_fails(
    event_log: EventLog, policy: PolicyEngine, gh_client: GitHubAppClient
) -> None:
    executor = Executor(event_log, policy, github_client=gh_client)
    proposal = Proposal(
        intent_id="intent_abc",
        agent_id="code-agent",
        title="try merge",
        action_type="github.merge_pr",
        target="jaydenpiao/quorum",
        rationale="x",
        rollback_steps=["y"],
        payload={"pr_number": 1},
        status=ProposalStatus.approved,
    )
    outcome = executor.execute(proposal, actor_id="code-agent")
    assert outcome["status"] == "failed"
    assert "github.merge_pr" in outcome["detail"]


# ---------------------------------------------------------------------------
# Happy path: github.open_pr dispatches end-to-end
# ---------------------------------------------------------------------------


def test_github_open_pr_happy_path(
    event_log: EventLog, policy: PolicyEngine, gh_client: GitHubAppClient
) -> None:
    executor = Executor(event_log, policy, github_client=gh_client)
    proposal = _open_pr_proposal()

    with respx.mock(assert_all_called=False) as mock:
        _setup_happy_path(mock)
        outcome = executor.execute(proposal, actor_id="code-agent")

    assert outcome["status"] == "succeeded"
    assert outcome["result"]["pr_number"] == 17
    assert outcome["result"]["head_branch"] == f"quorum/{proposal.id}"

    types = [e.event_type for e in event_log.read_all()]
    assert types[0] == "execution_started"
    assert types[-1] == "execution_succeeded"


# ---------------------------------------------------------------------------
# Actuator mid-flight failure surfaces as execution_failed
# ---------------------------------------------------------------------------


def test_github_open_pr_actuator_error_maps_to_execution_failed(
    event_log: EventLog, policy: PolicyEngine, gh_client: GitHubAppClient
) -> None:
    executor = Executor(event_log, policy, github_client=gh_client)

    with respx.mock(assert_all_called=False) as mock:
        mock.post("https://api.github.com/app/installations/7/access_tokens").mock(
            return_value=_token_response()
        )
        mock.get("https://api.github.com/repos/jaydenpiao/quorum/branches/feature/experiment").mock(
            return_value=httpx.Response(404, json={"message": "Branch not found"})
        )

        outcome = executor.execute(_open_pr_proposal(), actor_id="code-agent")

    assert outcome["status"] == "failed"
    # Detail carries the actuator error type prefix; no secrets.
    assert "actuator error" in outcome["detail"]
    assert "GitHubActionError" in outcome["detail"]


def test_github_open_pr_validates_payload(
    event_log: EventLog, policy: PolicyEngine, gh_client: GitHubAppClient
) -> None:
    """A malformed payload becomes a ValidationError, propagated unscrubbed.

    We don't catch pydantic's ValidationError in the dispatch path on
    purpose — it's a caller programming error, and the validation
    messages are safe. Confirm the proposal-submission time would catch
    this, but if it somehow slipped through, the executor surfaces
    loudly rather than silently succeeding.
    """
    executor = Executor(event_log, policy, github_client=gh_client)
    bad_proposal = Proposal(
        intent_id="intent_abc",
        agent_id="code-agent",
        title="Open PR",
        action_type="github.open_pr",
        target="jaydenpiao/quorum",
        rationale="x",
        rollback_steps=["y"],
        payload={"owner": "x"},  # missing required fields
        status=ProposalStatus.approved,
    )

    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        executor.execute(bad_proposal, actor_id="code-agent")


# ---------------------------------------------------------------------------
# Health check failure after successful dispatch still rolls back
# ---------------------------------------------------------------------------


def test_github_open_pr_success_then_health_check_fails(
    event_log: EventLog, policy: PolicyEngine, gh_client: GitHubAppClient
) -> None:
    """Dispatch succeeds → health check fails → actuator rollback runs.

    After PR C the rollback is actuator-aware: the executor calls
    ``rollback_open_pr``, which GETs the PR, PATCHes it closed, and
    DELETEs the branch. All those calls need to be mocked.
    """
    executor = Executor(event_log, policy, github_client=gh_client)
    proposal = _open_pr_proposal()
    proposal = proposal.model_copy(
        update={
            "health_checks": [HealthCheckSpec(name="intentional", kind=HealthCheckKind.always_fail)]
        }
    )

    with respx.mock(assert_all_called=False) as mock:
        _setup_happy_path(mock)
        # Actuator rollback path (see apps/.../actions.rollback_open_pr).
        mock.get("https://api.github.com/repos/jaydenpiao/quorum/pulls/17").mock(
            return_value=httpx.Response(200, json={"state": "open", "merged": False, "number": 17})
        )
        mock.patch("https://api.github.com/repos/jaydenpiao/quorum/pulls/17").mock(
            return_value=httpx.Response(
                200, json={"state": "closed", "merged": False, "number": 17}
            )
        )
        mock.delete(
            f"https://api.github.com/repos/jaydenpiao/quorum/git/refs/heads/quorum/{proposal.id}"
        ).mock(return_value=httpx.Response(204))

        outcome = executor.execute(proposal, actor_id="code-agent")

    assert outcome["status"] == "failed"
    # Actuator opened the PR, so result is populated even on failure.
    assert outcome["result"]["pr_number"] == 17
    types = [e.event_type for e in event_log.read_all()]
    assert "execution_succeeded" not in types
    assert "execution_failed" in types
    # rollback_completed fired (actuator-aware path succeeded).
    assert "rollback_completed" in types
    assert "rollback_impossible" not in types
    # The completed event carries an actuator_summary describing what
    # actually happened on GitHub.
    completed = next(e for e in event_log.read_all() if e.event_type == "rollback_completed")
    assert completed.payload["actuator_summary"]["pr_action"] == "closed"
    assert completed.payload["actuator_summary"]["branch_deleted"] == f"quorum/{proposal.id}"
