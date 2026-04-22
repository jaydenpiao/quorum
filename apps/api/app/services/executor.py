"""Execution path: actuator dispatch → health checks → rollback.

``Executor.execute()`` is the single place a proposal turns into
side-effects against the outside world. The sequence is always:

1. Emit ``execution_started``.
2. Dispatch the action type to an actuator (or pass through for the
   simulated action types used by existing flows). Result, if any, is
   attached to the ``ExecutionRecord.result`` blob so replay-from-events
   carries the same state as the direct return.
3. Run each ``HealthCheckSpec`` on the proposal, emit one
   ``health_check_completed`` event per check.
4. If the action itself raised or any health check failed, emit
   ``execution_failed`` + (optionally) rollback events, then return.
5. Otherwise emit ``execution_succeeded``.

The actuator subpackage never emits events — per ``AGENTS.md`` only the
executor does. Actuator errors are translated here into scrubbed
``execution_failed`` detail strings so private-key or token material
cannot leak into the event log.
"""

from __future__ import annotations

from typing import Any

from apps.api.app.domain.models import (
    EventEnvelope,
    ExecutionRecord,
    ExecutionStatus,
    HealthCheckResult,
    Proposal,
    RollbackRecord,
)
from apps.api.app.services.actuators.github import (
    GitHubActionError,
    GitHubApiError,
    GitHubAppAuthError,
    GitHubAppClient,
    GitHubOpenPrSpec,
    open_pr,
)
from apps.api.app.services.event_log import EventLog
from apps.api.app.services.health_checks import HealthCheckRunner
from apps.api.app.services.policy_engine import PolicyEngine


class ExecutorDispatchError(RuntimeError):
    """Raised when the executor cannot route a proposal to any actuator.

    Distinct from actuator-internal errors (``GitHubActionError``,
    ``GitHubApiError``, ``GitHubAppAuthError``) so callers can tell
    configuration gaps from mid-flight failures.
    """


_GITHUB_PREFIX = "github."


class Executor:
    def __init__(
        self,
        event_log: EventLog,
        policy_engine: PolicyEngine,
        *,
        github_client: GitHubAppClient | None = None,
    ) -> None:
        self.event_log = event_log
        self.policy_engine = policy_engine
        self.check_runner = HealthCheckRunner()
        self.github_client = github_client

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def execute(self, proposal: Proposal, actor_id: str) -> dict[str, Any]:
        started = ExecutionRecord(
            proposal_id=proposal.id,
            actor_id=actor_id,
            status=ExecutionStatus.started,
            detail=f"executing {proposal.action_type} on {proposal.target}",
        )
        self.event_log.append(
            EventEnvelope(
                event_type="execution_started",
                entity_type="execution",
                entity_id=started.id,
                payload=started.model_dump(mode="json"),
            )
        )

        # Step 2: dispatch to the actuator. If dispatch fails we emit
        # execution_failed immediately and skip health checks — there is
        # nothing healthy to verify if the mutation itself did not land.
        try:
            action_result = self._dispatch_action(proposal)
        except ExecutorDispatchError as exc:
            return self._fail_and_rollback(
                proposal=proposal,
                actor_id=actor_id,
                health_results=[],
                detail=f"action dispatch failed: {exc}",
                result={},
            )
        except (GitHubActionError, GitHubApiError, GitHubAppAuthError) as exc:
            # Scrubbed detail: only the error type + message already
            # sanitized by the actuator layer.
            return self._fail_and_rollback(
                proposal=proposal,
                actor_id=actor_id,
                health_results=[],
                detail=f"actuator error: {type(exc).__name__}: {exc}",
                result={},
            )

        # Step 3: health checks.
        health_results: list[HealthCheckResult] = []
        for spec in proposal.health_checks:
            result = self.check_runner.run(spec)
            self.event_log.append(
                EventEnvelope(
                    event_type="health_check_completed",
                    entity_type="health_check_result",
                    entity_id=result.id,
                    payload={
                        "id": result.id,
                        "execution_id": started.id,
                        "proposal_id": proposal.id,
                        "name": result.name,
                        "kind": spec.kind.value,
                        "passed": result.passed,
                        "detail": result.detail,
                        "created_at": result.created_at.isoformat(),
                    },
                )
            )
            health_results.append(result)

        failed = [r for r in health_results if not r.passed]
        if failed:
            return self._fail_and_rollback(
                proposal=proposal,
                actor_id=actor_id,
                health_results=health_results,
                detail="one or more health checks failed",
                result=action_result,
            )

        success = ExecutionRecord(
            proposal_id=proposal.id,
            actor_id=actor_id,
            status=ExecutionStatus.succeeded,
            health_checks=health_results,
            detail="execution completed and all health checks passed",
            result=action_result,
        )
        self.event_log.append(
            EventEnvelope(
                event_type="execution_succeeded",
                entity_type="execution",
                entity_id=success.id,
                payload=success.model_dump(mode="json"),
            )
        )
        return {
            "status": "succeeded",
            "health_checks": [h.model_dump(mode="json") for h in health_results],
            "result": action_result,
        }

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _dispatch_action(self, proposal: Proposal) -> dict[str, Any]:
        """Route ``proposal.action_type`` to an actuator.

        Returns the actuator's typed result serialized as a dict, or an
        empty dict for action types that predate real actuators.

        Raises:
            ExecutorDispatchError: unknown ``github.*`` action_type, or
                a ``github.*`` action_type when no GitHub client is
                configured.
            GitHubActionError / GitHubApiError / GitHubAppAuthError:
                mid-flight actuator failures, propagated untouched so
                ``execute()`` can record a scrubbed detail.
        """
        action_type = proposal.action_type
        if not action_type.startswith(_GITHUB_PREFIX):
            # Non-github action types retain the pre-PR-B2 simulated path:
            # emit events, run health checks, but perform no mutation.
            return {}

        if self.github_client is None:
            raise ExecutorDispatchError(
                f"proposal.action_type '{action_type}' requires a configured GitHub App, "
                "but none is available (set QUORUM_GITHUB_APP_PRIVATE_KEY and "
                "config/github.yaml app_id)"
            )

        if action_type == "github.open_pr":
            spec = GitHubOpenPrSpec.model_validate(proposal.payload)
            result = open_pr(self.github_client, spec, proposal_id=proposal.id)
            return result.model_dump(mode="json")

        raise ExecutorDispatchError(
            f"action_type '{action_type}' is not yet implemented; "
            "supported github actions in this release: github.open_pr"
        )

    # ------------------------------------------------------------------
    # Failure path
    # ------------------------------------------------------------------

    def _fail_and_rollback(
        self,
        *,
        proposal: Proposal,
        actor_id: str,
        health_results: list[HealthCheckResult],
        detail: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        failed_record = ExecutionRecord(
            proposal_id=proposal.id,
            actor_id=actor_id,
            status=ExecutionStatus.failed,
            health_checks=health_results,
            detail=detail,
            result=result,
        )
        self.event_log.append(
            EventEnvelope(
                event_type="execution_failed",
                entity_type="execution",
                entity_id=failed_record.id,
                payload=failed_record.model_dump(mode="json"),
            )
        )

        rollback_payload: dict[str, Any] | None = None
        if self.policy_engine.auto_rollback_enabled:
            rollback_started = RollbackRecord(
                proposal_id=proposal.id,
                actor_id=actor_id,
                steps=proposal.rollback_steps,
                status="started",
            )
            self.event_log.append(
                EventEnvelope(
                    event_type="rollback_started",
                    entity_type="rollback",
                    entity_id=rollback_started.id,
                    payload=rollback_started.model_dump(mode="json"),
                )
            )
            rollback_completed = RollbackRecord(
                proposal_id=proposal.id,
                actor_id=actor_id,
                steps=proposal.rollback_steps,
                status="completed",
            )
            self.event_log.append(
                EventEnvelope(
                    event_type="rollback_completed",
                    entity_type="rollback",
                    entity_id=rollback_completed.id,
                    payload=rollback_completed.model_dump(mode="json"),
                )
            )
            rollback_payload = rollback_completed.model_dump(mode="json")

        return {
            "status": "failed",
            "detail": detail,
            "health_checks": [h.model_dump(mode="json") for h in health_results],
            "rollback": rollback_payload,
            "result": result,
        }
