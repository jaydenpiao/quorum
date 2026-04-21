from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

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
    ExecutionRequest,
)
from apps.api.app.demo_seed import seed_demo

router = APIRouter(prefix="/api/v1")


def refresh_state(request: Request) -> None:
    request.app.state.state_store.replay(request.app.state.event_log.read_all())


@router.get("/health")
def health() -> dict:
    return {"ok": True}


@router.get("/state")
def state(request: Request) -> dict:
    refresh_state(request)
    return request.app.state.state_store.snapshot()


@router.get("/events")
def events(request: Request) -> list[dict]:
    refresh_state(request)
    return request.app.state.state_store.events


@router.post("/intents")
def create_intent(payload: IntentCreate, request: Request) -> dict:
    intent = Intent(**payload.model_dump())
    event = EventEnvelope(
        event_type="intent_created",
        entity_type="intent",
        entity_id=intent.id,
        payload=intent.model_dump(mode="json"),
    )
    request.app.state.event_log.append(event)
    refresh_state(request)
    return intent.model_dump(mode="json")


@router.post("/findings")
def create_finding(payload: FindingCreate, request: Request) -> dict:
    if payload.intent_id not in request.app.state.state_store.intents:
        refresh_state(request)
    if payload.intent_id not in request.app.state.state_store.intents:
        raise HTTPException(status_code=404, detail="intent not found")

    finding = Finding(**payload.model_dump())
    request.app.state.event_log.append(
        EventEnvelope(
            event_type="finding_created",
            entity_type="finding",
            entity_id=finding.id,
            payload=finding.model_dump(mode="json"),
        )
    )
    refresh_state(request)
    return finding.model_dump(mode="json")


@router.post("/proposals")
def create_proposal(payload: ProposalCreate, request: Request) -> dict:
    refresh_state(request)
    if payload.intent_id not in request.app.state.state_store.intents:
        raise HTTPException(status_code=404, detail="intent not found")

    proposal = Proposal(**payload.model_dump())
    request.app.state.event_log.append(
        EventEnvelope(
            event_type="proposal_created",
            entity_type="proposal",
            entity_id=proposal.id,
            payload=proposal.model_dump(mode="json"),
        )
    )

    decision = request.app.state.policy_engine.evaluate(proposal)
    request.app.state.event_log.append(
        EventEnvelope(
            event_type="policy_evaluated",
            entity_type="policy_decision",
            entity_id=proposal.id,
            payload=decision.model_dump(mode="json"),
        )
    )

    refresh_state(request)
    return {
        "proposal": proposal.model_dump(mode="json"),
        "policy_decision": decision.model_dump(mode="json"),
    }


@router.post("/votes")
def create_vote(payload: VoteCreate, request: Request) -> dict:
    refresh_state(request)
    if payload.proposal_id not in request.app.state.state_store.proposals:
        raise HTTPException(status_code=404, detail="proposal not found")

    vote = Vote(**payload.model_dump())
    request.app.state.event_log.append(
        EventEnvelope(
            event_type="proposal_voted",
            entity_type="vote",
            entity_id=vote.id,
            payload=vote.model_dump(mode="json"),
        )
    )

    refresh_state(request)
    votes = request.app.state.state_store.votes.get(payload.proposal_id, [])
    policy_payload = request.app.state.state_store.policy_decisions.get(payload.proposal_id)
    if not policy_payload:
        raise HTTPException(status_code=500, detail="missing policy decision")

    policy_decision = request.app.state.policy_engine.evaluate(
        Proposal.model_validate(request.app.state.state_store.proposals[payload.proposal_id])
    )

    approved = request.app.state.quorum_engine.is_approved(votes, policy_decision)
    blocked = request.app.state.quorum_engine.is_blocked(votes)

    if approved:
        request.app.state.event_log.append(
            EventEnvelope(
                event_type="proposal_approved",
                entity_type="proposal",
                entity_id=payload.proposal_id,
                payload={"proposal_id": payload.proposal_id},
            )
        )
    elif blocked:
        request.app.state.event_log.append(
            EventEnvelope(
                event_type="proposal_blocked",
                entity_type="proposal",
                entity_id=payload.proposal_id,
                payload={"proposal_id": payload.proposal_id},
            )
        )

    refresh_state(request)
    return request.app.state.state_store.snapshot()


@router.post("/proposals/{proposal_id}/execute")
def execute_proposal(proposal_id: str, payload: ExecutionRequest, request: Request) -> dict:
    refresh_state(request)
    proposal_payload = request.app.state.state_store.proposals.get(proposal_id)
    if not proposal_payload:
        raise HTTPException(status_code=404, detail="proposal not found")

    policy_payload = request.app.state.state_store.policy_decisions.get(proposal_id)
    if not policy_payload:
        raise HTTPException(status_code=500, detail="missing policy decision")

    proposal = Proposal.model_validate(proposal_payload)
    decision = request.app.state.policy_engine.evaluate(proposal)

    if not decision.allowed:
        raise HTTPException(status_code=403, detail="proposal not allowed by policy")

    if proposal.status != "approved":
        raise HTTPException(status_code=409, detail="proposal must be approved before execution")

    result = request.app.state.executor.execute(proposal, actor_id=payload.actor_id)
    refresh_state(request)
    return result


@router.post("/demo/incident")
def demo_incident(request: Request) -> dict:
    request.app.state.event_log.reset()
    snapshot = seed_demo(request.app.state.event_log.path.as_posix())
    refresh_state(request)
    return snapshot
