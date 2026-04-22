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

Rollback path:

- Non-github action types emit ``rollback_started`` +
  ``rollback_completed`` carrying ``proposal.rollback_steps``.
- ``github.*`` proposals with a captured actuator result dispatch to
  the matching actuator rollback function via the per-action-type
  ``_ROLLBACK_DISPATCH`` table. On success → ``rollback_completed``
  (payload carries an ``actuator_summary``). On
  ``RollbackImpossibleError`` or any other actuator error mid-rollback
  → ``rollback_impossible`` — the proposal lands in
  ``ProposalStatus.rollback_impossible`` and a human reconciles.

Dispatch tables (``_ACTION_DISPATCH`` / ``_ROLLBACK_DISPATCH``) keep the
per-action wiring in one place so adding a new action is a three-line
change here plus a spec + action function in the actuator subpackage.

The actuator subpackage never emits events — per ``AGENTS.md`` only the
executor does. Actuator errors are translated here into scrubbed
``execution_failed`` / ``rollback_impossible`` detail strings so
private-key or token material cannot leak into the event log.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ValidationError

from apps.api.app.domain.models import (
    EventEnvelope,
    ExecutionRecord,
    ExecutionStatus,
    HealthCheckResult,
    Proposal,
    RollbackImpossibleRecord,
    RollbackRecord,
)
from apps.api.app.services.actuators.github import (
    AddLabelsResult,
    ClosePrResult,
    CommentIssueResult,
    GitHubActionError,
    GitHubAddLabelsSpec,
    GitHubApiError,
    GitHubAppAuthError,
    GitHubAppClient,
    GitHubClosePrSpec,
    GitHubCommentIssueSpec,
    GitHubOpenPrSpec,
    OpenPrResult,
    RollbackImpossibleError,
    add_labels,
    close_pr,
    comment_issue,
    open_pr,
    rollback_add_labels,
    rollback_close_pr,
    rollback_comment_issue,
    rollback_open_pr,
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


# Per-action_type dispatch: each entry pairs the payload spec model with
# an orchestration wrapper. Wrappers accept the client, the validated
# spec, and the proposal id (kept on all actions for API symmetry even
# when only ``open_pr`` derives state from it).
_ActionFn = Callable[[GitHubAppClient, Any, str], BaseModel]
_ACTION_DISPATCH: dict[str, tuple[type[BaseModel], _ActionFn]] = {
    "github.open_pr": (
        GitHubOpenPrSpec,
        lambda client, spec, pid: open_pr(client, spec, proposal_id=pid),
    ),
    "github.comment_issue": (
        GitHubCommentIssueSpec,
        lambda client, spec, pid: comment_issue(client, spec, proposal_id=pid),
    ),
    "github.close_pr": (
        GitHubClosePrSpec,
        lambda client, spec, pid: close_pr(client, spec, proposal_id=pid),
    ),
    "github.add_labels": (
        GitHubAddLabelsSpec,
        lambda client, spec, pid: add_labels(client, spec, proposal_id=pid),
    ),
}

# Per-action_type rollback dispatch: result model + rollback fn. Keyed
# by the same action_type as the forward dispatch so the executor can
# look up how to undo whatever it just ran.
_RollbackFn = Callable[[GitHubAppClient, Any], dict[str, Any]]
_ROLLBACK_DISPATCH: dict[str, tuple[type[BaseModel], _RollbackFn]] = {
    "github.open_pr": (OpenPrResult, rollback_open_pr),
    "github.comment_issue": (CommentIssueResult, rollback_comment_issue),
    "github.close_pr": (ClosePrResult, rollback_close_pr),
    "github.add_labels": (AddLabelsResult, rollback_add_labels),
}


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
            return self._fail_and_rollback(
                proposal=proposal,
                actor_id=actor_id,
                health_results=[],
                detail=f"actuator error: {type(exc).__name__}: {exc}",
                result={},
            )

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
        action_type = proposal.action_type
        if not action_type.startswith(_GITHUB_PREFIX):
            return {}

        if self.github_client is None:
            raise ExecutorDispatchError(
                f"proposal.action_type '{action_type}' requires a configured GitHub App, "
                "but none is available (set QUORUM_GITHUB_APP_PRIVATE_KEY and "
                "config/github.yaml app_id)"
            )

        entry = _ACTION_DISPATCH.get(action_type)
        if entry is None:
            raise ExecutorDispatchError(
                f"action_type '{action_type}' is not yet implemented; "
                f"supported github actions: {sorted(_ACTION_DISPATCH.keys())}"
            )

        spec_cls, action_fn = entry
        spec = spec_cls.model_validate(proposal.payload)
        result_model = action_fn(self.github_client, spec, proposal.id)
        return result_model.model_dump(mode="json")

    # ------------------------------------------------------------------
    # Failure + rollback path
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
            rollback_payload = self._do_rollback(
                proposal=proposal, actor_id=actor_id, result=result
            )

        return {
            "status": "failed",
            "detail": detail,
            "health_checks": [h.model_dump(mode="json") for h in health_results],
            "rollback": rollback_payload,
            "result": result,
        }

    def _do_rollback(
        self,
        *,
        proposal: Proposal,
        actor_id: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        """Emit rollback_started, then rollback_completed or rollback_impossible."""
        started = RollbackRecord(
            proposal_id=proposal.id,
            actor_id=actor_id,
            steps=proposal.rollback_steps,
            status="started",
        )
        self.event_log.append(
            EventEnvelope(
                event_type="rollback_started",
                entity_type="rollback",
                entity_id=started.id,
                payload=started.model_dump(mode="json"),
            )
        )

        # Actuator-aware rollback path: requires a client, a dispatch
        # entry for the action_type, and a non-empty captured result.
        rollback_entry = _ROLLBACK_DISPATCH.get(proposal.action_type)
        if self.github_client is not None and rollback_entry is not None and result:
            result_cls, rollback_fn = rollback_entry
            try:
                parsed = result_cls.model_validate(result)
            except ValidationError as exc:
                return self._emit_rollback_impossible(
                    proposal=proposal,
                    actor_id=actor_id,
                    reason=(
                        f"{proposal.action_type} execution result did not match "
                        f"{result_cls.__name__} schema ({exc.error_count()} errors); "
                        "manual reconcile required"
                    ),
                    actuator_state=result,
                )

            try:
                rollback_summary = rollback_fn(self.github_client, parsed)
            except RollbackImpossibleError as exc:
                return self._emit_rollback_impossible(
                    proposal=proposal,
                    actor_id=actor_id,
                    reason=exc.reason,
                    actuator_state=exc.actuator_state,
                )
            except (GitHubActionError, GitHubApiError, GitHubAppAuthError) as exc:
                return self._emit_rollback_impossible(
                    proposal=proposal,
                    actor_id=actor_id,
                    reason=f"actuator rollback failed: {type(exc).__name__}: {exc}",
                    actuator_state=parsed.model_dump(mode="json"),
                )

            completed = RollbackRecord(
                proposal_id=proposal.id,
                actor_id=actor_id,
                steps=proposal.rollback_steps,
                status="completed",
            )
            self.event_log.append(
                EventEnvelope(
                    event_type="rollback_completed",
                    entity_type="rollback",
                    entity_id=completed.id,
                    payload={
                        **completed.model_dump(mode="json"),
                        "actuator_summary": rollback_summary,
                    },
                )
            )
            return completed.model_dump(mode="json")

        # Text-only rollback path (non-github or no captured result).
        completed = RollbackRecord(
            proposal_id=proposal.id,
            actor_id=actor_id,
            steps=proposal.rollback_steps,
            status="completed",
        )
        self.event_log.append(
            EventEnvelope(
                event_type="rollback_completed",
                entity_type="rollback",
                entity_id=completed.id,
                payload=completed.model_dump(mode="json"),
            )
        )
        return completed.model_dump(mode="json")

    def _emit_rollback_impossible(
        self,
        *,
        proposal: Proposal,
        actor_id: str,
        reason: str,
        actuator_state: dict[str, Any],
    ) -> dict[str, Any]:
        record = RollbackImpossibleRecord(
            proposal_id=proposal.id,
            actor_id=actor_id,
            reason=reason,
            actuator_state=actuator_state,
        )
        payload = record.model_dump(mode="json")
        self.event_log.append(
            EventEnvelope(
                event_type="rollback_impossible",
                entity_type="rollback_impossible",
                entity_id=record.id,
                payload=payload,
            )
        )
        return payload
