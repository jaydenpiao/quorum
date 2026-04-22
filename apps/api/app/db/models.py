"""SQLAlchemy ORM rows for the Postgres projection.

One row type per domain entity. Primary keys reuse the existing
``<prefix>_<12hex>`` IDs from ``apps/api/app/domain/models.py`` — we do
not introduce auto-increment surrogate keys. The projector is idempotent
against these PKs via ``INSERT ... ON CONFLICT DO UPDATE``.

PR B only exercises ``IntentRow`` + ``EventProjectedRow`` (the metadata
table that tracks the last applied event id/hash for reconciliation).
Remaining entities land in PR C.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String
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
