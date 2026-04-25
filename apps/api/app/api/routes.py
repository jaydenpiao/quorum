from __future__ import annotations

import asyncio
import json
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from apps.api.app.demo_seed import seed_demo
from apps.api.app.domain.models import (
    ApprovalCreate,
    ApprovalDecision,
    EventEnvelope,
    ExecutionRequest,
    Finding,
    FindingCreate,
    HumanApprovalOutcome,
    HumanApprovalRequest,
    ImagePushCreate,
    ImagePushRecord,
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

# Server-Sent Events keepalive interval. The client's EventSource will
# reconnect automatically if the connection drops, so a 15s heartbeat
# keeps middleboxes (proxies, load balancers) from closing an idle
# connection without trading latency for data freshness.
_SSE_KEEPALIVE_SECONDS = 15.0

# Bounded per-subscriber queue. If a slow client can't keep up with
# event volume, drop the oldest queued events rather than buffer
# forever or block the append path. 256 events covers any reasonable
# browser reconnect gap during a demo.
_SSE_QUEUE_SIZE = 256


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


@router.get("/events/stream")
async def stream_events(request: Request) -> StreamingResponse:
    """Server-Sent Events stream of new envelopes as they land.

    The operator console's ``EventSource`` consumes this to live-tail
    the event log without polling. Protocol:

    - ``data: <json>\\n\\n`` for each event, where ``<json>`` is the
      serialized ``EventEnvelope``.
    - ``: keepalive\\n\\n`` every 15 s so idle proxies don't close the
      connection.

    The route is read-only (no ``Depends(require_agent)``) because the
    ``GET /api/v1/events`` poller is also public — the event log is the
    product's audit trail and the console displays it without auth.
    Mutating routes remain bearer-authenticated.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[EventEnvelope] = asyncio.Queue(maxsize=_SSE_QUEUE_SIZE)

    def _on_event(envelope: EventEnvelope) -> None:
        # ``subscribe()`` invokes this on the writer thread (sync
        # ``EventLog.append``); marshal back onto the async loop.
        try:
            loop.call_soon_threadsafe(_enqueue, envelope)
        except RuntimeError:
            # Loop is closed (client disconnected + cleanup racing).
            # Nothing to do; the unsubscribe in ``finally`` below
            # will remove the callback shortly.
            pass

    def _enqueue(envelope: EventEnvelope) -> None:
        if queue.full():
            # Drop the oldest queued event to make room. The client
            # can re-fetch the full log via GET /api/v1/events if it
            # suspects it missed one.
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(envelope)

    unsubscribe = request.app.state.event_log.subscribe(_on_event)

    async def _gen() -> Any:
        try:
            while True:
                if await request.is_disconnected():
                    return
                try:
                    envelope = await asyncio.wait_for(queue.get(), timeout=_SSE_KEEPALIVE_SECONDS)
                except TimeoutError:
                    yield b": keepalive\n\n"
                    continue
                payload = json.dumps(envelope.model_dump(mode="json"), default=str)
                yield f"data: {payload}\n\n".encode("utf-8")
        finally:
            unsubscribe()

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            # Disable intermediate buffering on nginx / Fly proxies so
            # events reach the client immediately.
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


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


@router.post("/image-pushes")
def record_image_push(
    payload: ImagePushCreate,
    request: Request,
    agent_id: str = Depends(require_agent),
) -> dict[str, Any]:
    """Record CI image-push evidence for deploy-agent consumption.

    This is evidence only. It does not execute a deploy, vote, or
    approve anything; deploys still flow through `fly.deploy` proposals.
    """

    record = ImagePushRecord(**payload.model_dump(), reported_by=agent_id)
    request.app.state.event_log.append(
        EventEnvelope(
            event_type="image_push_completed",
            entity_type="image_push",
            entity_id=record.id,
            payload=record.model_dump(mode="json"),
        )
    )
    refresh_state(request)
    return record.model_dump(mode="json")


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

    # Human approval entity — emit a request event right after the
    # policy decision so operators + auditors see exactly why approval
    # is needed. The request is pending until a POST to
    # /api/v1/approvals/{proposal_id} resolves it.
    if decision.requires_human:
        approval_request = HumanApprovalRequest(
            proposal_id=proposal.id,
            proposer_id=bound_agent,
            reasons=list(decision.reasons),
        )
        request.app.state.event_log.append(
            EventEnvelope(
                event_type="human_approval_requested",
                entity_type="human_approval_request",
                entity_id=approval_request.id,
                payload=approval_request.model_dump(mode="json"),
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


@router.post("/approvals/{proposal_id}")
def create_approval(
    proposal_id: str,
    payload: ApprovalCreate,
    request: Request,
    agent_id: str = Depends(require_agent),
) -> dict[str, Any]:
    """Grant or deny a human approval on a proposal that needs one.

    Preconditions:
    - The proposal must exist.
    - The proposal's policy decision must have ``requires_human=True``;
      approvals on proposals that don't need one are 422.
    - There must be no prior granted/denied approval — re-deciding is a
      409 so the event log never carries two competing decisions for
      the same proposal.

    The approver identity comes from the authenticated agent — the
    body cannot forge it (same actor-binding rule as every other
    mutating route).
    """
    refresh_state(request)
    store = request.app.state.state_store

    if proposal_id not in store.proposals:
        raise HTTPException(status_code=404, detail="proposal not found")

    policy_payload = store.policy_decisions.get(proposal_id)
    if not policy_payload:
        raise HTTPException(status_code=500, detail="missing policy decision")
    if not policy_payload.get("requires_human"):
        raise HTTPException(
            status_code=422,
            detail="proposal does not require human approval; nothing to decide",
        )

    # Re-decisions are rejected — the event log must tell a clean story.
    prior = store.human_approvals.get(proposal_id, [])
    for entry in prior:
        if entry.get("decision") in {"granted", "denied"}:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"approval for proposal {proposal_id} already decided "
                    f"({entry['decision']}); re-decisions are not allowed"
                ),
            )

    outcome = HumanApprovalOutcome(
        proposal_id=proposal_id,
        approver_id=agent_id,
        decision=payload.decision,
        reason=payload.reason,
    )
    event_type = (
        "human_approval_granted"
        if payload.decision is ApprovalDecision.granted
        else "human_approval_denied"
    )
    request.app.state.event_log.append(
        EventEnvelope(
            event_type=event_type,
            entity_type="human_approval_outcome",
            entity_id=outcome.id,
            payload=outcome.model_dump(mode="json"),
        )
    )

    refresh_state(request)
    return outcome.model_dump(mode="json")


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

    # Human approval gate — only proposals that needed approval are checked.
    # Reads the reduced state_store.human_approvals map populated by the
    # reducer cases for human_approval_* events.
    if decision.requires_human:
        if not request.app.state.state_store.proposal_has_granted_approval(proposal_id):
            raise HTTPException(
                status_code=403,
                detail=(
                    "proposal requires human approval and none has been granted; "
                    f"POST to /api/v1/approvals/{proposal_id} with decision='granted'"
                ),
            )

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
