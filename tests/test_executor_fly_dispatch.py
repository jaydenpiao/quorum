"""Executor dispatch for ``fly.*`` action types.

Companion to ``tests/test_executor_github_dispatch.py`` — same pattern,
different actuator. Covers:

- happy path: ``fly.deploy`` with a FlyClient stub returns an
  ``execution_succeeded`` event carrying a FlyDeployResult-shaped
  result blob.
- missing client: ExecutorDispatchError → ``execution_failed`` with a
  scrubbed detail string.
- rollback: when a health check fails post-deploy, ``rollback_deploy``
  is invoked and ``rollback_completed`` carries an actuator_summary
  that names the previous digest.
- rollback_impossible: deploy with no captured previous digest emits
  ``rollback_impossible`` instead of a faux success.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from apps.api.app.domain.models import (
    HealthCheckKind,
    HealthCheckSpec,
    Proposal,
    ProposalStatus,
)
from apps.api.app.services.event_log import EventLog
from apps.api.app.services.executor import Executor
from apps.api.app.services.policy_engine import PolicyEngine

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def event_log(tmp_path: Path) -> EventLog:
    return EventLog(tmp_path / "events.jsonl")


@pytest.fixture
def policy() -> PolicyEngine:
    return PolicyEngine("config/policies.yaml")


class _StubFlyClient:
    """Replays scripted responses for Fly client calls. Not a subclass
    of FlyClient — the executor treats fly_client duck-typed via the
    dispatch functions.
    """

    def __init__(
        self,
        *,
        releases_response: list[dict[str, Any]] | None = None,
        deploy_response: dict[str, Any] | None = None,
        deploy_raises: Exception | None = None,
    ) -> None:
        self._releases = releases_response or []
        self._deploy_response = deploy_response or {}
        self._deploy_raises = deploy_raises
        self.deploy_calls: list[dict[str, Any]] = []

    def deploy(self, *, app: str, image_digest: str, strategy: str = "rolling") -> dict[str, Any]:
        self.deploy_calls.append({"app": app, "image_digest": image_digest, "strategy": strategy})
        if self._deploy_raises is not None:
            raise self._deploy_raises
        return self._deploy_response

    def releases(self, *, app: str, limit: int = 5) -> list[dict[str, Any]]:
        return self._releases


def _deploy_proposal(
    *,
    app: str = "quorum-staging",
    image_digest: str = "sha256:" + "a" * 64,
    health_checks: list[HealthCheckSpec] | None = None,
) -> Proposal:
    checks = (
        [HealthCheckSpec(name="post-deploy-smoke", kind=HealthCheckKind.always_pass)]
        if health_checks is None
        else health_checks
    )
    return Proposal(
        intent_id="intent_deploy",
        agent_id="deploy-agent",
        title=f"Deploy {image_digest[:14]} to {app}",
        action_type="fly.deploy",
        target=app,
        rationale="new image built from main",
        rollback_steps=["redeploy previous digest"],
        payload={
            "app": app,
            "image_digest": image_digest,
            "strategy": "rolling",
        },
        health_checks=checks,
        status=ProposalStatus.approved,
    )


# ---------------------------------------------------------------------------
# Dispatch happy path
# ---------------------------------------------------------------------------


def test_fly_deploy_success_emits_execution_succeeded(
    event_log: EventLog, policy: PolicyEngine
) -> None:
    fly = _StubFlyClient(
        releases_response=[{"ImageRef": {"Digest": "sha256:" + "b" * 64}}],
        deploy_response={"ReleaseId": "rel_xyz"},
    )
    executor = Executor(event_log, policy, fly_client=fly)  # type: ignore[arg-type]

    result = executor.execute(_deploy_proposal(), actor_id="operator")

    assert result["status"] == "succeeded"
    assert fly.deploy_calls[0]["app"] == "quorum-staging"
    assert fly.deploy_calls[0]["image_digest"] == "sha256:" + "a" * 64

    events = event_log.read_all()
    event_types = [e.event_type for e in events]
    assert "execution_started" in event_types
    assert "execution_succeeded" in event_types

    succeeded = next(e for e in events if e.event_type == "execution_succeeded")
    stored_result = succeeded.payload["result"]
    assert stored_result["released_image_digest"] == "sha256:" + "a" * 64
    assert stored_result["previous_image_digest"] == "sha256:" + "b" * 64
    assert stored_result["release_id"] == "rel_xyz"


# ---------------------------------------------------------------------------
# Missing client / dispatch error
# ---------------------------------------------------------------------------


def test_fly_deploy_without_client_fails_cleanly(event_log: EventLog, policy: PolicyEngine) -> None:
    # No fly_client argument → dispatch error, not a crash.
    executor = Executor(event_log, policy)

    result = executor.execute(_deploy_proposal(), actor_id="operator")

    assert result["status"] == "failed"
    assert "fly client" in result["detail"].lower()

    events = event_log.read_all()
    failed = next(e for e in events if e.event_type == "execution_failed")
    assert "fly client" in failed.payload["detail"].lower()


def test_fly_unknown_action_fails_cleanly(event_log: EventLog, policy: PolicyEngine) -> None:
    fly = _StubFlyClient()
    executor = Executor(event_log, policy, fly_client=fly)  # type: ignore[arg-type]

    bad = _deploy_proposal()
    bad = bad.model_copy(update={"action_type": "fly.restart"})

    result = executor.execute(bad, actor_id="operator")

    assert result["status"] == "failed"
    assert "fly.restart" in result["detail"]
    assert "fly.deploy" in result["detail"]  # enumerates supported


def test_fly_deploy_refuses_same_app_self_deploy(
    monkeypatch: pytest.MonkeyPatch,
    event_log: EventLog,
    policy: PolicyEngine,
) -> None:
    monkeypatch.setenv("FLY_APP_NAME", "quorum-staging")
    fly = _StubFlyClient(
        releases_response=[{"ImageRef": {"Digest": "sha256:" + "b" * 64}}],
        deploy_response={"ReleaseId": "rel_xyz"},
    )
    executor = Executor(event_log, policy, fly_client=fly)  # type: ignore[arg-type]

    result = executor.execute(_deploy_proposal(app="quorum-staging"), actor_id="operator")

    assert result["status"] == "failed"
    assert "refusing same-app fly.deploy" in result["detail"]
    assert fly.deploy_calls == []

    events = event_log.read_all()
    event_types = [e.event_type for e in events]
    assert "execution_started" in event_types
    assert "execution_failed" in event_types
    assert "execution_succeeded" not in event_types


def test_fly_deploy_without_health_checks_fails_before_mutation(
    event_log: EventLog, policy: PolicyEngine
) -> None:
    fly = _StubFlyClient(
        releases_response=[{"ImageRef": {"Digest": "sha256:" + "b" * 64}}],
        deploy_response={"ReleaseId": "rel_xyz"},
    )
    executor = Executor(event_log, policy, fly_client=fly)  # type: ignore[arg-type]

    result = executor.execute(_deploy_proposal(health_checks=[]), actor_id="operator")

    assert result["status"] == "failed"
    assert "fly.deploy proposals require health_checks" in result["detail"]
    assert fly.deploy_calls == []

    event_types = [e.event_type for e in event_log.read_all()]
    assert "execution_started" in event_types
    assert "execution_failed" in event_types
    assert "execution_succeeded" not in event_types


# ---------------------------------------------------------------------------
# Rollback paths
# ---------------------------------------------------------------------------


def test_fly_deploy_rollback_on_failed_health_check(
    event_log: EventLog, policy: PolicyEngine
) -> None:
    fly = _StubFlyClient(
        releases_response=[{"ImageRef": {"Digest": "sha256:" + "b" * 64}}],
        deploy_response={"ReleaseId": "rel_new"},
    )
    executor = Executor(event_log, policy, fly_client=fly)  # type: ignore[arg-type]

    proposal = _deploy_proposal(
        health_checks=[HealthCheckSpec(name="forced-fail", kind=HealthCheckKind.always_fail)]
    )

    result = executor.execute(proposal, actor_id="operator")
    assert result["status"] == "failed"

    # Two deploy calls total: the forward deploy + the rollback redeploy.
    assert len(fly.deploy_calls) == 2
    assert fly.deploy_calls[0]["image_digest"] == "sha256:" + "a" * 64
    assert fly.deploy_calls[1]["image_digest"] == "sha256:" + "b" * 64

    events = event_log.read_all()
    event_types = [e.event_type for e in events]
    assert "execution_failed" in event_types
    assert "rollback_started" in event_types
    assert "rollback_completed" in event_types
    assert "rollback_impossible" not in event_types

    completed = next(e for e in events if e.event_type == "rollback_completed")
    summary = completed.payload.get("actuator_summary") or {}
    assert summary.get("rolled_back_to") == "sha256:" + "b" * 64


def test_fly_deploy_rollback_impossible_without_previous_digest(
    event_log: EventLog, policy: PolicyEngine
) -> None:
    # No prior releases — deploy captures previous_image_digest="". The
    # rollback path then emits rollback_impossible.
    fly = _StubFlyClient(
        releases_response=[],
        deploy_response={},
    )
    executor = Executor(event_log, policy, fly_client=fly)  # type: ignore[arg-type]

    proposal = _deploy_proposal(
        health_checks=[HealthCheckSpec(name="forced-fail", kind=HealthCheckKind.always_fail)]
    )

    executor.execute(proposal, actor_id="operator")

    events = event_log.read_all()
    event_types = [e.event_type for e in events]
    assert "rollback_impossible" in event_types
    assert "rollback_completed" not in event_types

    impossible = next(e for e in events if e.event_type == "rollback_impossible")
    assert "no previous image digest" in impossible.payload["reason"]
