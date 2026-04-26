from __future__ import annotations

from typing import Any

from apps.api.app.domain.models import (
    ApprovalDecision,
    EventEnvelope,
    Finding,
    FindingCreate,
    HealthCheckKind,
    HealthCheckSpec,
    HumanApprovalOutcome,
    HumanApprovalRequest,
    ImagePushRecord,
    Intent,
    IntentCreate,
    Proposal,
    ProposalCreate,
    RiskLevel,
    Vote,
    VoteCreate,
    VoteDecision,
)
from apps.api.app.services.actuators.fly import FlyClient
from apps.api.app.services.event_log import EventLog
from apps.api.app.services.executor import Executor
from apps.api.app.services.policy_engine import PolicyEngine
from apps.api.app.services.quorum_engine import QuorumEngine
from apps.api.app.services.state_store import StateStore

_DEMO_COMMIT_SHA = "2c1e6e17eff7b3428418efb3bc0d8535146f67dc"
_DEMO_WORKFLOW_RUN_ID = "24952257426"
_DEMO_NEW_DIGEST = "sha256:aa267ec52be093acd5b2e8a39c658d073f1927ceeeada5aef55c28fbe7f90f6e"
_DEMO_PREVIOUS_DIGEST = "sha256:36809cd455123b89a592a70dcf31cc91a27bb8eddb9b9ccd154830bfa0f9bcce"


class _DemoFlyClient(FlyClient):
    """Deterministic Fly client for the local demo seeder.

    It exercises the real ``fly.deploy`` executor path without invoking
    flyctl or changing any live Fly app.
    """

    def __init__(self) -> None:
        self.deploy_calls: list[dict[str, str]] = []

    def releases(self, *, app: str, limit: int = 5) -> list[dict[str, object]]:
        return [
            {
                "ID": "rel_previous_demo",
                "ImageRef": {"Digest": _DEMO_PREVIOUS_DIGEST},
                "Version": 7,
            }
        ][:limit]

    def deploy(self, *, app: str, image_digest: str, strategy: str = "rolling") -> dict[str, str]:
        self.deploy_calls.append({"app": app, "image_digest": image_digest, "strategy": strategy})
        return {"ReleaseId": "rel_dogfood_demo"}


def seed_demo(
    log_path: str = "data/events.jsonl", event_log: EventLog | None = None
) -> dict[str, Any]:
    # Caller can provide an existing EventLog to preserve hash-chain continuity;
    # otherwise a fresh instance is created (suitable for CLI use).
    if event_log is None:
        event_log = EventLog(log_path)
    policy = PolicyEngine("config/policies.yaml")
    quorum = QuorumEngine()
    store = StateStore()

    image_push = ImagePushRecord(
        commit_sha=_DEMO_COMMIT_SHA,
        workflow_run_id=_DEMO_WORKFLOW_RUN_ID,
        workflow_url=f"https://github.com/jaydenpiao/quorum/actions/runs/{_DEMO_WORKFLOW_RUN_ID}",
        staging_image_ref=f"registry.fly.io/quorum-staging@{_DEMO_NEW_DIGEST}",
        staging_digest=_DEMO_NEW_DIGEST,
        prod_image_ref=f"registry.fly.io/quorum-prod@{_DEMO_NEW_DIGEST}",
        prod_digest=_DEMO_NEW_DIGEST,
        reported_by="deploy-agent",
    )
    event_log.append(
        EventEnvelope(
            event_type="image_push_completed",
            entity_type="image_push",
            entity_id=image_push.id,
            payload=image_push.model_dump(mode="json"),
        )
    )

    intent = IntentCreate(
        title="Promote verified Quorum image from staging to prod",
        description=(
            "Image-push CI published a new content-addressed Quorum image; "
            "agents need to verify evidence and propose the gated prod deploy."
        ),
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
            agent_id="deploy-llm-agent",
            summary=(
                "Image-push evidence shows the same immutable digest is available "
                "for quorum-staging and quorum-prod."
            ),
            evidence_refs=[
                f"image_push:{image_push.id}",
                f"workflow:{_DEMO_WORKFLOW_RUN_ID}",
                f"digest:{_DEMO_NEW_DIGEST}",
            ],
            confidence=0.94,
        ),
        FindingCreate(
            intent_id=intent_obj.id,
            agent_id="telemetry-agent",
            summary=(
                "Staging and prod readiness probes are the required post-change "
                "checks for a safe Quorum dog-food deploy."
            ),
            evidence_refs=[
                "https://quorum-staging.fly.dev/readiness",
                "https://quorum-prod.fly.dev/api/v1/health",
            ],
            confidence=0.9,
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
        title=f"Deploy Quorum prod image {_DEMO_NEW_DIGEST[:19]}",
        action_type="fly.deploy",
        target="quorum-prod",
        environment="prod",
        risk=RiskLevel.high,
        rationale=(
            "CI produced a pinned Fly image digest and agents verified the "
            "post-change readiness checks required for production promotion."
        ),
        evidence_refs=[
            f"image_push:{image_push.id}",
            f"workflow:{_DEMO_WORKFLOW_RUN_ID}",
            "staging-readiness",
            "prod-api-health",
        ],
        rollback_steps=[
            f"redeploy previous prod image {_DEMO_PREVIOUS_DIGEST}",
            "wait for Fly release health checks",
            "verify prod readiness and API health return HTTP 200",
        ],
        health_checks=[
            HealthCheckSpec(name="prod-readiness", kind=HealthCheckKind.always_pass),
            HealthCheckSpec(name="prod-api-health", kind=HealthCheckKind.always_pass),
        ],
        payload={
            "app": "quorum-prod",
            "image_digest": _DEMO_NEW_DIGEST,
            "strategy": "immediate",
        },
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
    if decision.requires_human:
        approval_request = HumanApprovalRequest(
            proposal_id=proposal.id,
            proposer_id=proposal.agent_id,
            reasons=list(decision.reasons),
        )
        event_log.append(
            EventEnvelope(
                event_type="human_approval_requested",
                entity_type="human_approval_request",
                entity_id=approval_request.id,
                payload=approval_request.model_dump(mode="json"),
            )
        )

    votes = [
        VoteCreate(
            proposal_id=proposal.id,
            agent_id="telemetry-agent",
            decision=VoteDecision.approve,
            reason="readiness and health checks are explicit and target prod",
        ),
        VoteCreate(
            proposal_id=proposal.id,
            agent_id="code-agent",
            decision=VoteDecision.approve,
            reason="image digest is immutable and comes from main CI",
        ),
    ]
    all_votes: list[dict[str, Any]] = []
    for vote in votes:
        vote_obj = Vote(**vote.model_dump())
        event_log.append(
            EventEnvelope(
                event_type="proposal_voted",
                entity_type="vote",
                entity_id=vote_obj.id,
                payload=vote_obj.model_dump(mode="json"),
            )
        )
        all_votes.append(vote_obj.model_dump(mode="json"))

    if quorum.is_approved(all_votes, decision):
        event_log.append(
            EventEnvelope(
                event_type="proposal_approved",
                entity_type="proposal",
                entity_id=proposal.id,
                payload={"proposal_id": proposal.id},
            )
        )
        approval = HumanApprovalOutcome(
            proposal_id=proposal.id,
            approver_id="operator",
            decision=ApprovalDecision.granted,
            reason="reviewed digest, policy decision, votes, and health checks",
        )
        event_log.append(
            EventEnvelope(
                event_type="human_approval_granted",
                entity_type="human_approval_outcome",
                entity_id=approval.id,
                payload=approval.model_dump(mode="json"),
            )
        )
        Executor(event_log, policy, fly_client=_DemoFlyClient()).execute(
            proposal, actor_id="deploy-agent"
        )

    store.replay(event_log.read_all())
    return store.snapshot()


if __name__ == "__main__":
    snapshot = seed_demo()
    print(f"seeded demo with {snapshot['event_count']} events")
