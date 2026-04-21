from __future__ import annotations

from apps.api.app.domain.models import (
    EventEnvelope,
    Finding,
    FindingCreate,
    Intent,
    IntentCreate,
    Proposal,
    ProposalCreate,
    Vote,
    VoteCreate,
    HealthCheckSpec,
    HealthCheckKind,
)
from apps.api.app.services.event_log import EventLog
from apps.api.app.services.policy_engine import PolicyEngine
from apps.api.app.services.quorum_engine import QuorumEngine
from apps.api.app.services.state_store import StateStore
from apps.api.app.services.executor import Executor


def seed_demo(log_path: str = "data/events.jsonl") -> dict:
    event_log = EventLog(log_path)
    policy = PolicyEngine("config/policies.yaml")
    quorum = QuorumEngine()
    store = StateStore()

    intent = IntentCreate(
        title="Investigate elevated p99 latency in checkout-service",
        description="Error rate and latency rose after deploy v184",
        environment="prod",
        requested_by="operator",
    )
    intent_obj = Intent(**intent.model_dump())
    event_log.append(
        EventEnvelope(
            event_type="intent_created",
            entity_type="intent",
            entity_id=intent_obj.id,
            payload=intent_obj.model_dump(mode="json"),
        )
    )

    findings = [
        FindingCreate(
            intent_id=intent_obj.id,
            agent_id="telemetry-agent",
            summary="p99 latency doubled after deploy v184; DB errors correlate with spike",
            evidence_refs=["grafana:checkout-p99", "logs:error-rate"],
            confidence=0.91,
        ),
        FindingCreate(
            intent_id=intent_obj.id,
            agent_id="deploy-agent",
            summary="deploy v184 introduced new DB pool settings 6 minutes before spike",
            evidence_refs=["deploy:v184", "release-notes:v184"],
            confidence=0.87,
        ),
    ]

    for finding in findings:
        obj = Finding(**finding.model_dump())
        event_log.append(
            EventEnvelope(
                event_type="finding_created",
                entity_type="finding",
                entity_id=obj.id,
                payload=obj.model_dump(mode="json"),
            )
        )

    proposal_create = ProposalCreate(
        intent_id=intent_obj.id,
        agent_id="deploy-agent",
        title="Rollback checkout-service from v184 to v183",
        action_type="rollback-deploy",
        target="checkout-service",
        environment="prod",
        risk="high",
        rationale="Independent telemetry and deploy findings agree that v184 caused the regression",
        evidence_refs=["deploy:v184", "grafana:checkout-p99"],
        rollback_steps=[
            "set deployment image to v183",
            "wait for rollout complete",
            "confirm connection errors drop",
        ],
        health_checks=[
            HealthCheckSpec(name="error-rate", kind=HealthCheckKind.always_pass),
            HealthCheckSpec(name="latency", kind=HealthCheckKind.always_pass),
        ],
    )
    proposal = Proposal(**proposal_create.model_dump())
    event_log.append(
        EventEnvelope(
            event_type="proposal_created",
            entity_type="proposal",
            entity_id=proposal.id,
            payload=proposal.model_dump(mode="json"),
        )
    )

    decision = policy.evaluate(proposal)
    event_log.append(
        EventEnvelope(
            event_type="policy_evaluated",
            entity_type="policy_decision",
            entity_id=proposal.id,
            payload=decision.model_dump(mode="json"),
        )
    )

    votes = [
        VoteCreate(
            proposal_id=proposal.id,
            agent_id="telemetry-agent",
            decision="approve",
            reason="matches telemetry evidence",
        ),
        VoteCreate(
            proposal_id=proposal.id,
            agent_id="code-agent",
            decision="approve",
            reason="recent config diff aligns with failure",
        ),
    ]
    all_votes = []
    for vote in votes:
        obj = Vote(**vote.model_dump())
        event_log.append(
            EventEnvelope(
                event_type="proposal_voted",
                entity_type="vote",
                entity_id=obj.id,
                payload=obj.model_dump(mode="json"),
            )
        )
        all_votes.append(obj.model_dump(mode="json"))

    if quorum.is_approved(all_votes, decision):
        event_log.append(
            EventEnvelope(
                event_type="proposal_approved",
                entity_type="proposal",
                entity_id=proposal.id,
                payload={"proposal_id": proposal.id},
            )
        )
        Executor(event_log, policy).execute(proposal, actor_id="operator")

    store.replay(event_log.read_all())
    return store.snapshot()


if __name__ == "__main__":
    snapshot = seed_demo()
    print(f"seeded demo with {snapshot['event_count']} events")
