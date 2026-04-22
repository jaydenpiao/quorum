"""SQLAlchemy ORM rows for the Postgres projection.

One row type per domain entity. Primary keys reuse the existing
``<prefix>_<12hex>`` IDs from ``apps/api/app/domain/models.py`` — we do
not introduce auto-increment surrogate keys. The projector is idempotent
against these PKs via ``INSERT ... ON CONFLICT DO UPDATE``.

PR B introduced IntentRow + EventProjectedRow. PR C adds the remaining
entity rows. A separate ``health_check_results`` table is deferred —
today's health-check outcomes are embedded inside ExecutionRecord, and
splitting them out needs the ``health_check_completed`` event type to
be emitted first (currently it isn't).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Project-wide declarative base. All ORM rows inherit from this."""


class IntentRow(Base):
    __tablename__ = "intents"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(String(4000))
    environment: Mapped[str] = mapped_column(String(64), index=True)
    requested_by: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class FindingRow(Base):
    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    intent_id: Mapped[str] = mapped_column(String(128), index=True)
    agent_id: Mapped[str] = mapped_column(String(128), index=True)
    summary: Mapped[str] = mapped_column(String(4000))
    evidence_refs: Mapped[list[Any]] = mapped_column(JSONB)
    confidence: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ProposalRow(Base):
    __tablename__ = "proposals"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    intent_id: Mapped[str] = mapped_column(String(128), index=True)
    agent_id: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(500))
    action_type: Mapped[str] = mapped_column(String(128), index=True)
    target: Mapped[str] = mapped_column(String(256))
    environment: Mapped[str] = mapped_column(String(64), index=True)
    risk: Mapped[str] = mapped_column(String(32), index=True)
    rationale: Mapped[str] = mapped_column(String(4000))
    evidence_refs: Mapped[list[Any]] = mapped_column(JSONB)
    rollback_steps: Mapped[list[Any]] = mapped_column(JSONB)
    health_checks: Mapped[list[Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class VoteRow(Base):
    __tablename__ = "votes"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(String(128), index=True)
    agent_id: Mapped[str] = mapped_column(String(128), index=True)
    decision: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class PolicyDecisionRow(Base):
    """Keyed on proposal_id. Re-evaluations upsert the same row."""

    __tablename__ = "policy_decisions"

    proposal_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    allowed: Mapped[bool] = mapped_column()
    requires_human: Mapped[bool] = mapped_column()
    votes_required: Mapped[int] = mapped_column(Integer)
    reasons: Mapped[list[Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ExecutionRow(Base):
    """One row per ExecutionRecord — each status transition generates a new id."""

    __tablename__ = "executions"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(String(128), index=True)
    actor_id: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    # Embedded HealthCheckResult list stays JSONB until we split it into
    # its own table (blocked on health_check_completed event emission).
    health_checks: Mapped[list[Any]] = mapped_column(JSONB)
    detail: Mapped[str] = mapped_column(String(4000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class HealthCheckResultRow(Base):
    """One row per health_check_completed event. Parent is `execution_id`."""

    __tablename__ = "health_check_results"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    execution_id: Mapped[str] = mapped_column(String(128), index=True)
    proposal_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(256))
    kind: Mapped[str] = mapped_column(String(32), index=True)
    passed: Mapped[bool] = mapped_column()
    detail: Mapped[str] = mapped_column(String(4000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class RollbackRow(Base):
    """One row per RollbackRecord — started / completed generate separate ids."""

    __tablename__ = "rollbacks"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(String(128), index=True)
    actor_id: Mapped[str] = mapped_column(String(128), index=True)
    steps: Mapped[list[Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class EventProjectedRow(Base):
    """One row per event ever applied. Enables idempotency + reconciliation.

    The projector upserts on (``event_id``) before touching the per-entity
    tables — if a retry comes in for an already-projected event, the
    per-entity upsert is skipped to avoid double-apply on non-idempotent
    side effects in future entity types.
    """

    __tablename__ = "events_projected"

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    event_hash: Mapped[str] = mapped_column(String(64))
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    projected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Store the full envelope for debugging + future replay.
    envelope: Mapped[dict[str, Any]] = mapped_column(JSONB)
