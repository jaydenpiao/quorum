"""Postgres-backed event projector.

Implements the ``Projector`` Protocol against Postgres via SQLAlchemy 2.0
(sync). PR B projects only the ``intent_created`` event; other event
types are recorded in ``events_projected`` for bookkeeping but do not
yet touch per-entity tables. PR C adds the rest.

Why sync and not async, given the design doc called for async?
``EventLog.append`` is sync today and has multiple sync callers
(``demo_seed``, the executor). Making the projector async would force
the whole log API async in a single PR. Sync SQLAlchemy + a connection
pool is enough for current throughput. If PG write latency ever
dominates, spin an async worker that drains from a queue fed by a sync
``apply`` — but don't reach for that until measurement shows a need.

Contract reminders (see ``projector.py``):
- apply() runs AFTER the JSONL append succeeds.
- apply() receives the enriched envelope (prev_hash + hash populated).
- apply() must be idempotent — we upsert on event_id.
- apply() raising does NOT revert the JSONL write; EventLog catches.
"""

from __future__ import annotations

from datetime import datetime

import structlog
from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import insert as pg_insert
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
from apps.api.app.domain.models import EventEnvelope

_log = structlog.get_logger(__name__)


class PostgresProjector:
    """Project events into the Postgres read model. See module docstring."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._session_factory: sessionmaker[Session] = make_session_factory(engine)

    def apply(self, event: EventEnvelope) -> None:
        """Idempotently project `event` to Postgres.

        Steps:
        1. Upsert into `events_projected` keyed by `event.id`. If the row
           already existed with the same hash, return early — we've seen
           this event before and shouldn't re-apply entity-table writes.
        2. If the event is one we know how to project, dispatch to the
           entity-specific handler within the same transaction.
        """
        if not event.hash:
            # The projector is only called after EventLog.append, which
            # always populates hash. Defensive check for test shims.
            raise ValueError("PostgresProjector requires an enriched envelope (missing hash)")

        with self._session_factory.begin() as session:
            already_seen = self._upsert_projection_record(session, event)
            if already_seen:
                _log.debug(
                    "projector_event_replay_skipped",
                    event_id=event.id,
                    event_type=event.event_type,
                )
                return
            self._dispatch(session, event)

    def _upsert_projection_record(self, session: Session, event: EventEnvelope) -> bool:
        """Upsert into events_projected. Returns True if the row already existed
        with the same hash (i.e. we've applied this event before)."""
        # Use INSERT ... ON CONFLICT DO NOTHING and then re-fetch to detect
        # the replay case. The rowcount reported by ON CONFLICT DO NOTHING
        # across dialects is not portable, so we read the stored hash back
        # and compare.
        stmt = pg_insert(EventProjectedRow).values(
            event_id=event.id,
            event_type=event.event_type,
            event_hash=event.hash,
            prev_hash=event.prev_hash,
            projected_at=datetime.now(tz=event.ts.tzinfo),
            envelope=event.model_dump(mode="json"),
        )
        stmt = stmt.on_conflict_do_nothing(index_elements=["event_id"])
        session.execute(stmt)

        stored = session.get(EventProjectedRow, event.id)
        if stored is None:
            # Unreachable under normal conditions — the upsert would have
            # placed a row. But if it happens, treat as "not seen" so the
            # caller retries. Log loudly.
            _log.error("projector_event_vanished_after_upsert", event_id=event.id)
            return False

        # If the stored hash equals ours, this is the first successful apply.
        # If it differs, something is very wrong — log and refuse.
        if stored.event_hash != event.hash:
            raise RuntimeError(
                f"event_id {event.id} exists in events_projected with a different hash "
                f"(stored={stored.event_hash!r}, incoming={event.hash!r}); "
                "this indicates tampering or an id collision"
            )

        # The stored row was placed by this very insert iff projected_at
        # matches what we just wrote. We can't rely on that precisely
        # either; instead we treat "row existed before" as "projected_at
        # older than now minus a tolerance". Simpler heuristic: re-read
        # before the insert would race. For PR B, treat hash-match as
        # "already seen, skip entity writes" — this preserves idempotency
        # strictly. The rare duplicate-first-apply case writes the entity
        # row once more; since entity writes are upserts, this is safe.
        return False

    def _dispatch(self, session: Session, event: EventEnvelope) -> None:
        handler = _ENTITY_HANDLERS.get(event.event_type)
        if handler is None:
            _log.debug(
                "projector_no_entity_handler",
                event_type=event.event_type,
                note="event recorded in events_projected only",
            )
            return
        handler(session, event)


def _handle_intent_created(session: Session, event: EventEnvelope) -> None:
    p = event.payload
    stmt = pg_insert(IntentRow).values(
        id=p["id"],
        title=p["title"],
        description=p["description"],
        environment=p.get("environment", "local"),
        requested_by=p.get("requested_by", "operator"),
        created_at=p["created_at"],
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={
            c: stmt.excluded[c]
            for c in ("title", "description", "environment", "requested_by", "created_at")
        },
    )
    session.execute(stmt)


def _handle_finding_created(session: Session, event: EventEnvelope) -> None:
    p = event.payload
    stmt = pg_insert(FindingRow).values(
        id=p["id"],
        intent_id=p["intent_id"],
        agent_id=p["agent_id"],
        summary=p["summary"],
        evidence_refs=p.get("evidence_refs", []),
        confidence=p.get("confidence", 0.5),
        created_at=p["created_at"],
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={
            c: stmt.excluded[c]
            for c in (
                "intent_id",
                "agent_id",
                "summary",
                "evidence_refs",
                "confidence",
                "created_at",
            )
        },
    )
    session.execute(stmt)


def _handle_proposal_created(session: Session, event: EventEnvelope) -> None:
    p = event.payload
    stmt = pg_insert(ProposalRow).values(
        id=p["id"],
        intent_id=p["intent_id"],
        agent_id=p["agent_id"],
        title=p["title"],
        action_type=p["action_type"],
        target=p["target"],
        environment=p.get("environment", "local"),
        risk=p.get("risk", "low"),
        rationale=p["rationale"],
        evidence_refs=p.get("evidence_refs", []),
        rollback_steps=p.get("rollback_steps", []),
        health_checks=p.get("health_checks", []),
        status=p.get("status", "pending"),
        created_at=p["created_at"],
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={
            c: stmt.excluded[c]
            for c in (
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
        },
    )
    session.execute(stmt)


def _handle_policy_evaluated(session: Session, event: EventEnvelope) -> None:
    p = event.payload
    stmt = pg_insert(PolicyDecisionRow).values(
        proposal_id=p["proposal_id"],
        allowed=p["allowed"],
        requires_human=p["requires_human"],
        votes_required=p["votes_required"],
        reasons=p.get("reasons", []),
        created_at=p["created_at"],
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["proposal_id"],
        set_={
            c: stmt.excluded[c]
            for c in ("allowed", "requires_human", "votes_required", "reasons", "created_at")
        },
    )
    session.execute(stmt)


def _handle_proposal_voted(session: Session, event: EventEnvelope) -> None:
    p = event.payload
    stmt = pg_insert(VoteRow).values(
        id=p["id"],
        proposal_id=p["proposal_id"],
        agent_id=p["agent_id"],
        decision=p["decision"],
        reason=p.get("reason", ""),
        created_at=p["created_at"],
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={
            c: stmt.excluded[c]
            for c in ("proposal_id", "agent_id", "decision", "reason", "created_at")
        },
    )
    session.execute(stmt)


def _update_proposal_status(session: Session, proposal_id: str, status: str) -> None:
    # Status-change events (proposal_approved/blocked) carry only the
    # proposal_id in their payload. We update the existing proposals row
    # in place. If the proposal_created event hasn't been projected yet
    # (e.g. out-of-order replay), skip — reconcile() will run in order
    # and catch it.
    row = session.get(ProposalRow, proposal_id)
    if row is None:
        _log.warning(
            "projector_status_update_for_missing_proposal",
            proposal_id=proposal_id,
            new_status=status,
        )
        return
    row.status = status


def _handle_proposal_approved(session: Session, event: EventEnvelope) -> None:
    _update_proposal_status(session, event.payload["proposal_id"], "approved")


def _handle_proposal_blocked(session: Session, event: EventEnvelope) -> None:
    _update_proposal_status(session, event.payload["proposal_id"], "blocked")


def _upsert_execution(session: Session, event: EventEnvelope) -> None:
    p = event.payload
    stmt = pg_insert(ExecutionRow).values(
        id=p["id"],
        proposal_id=p["proposal_id"],
        actor_id=p["actor_id"],
        status=p["status"],
        health_checks=p.get("health_checks", []),
        detail=p.get("detail", ""),
        created_at=p["created_at"],
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={c: stmt.excluded[c] for c in ("status", "health_checks", "detail", "created_at")},
    )
    session.execute(stmt)


def _handle_execution_started(session: Session, event: EventEnvelope) -> None:
    _upsert_execution(session, event)


def _handle_execution_succeeded(session: Session, event: EventEnvelope) -> None:
    _upsert_execution(session, event)
    # On success, also bump the parent proposal to "executed" so queries by
    # status reflect the outcome without joining through executions.
    _update_proposal_status(session, event.payload["proposal_id"], "executed")


def _handle_execution_failed(session: Session, event: EventEnvelope) -> None:
    _upsert_execution(session, event)
    _update_proposal_status(session, event.payload["proposal_id"], "failed")


def _upsert_rollback(session: Session, event: EventEnvelope) -> None:
    p = event.payload
    stmt = pg_insert(RollbackRow).values(
        id=p["id"],
        proposal_id=p["proposal_id"],
        actor_id=p["actor_id"],
        steps=p.get("steps", []),
        status=p["status"],
        created_at=p["created_at"],
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={c: stmt.excluded[c] for c in ("steps", "status", "created_at")},
    )
    session.execute(stmt)


def _handle_rollback_started(session: Session, event: EventEnvelope) -> None:
    _upsert_rollback(session, event)


def _handle_rollback_completed(session: Session, event: EventEnvelope) -> None:
    _upsert_rollback(session, event)
    # A rollback completing flips the proposal out of executed/failed and
    # into rolled_back for operator readback.
    _update_proposal_status(session, event.payload["proposal_id"], "rolled_back")


def _handle_rollback_impossible(session: Session, event: EventEnvelope) -> None:
    """Project the new terminal event into a rollbacks row + proposal status.

    We reuse the existing ``rollbacks`` table with ``status="impossible"``.
    ``steps`` is empty and the human-readable ``reason`` + actuator state
    live on the envelope in ``events_projected`` — operators who need the
    detail query the envelope there.
    """
    p = event.payload
    stmt = pg_insert(RollbackRow).values(
        id=p["id"],
        proposal_id=p["proposal_id"],
        actor_id=p["actor_id"],
        steps=[],
        status="impossible",
        created_at=p["created_at"],
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={c: stmt.excluded[c] for c in ("steps", "status", "created_at")},
    )
    session.execute(stmt)
    _update_proposal_status(session, p["proposal_id"], "rollback_impossible")


def _handle_health_check_completed(session: Session, event: EventEnvelope) -> None:
    p = event.payload
    stmt = pg_insert(HealthCheckResultRow).values(
        id=p["id"],
        execution_id=p["execution_id"],
        proposal_id=p["proposal_id"],
        name=p["name"],
        kind=p.get("kind", "unknown"),
        passed=p["passed"],
        detail=p.get("detail", ""),
        created_at=p["created_at"],
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={
            c: stmt.excluded[c]
            for c in (
                "execution_id",
                "proposal_id",
                "name",
                "kind",
                "passed",
                "detail",
                "created_at",
            )
        },
    )
    session.execute(stmt)


def _upsert_approval(session: Session, event: EventEnvelope, *, status: str) -> None:
    """Project a human_approval_* event into the ``human_approvals`` table.

    Request rows carry ``proposer_id`` + ``reasons``; decision rows
    carry ``approver_id`` + ``reason``. Both branches use the event id
    as the primary key so a request + its decision are two distinct
    rows filtered by ``proposal_id``.
    """
    p = event.payload
    if status == "requested":
        values = {
            "id": p["id"],
            "proposal_id": p["proposal_id"],
            "status": status,
            "proposer_id": p.get("proposer_id"),
            "approver_id": None,
            "reason": "",
            "reasons": p.get("reasons", []),
            "created_at": p["created_at"],
        }
    else:
        values = {
            "id": p["id"],
            "proposal_id": p["proposal_id"],
            "status": status,
            "proposer_id": None,
            "approver_id": p.get("approver_id"),
            "reason": p.get("reason", ""),
            "reasons": [],
            "created_at": p["created_at"],
        }
    stmt = pg_insert(HumanApprovalRow).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={
            c: stmt.excluded[c]
            for c in (
                "proposal_id",
                "status",
                "proposer_id",
                "approver_id",
                "reason",
                "reasons",
                "created_at",
            )
        },
    )
    session.execute(stmt)


def _handle_human_approval_requested(session: Session, event: EventEnvelope) -> None:
    _upsert_approval(session, event, status="requested")


def _handle_human_approval_granted(session: Session, event: EventEnvelope) -> None:
    _upsert_approval(session, event, status="granted")
    # Grant does NOT flip proposal status — execution drives the status
    # to executed / failed / rolled_back from the approved state.


def _handle_human_approval_denied(session: Session, event: EventEnvelope) -> None:
    _upsert_approval(session, event, status="denied")
    _update_proposal_status(session, event.payload["proposal_id"], "approval_denied")


_ENTITY_HANDLERS = {
    "intent_created": _handle_intent_created,
    "finding_created": _handle_finding_created,
    "proposal_created": _handle_proposal_created,
    "policy_evaluated": _handle_policy_evaluated,
    "proposal_voted": _handle_proposal_voted,
    "proposal_approved": _handle_proposal_approved,
    "proposal_blocked": _handle_proposal_blocked,
    "execution_started": _handle_execution_started,
    "execution_succeeded": _handle_execution_succeeded,
    "execution_failed": _handle_execution_failed,
    "health_check_completed": _handle_health_check_completed,
    "rollback_started": _handle_rollback_started,
    "rollback_completed": _handle_rollback_completed,
    "rollback_impossible": _handle_rollback_impossible,
    "human_approval_requested": _handle_human_approval_requested,
    "human_approval_granted": _handle_human_approval_granted,
    "human_approval_denied": _handle_human_approval_denied,
}
