"""Read-only history endpoints backed by the Postgres projection.

Writes always flow through ``EventLog.append`` first; these endpoints never
mutate anything. Public-read, no bearer token (same contract as
``/api/v1/state`` and ``/api/v1/events``).

When ``DATABASE_URL`` is unset (NoOpProjector), every endpoint here returns
**503 Service Unavailable** with a clear message. The existing replay-based
endpoints (`/state`, `/events`) still work in that mode — use those for
tiny demos. History endpoints exist for operator-grade queries that
replay cannot serve efficiently.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.app.db.engine import make_session_factory
from apps.api.app.db.models import (
    EventProjectedRow,
    ExecutionRow,
    FindingRow,
    HealthCheckResultRow,
    HumanApprovalRow,
    IntentRow,
    PolicyDecisionRow,
    ProposalRow,
    RollbackRow,
    VoteRow,
)

router = APIRouter(prefix="/api/v1/history")

_LIMIT = Annotated[int, Query(ge=1, le=200, description="Page size (max 200)")]
_OFFSET = Annotated[int, Query(ge=0, description="Rows to skip")]


def _require_db(request: Request) -> sessionmaker[Session]:
    """Return a session factory, or raise 503 if PG isn't wired up."""
    engine: Engine | None = getattr(request.app.state, "pg_engine", None)
    if engine is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "history endpoints require the Postgres projection; set DATABASE_URL "
                "and restart, or use /api/v1/state and /api/v1/events for replay-based reads"
            ),
        )
    factory: sessionmaker[Session] | None = getattr(request.app.state, "pg_session_factory", None)
    if factory is None:
        factory = make_session_factory(engine)
        request.app.state.pg_session_factory = factory
    return factory


def _row_to_dict(row: Any, columns: Sequence[str]) -> dict[str, Any]:
    return {c: getattr(row, c) for c in columns}


def _image_push_to_dict(row: EventProjectedRow) -> dict[str, Any]:
    payload = dict(row.envelope.get("payload", {}))
    return {
        **payload,
        "event_id": row.event_id,
        "event_hash": row.event_hash,
        "prev_hash": row.prev_hash,
        "projected_at": row.projected_at,
    }


@router.get("/intents", response_model=list[dict[str, Any]])
def list_intents(
    request: Request,
    environment: str | None = Query(default=None, max_length=64),
    requested_by: str | None = Query(default=None, max_length=128),
    limit: _LIMIT = 50,
    offset: _OFFSET = 0,
) -> list[dict[str, Any]]:
    factory = _require_db(request)
    cols = ("id", "title", "description", "environment", "requested_by", "created_at")
    with factory() as session:
        stmt = select(IntentRow)
        if environment:
            stmt = stmt.where(IntentRow.environment == environment)
        if requested_by:
            stmt = stmt.where(IntentRow.requested_by == requested_by)
        stmt = stmt.order_by(IntentRow.created_at.desc()).limit(limit).offset(offset)
        rows = session.execute(stmt).scalars().all()
    return [_row_to_dict(r, cols) for r in rows]


@router.get("/findings", response_model=list[dict[str, Any]])
def list_findings(
    request: Request,
    intent_id: str | None = Query(default=None, max_length=128),
    agent_id: str | None = Query(default=None, max_length=128),
    limit: _LIMIT = 50,
    offset: _OFFSET = 0,
) -> list[dict[str, Any]]:
    factory = _require_db(request)
    cols = (
        "id",
        "intent_id",
        "agent_id",
        "summary",
        "evidence_refs",
        "confidence",
        "created_at",
    )
    with factory() as session:
        stmt = select(FindingRow)
        if intent_id:
            stmt = stmt.where(FindingRow.intent_id == intent_id)
        if agent_id:
            stmt = stmt.where(FindingRow.agent_id == agent_id)
        stmt = stmt.order_by(FindingRow.created_at.desc()).limit(limit).offset(offset)
        rows = session.execute(stmt).scalars().all()
    return [_row_to_dict(r, cols) for r in rows]


@router.get("/proposals", response_model=list[dict[str, Any]])
def list_proposals(
    request: Request,
    intent_id: str | None = Query(default=None, max_length=128),
    agent_id: str | None = Query(default=None, max_length=128),
    status: str | None = Query(default=None, max_length=32),
    action_type: str | None = Query(default=None, max_length=128),
    environment: str | None = Query(default=None, max_length=64),
    risk: str | None = Query(default=None, max_length=32),
    limit: _LIMIT = 50,
    offset: _OFFSET = 0,
) -> list[dict[str, Any]]:
    factory = _require_db(request)
    cols = (
        "id",
        "intent_id",
        "agent_id",
        "title",
        "action_type",
        "target",
        "environment",
        "risk",
        "rationale",
        "evidence_refs",
        "rollback_steps",
        "health_checks",
        "status",
        "created_at",
    )
    with factory() as session:
        stmt = select(ProposalRow)
        if intent_id:
            stmt = stmt.where(ProposalRow.intent_id == intent_id)
        if agent_id:
            stmt = stmt.where(ProposalRow.agent_id == agent_id)
        if status:
            stmt = stmt.where(ProposalRow.status == status)
        if action_type:
            stmt = stmt.where(ProposalRow.action_type == action_type)
        if environment:
            stmt = stmt.where(ProposalRow.environment == environment)
        if risk:
            stmt = stmt.where(ProposalRow.risk == risk)
        stmt = stmt.order_by(ProposalRow.created_at.desc()).limit(limit).offset(offset)
        rows = session.execute(stmt).scalars().all()
    return [_row_to_dict(r, cols) for r in rows]


@router.get("/policy-decisions", response_model=list[dict[str, Any]])
def list_policy_decisions(
    request: Request,
    proposal_id: str | None = Query(default=None, max_length=128),
    allowed: bool | None = Query(default=None),
    requires_human: bool | None = Query(default=None),
    limit: _LIMIT = 50,
    offset: _OFFSET = 0,
) -> list[dict[str, Any]]:
    factory = _require_db(request)
    cols = (
        "proposal_id",
        "allowed",
        "requires_human",
        "votes_required",
        "reasons",
        "created_at",
    )
    with factory() as session:
        stmt = select(PolicyDecisionRow)
        if proposal_id:
            stmt = stmt.where(PolicyDecisionRow.proposal_id == proposal_id)
        if allowed is not None:
            stmt = stmt.where(PolicyDecisionRow.allowed == allowed)
        if requires_human is not None:
            stmt = stmt.where(PolicyDecisionRow.requires_human == requires_human)
        stmt = stmt.order_by(PolicyDecisionRow.created_at.desc()).limit(limit).offset(offset)
        rows = session.execute(stmt).scalars().all()
    return [_row_to_dict(r, cols) for r in rows]


@router.get("/votes", response_model=list[dict[str, Any]])
def list_votes(
    request: Request,
    proposal_id: str | None = Query(default=None, max_length=128),
    agent_id: str | None = Query(default=None, max_length=128),
    decision: str | None = Query(default=None, max_length=32),
    limit: _LIMIT = 50,
    offset: _OFFSET = 0,
) -> list[dict[str, Any]]:
    factory = _require_db(request)
    cols = (
        "id",
        "proposal_id",
        "agent_id",
        "decision",
        "reason",
        "voter_kind",
        "llm_model",
        "system_prompt_sha256",
        "observed_event_cursor",
        "counted",
        "counted_reason",
        "created_at",
    )
    with factory() as session:
        stmt = select(VoteRow)
        if proposal_id:
            stmt = stmt.where(VoteRow.proposal_id == proposal_id)
        if agent_id:
            stmt = stmt.where(VoteRow.agent_id == agent_id)
        if decision:
            stmt = stmt.where(VoteRow.decision == decision)
        stmt = stmt.order_by(VoteRow.created_at.desc()).limit(limit).offset(offset)
        rows = session.execute(stmt).scalars().all()
    return [_row_to_dict(r, cols) for r in rows]


@router.get("/human-approvals", response_model=list[dict[str, Any]])
def list_human_approvals(
    request: Request,
    proposal_id: str | None = Query(default=None, max_length=128),
    status: str | None = Query(default=None, max_length=32),
    proposer_id: str | None = Query(default=None, max_length=128),
    approver_id: str | None = Query(default=None, max_length=128),
    limit: _LIMIT = 50,
    offset: _OFFSET = 0,
) -> list[dict[str, Any]]:
    factory = _require_db(request)
    cols = (
        "id",
        "proposal_id",
        "status",
        "proposer_id",
        "approver_id",
        "reason",
        "reasons",
        "created_at",
    )
    with factory() as session:
        stmt = select(HumanApprovalRow)
        if proposal_id:
            stmt = stmt.where(HumanApprovalRow.proposal_id == proposal_id)
        if status:
            stmt = stmt.where(HumanApprovalRow.status == status)
        if proposer_id:
            stmt = stmt.where(HumanApprovalRow.proposer_id == proposer_id)
        if approver_id:
            stmt = stmt.where(HumanApprovalRow.approver_id == approver_id)
        stmt = stmt.order_by(HumanApprovalRow.created_at.desc()).limit(limit).offset(offset)
        rows = session.execute(stmt).scalars().all()
    return [_row_to_dict(r, cols) for r in rows]


@router.get("/executions", response_model=list[dict[str, Any]])
def list_executions(
    request: Request,
    proposal_id: str | None = Query(default=None, max_length=128),
    status: str | None = Query(default=None, max_length=32),
    actor_id: str | None = Query(default=None, max_length=128),
    limit: _LIMIT = 50,
    offset: _OFFSET = 0,
) -> list[dict[str, Any]]:
    factory = _require_db(request)
    cols = (
        "id",
        "proposal_id",
        "actor_id",
        "status",
        "health_checks",
        "detail",
        "created_at",
    )
    with factory() as session:
        stmt = select(ExecutionRow)
        if proposal_id:
            stmt = stmt.where(ExecutionRow.proposal_id == proposal_id)
        if status:
            stmt = stmt.where(ExecutionRow.status == status)
        if actor_id:
            stmt = stmt.where(ExecutionRow.actor_id == actor_id)
        stmt = stmt.order_by(ExecutionRow.created_at.desc()).limit(limit).offset(offset)
        rows = session.execute(stmt).scalars().all()
    return [_row_to_dict(r, cols) for r in rows]


@router.get("/health-check-results", response_model=list[dict[str, Any]])
def list_health_check_results(
    request: Request,
    proposal_id: str | None = Query(default=None, max_length=128),
    execution_id: str | None = Query(default=None, max_length=128),
    kind: str | None = Query(default=None, max_length=32),
    passed: bool | None = Query(default=None),
    limit: _LIMIT = 50,
    offset: _OFFSET = 0,
) -> list[dict[str, Any]]:
    factory = _require_db(request)
    cols = (
        "id",
        "execution_id",
        "proposal_id",
        "name",
        "kind",
        "passed",
        "detail",
        "created_at",
    )
    with factory() as session:
        stmt = select(HealthCheckResultRow)
        if proposal_id:
            stmt = stmt.where(HealthCheckResultRow.proposal_id == proposal_id)
        if execution_id:
            stmt = stmt.where(HealthCheckResultRow.execution_id == execution_id)
        if kind:
            stmt = stmt.where(HealthCheckResultRow.kind == kind)
        if passed is not None:
            stmt = stmt.where(HealthCheckResultRow.passed == passed)
        stmt = stmt.order_by(HealthCheckResultRow.created_at.desc()).limit(limit).offset(offset)
        rows = session.execute(stmt).scalars().all()
    return [_row_to_dict(r, cols) for r in rows]


@router.get("/rollbacks", response_model=list[dict[str, Any]])
def list_rollbacks(
    request: Request,
    proposal_id: str | None = Query(default=None, max_length=128),
    actor_id: str | None = Query(default=None, max_length=128),
    status: str | None = Query(default=None, max_length=32),
    limit: _LIMIT = 50,
    offset: _OFFSET = 0,
) -> list[dict[str, Any]]:
    factory = _require_db(request)
    cols = ("id", "proposal_id", "actor_id", "steps", "status", "created_at")
    with factory() as session:
        stmt = select(RollbackRow)
        if proposal_id:
            stmt = stmt.where(RollbackRow.proposal_id == proposal_id)
        if actor_id:
            stmt = stmt.where(RollbackRow.actor_id == actor_id)
        if status:
            stmt = stmt.where(RollbackRow.status == status)
        stmt = stmt.order_by(RollbackRow.created_at.desc()).limit(limit).offset(offset)
        rows = session.execute(stmt).scalars().all()
    return [_row_to_dict(r, cols) for r in rows]


@router.get("/image-pushes", response_model=list[dict[str, Any]])
def list_image_pushes(
    request: Request,
    limit: _LIMIT = 50,
    offset: _OFFSET = 0,
) -> list[dict[str, Any]]:
    factory = _require_db(request)
    with factory() as session:
        stmt = (
            select(EventProjectedRow)
            .where(EventProjectedRow.event_type == "image_push_completed")
            .order_by(EventProjectedRow.projected_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = session.execute(stmt).scalars().all()
    return [_image_push_to_dict(r) for r in rows]
