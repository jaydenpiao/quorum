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
from apps.api.app.services.event_log import EventLog
from apps.api.app.services.health_checks import HealthCheckRunner
from apps.api.app.services.policy_engine import PolicyEngine


class Executor:
    def __init__(self, event_log: EventLog, policy_engine: PolicyEngine) -> None:
        self.event_log = event_log
        self.policy_engine = policy_engine
        self.check_runner = HealthCheckRunner()

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

        health_results: list[HealthCheckResult] = [
            self.check_runner.run(spec) for spec in proposal.health_checks
        ]

        failed = [result for result in health_results if not result.passed]
        if failed:
            failed_record = ExecutionRecord(
                proposal_id=proposal.id,
                actor_id=actor_id,
                status=ExecutionStatus.failed,
                health_checks=health_results,
                detail="one or more health checks failed",
            )
            self.event_log.append(
                EventEnvelope(
                    event_type="execution_failed",
                    entity_type="execution",
                    entity_id=failed_record.id,
                    payload=failed_record.model_dump(mode="json"),
                )
            )

            rollback_payload = None
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
                "health_checks": [h.model_dump(mode="json") for h in health_results],
                "rollback": rollback_payload,
            }

        success = ExecutionRecord(
            proposal_id=proposal.id,
            actor_id=actor_id,
            status=ExecutionStatus.succeeded,
            health_checks=health_results,
            detail="execution completed and all health checks passed",
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
        }
