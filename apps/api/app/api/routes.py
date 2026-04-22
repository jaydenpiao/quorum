from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request

from apps.api.app.demo_seed import seed_demo
from apps.api.app.domain.models import (
    EventEnvelope,
    ExecutionRequest,
    Finding,
    FindingCreate,
    Intent,
    IntentCreate,
    Proposal,
    ProposalCreate,
    Vote,
    VoteCreate,
)
from apps.api.app.services.auth import (
    allowed_action_types_for,
    demo_allowed,
    require_agent,
)
from apps.api.app.services.event_log import EventLogTamperError

router = APIRouter(prefix="/api/v1")


def refresh_state(request: Request) -> None:
    request.app.state.state_store.replay(request.app.state.event_log.read_all())


def _enforce_agent(body_agent_id: str | None, authenticated_agent_id: str) -> str:
    """Return the agent_id to persist.

    If the request body includes an agent_id, it must match the authenticated
    agent exactly — otherwise 403. If omitted (or empty string), fall back to
    the authenticated agent. This closes the spoof surface: a valid key for
    agent A can no longer claim authorship as agent B.
    """
    if body_agent_id and body_agent_id != authenticated_agent_id:
        raise HTTPException(
            status_code=403,
            detail=(
                f"agent_id mismatch: body claims '{body_agent_id}' but the "
                f"authenticated agent is '{authenticated_agent_id}'"
            ),
        )
    return authenticated_agent_id


@router.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True}


@router.get("/state")
def state(request: Request) -> dict[str, Any]:
    refresh_state(request)
    return cast(dict[str, Any], request.app.state.state_store.snapshot())


@router.get("/events")
def events(request: Request) -> list[dict[str, Any]]:
    refresh_state(request)
    return cast(list[dict[str, Any]], request.app.state.state_store.events)


@router.get("/events/verify")
def verify_events(request: Request) -> dict[str, Any]:
    """Re-walk the event log's hash chain. Returns ok=True or raises 500 with detail."""
    try:
        request.app.state.event_log.verify()
    except EventLogTamperError as exc:
        raise HTTPException(status_code=500, detail=f"event log tamper detected: {exc}") from exc
    events = request.app.state.event_log.read_all()
    return {
        "ok": True,
        "event_count": len(events),
        "last_hash": events[-1].hash if events else None,
    }


@router.post("/intents")
def create_intent(
    payload: IntentCreate,
    request: Request,
    agent_id: str = Depends(require_agent),
) -> dict[str, Any]:
    data = payload.model_dump()
    # Server-side identity always wins over whatever the client sent.
    data["requested_by"] = agent_id
    intent = Intent(**data)
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
def create_finding(
    payload: FindingCreate,
    request: Request,
    agent_id: str = Depends(require_agent),
) -> dict[str, Any]:
    bound_agent = _enforce_agent(payload.agent_id, agent_id)

    if payload.intent_id not in request.app.state.state_store.intents:
        refresh_state(request)
    if payload.intent_id not in request.app.state.state_store.intents:
        raise HTTPException(status_code=404, detail="intent not found")

    data = payload.model_dump()
    data["agent_id"] = bound_agent
    finding = Finding(**data)
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
def create_proposal(
    payload: ProposalCreate,
    request: Request,
    agent_id: str = Depends(require_agent),
) -> dict[str, Any]:
    bound_agent = _enforce_agent(payload.agent_id, agent_id)

    # Per-agent action_type allow-list (LLM PR 3). Returns None for
    # unrestricted agents (human operators, pre-existing agents); a
    # tuple for agents that explicitly scope their proposals. We reject
    # with 403 **before** the event log sees the proposal — a blocked
    # attempt is not a mutation.
    allowed = allowed_action_types_for(bound_agent)
    if allowed is not None and payload.action_type not in allowed:
        raise HTTPException(
            status_code=403,
            detail=(
                f"agent {bound_agent!r} is not permitted to propose "
                f"action_type {payload.action_type!r}; "
                f"allowed: {list(allowed)}"
            ),
        )

    refresh_state(request)
    if payload.intent_id not in request.app.state.state_store.intents:
        raise HTTPException(status_code=404, detail="intent not found")

    data = payload.model_dump()
    data["agent_id"] = bound_agent
    proposal = Proposal(**data)
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
def create_vote(
    payload: VoteCreate,
    request: Request,
    agent_id: str = Depends(require_agent),
) -> dict[str, Any]:
    # Spoof check precedes existence check so 403 wins over 404.
    bound_agent = _enforce_agent(payload.agent_id, agent_id)

    refresh_state(request)
    if payload.proposal_id not in request.app.state.state_store.proposals:
        raise HTTPException(status_code=404, detail="proposal not found")

    data = payload.model_dump()
    data["agent_id"] = bound_agent
    vote = Vote(**data)
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
    return cast(dict[str, Any], request.app.state.state_store.snapshot())


@router.post("/proposals/{proposal_id}/execute")
def execute_proposal(
    proposal_id: str,
    payload: ExecutionRequest,
    request: Request,
    agent_id: str = Depends(require_agent),
) -> dict[str, Any]:
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

    # Server-side actor is always the authenticated agent.
    # The ExecutionRequest body is retained for backwards compatibility but its
    # `actor_id` is advisory and ignored here.
    result = request.app.state.executor.execute(proposal, actor_id=agent_id)
    refresh_state(request)
    return cast(dict[str, Any], result)


@router.post("/demo/incident")
def demo_incident(
    request: Request,
    agent_id: str = Depends(require_agent),
) -> dict[str, Any]:
    if not demo_allowed():
        raise HTTPException(
            status_code=404,
            detail="demo endpoint disabled; set QUORUM_ALLOW_DEMO=1 to enable",
        )
    event_log = request.app.state.event_log
    event_log.reset()
    snapshot = seed_demo(event_log.path.as_posix(), event_log=event_log)
    refresh_state(request)
    return snapshot
