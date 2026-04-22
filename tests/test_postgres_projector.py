"""Tests for PostgresProjector.

Unit tests run against SQLite in-memory for the schema subset we care about.
Full integration tests (marked `integration`) require a live Postgres; run
with `uv run pytest -m integration` and `DATABASE_URL` set. CI skips them
by default via the `-m 'not integration'` addopt in pyproject.toml.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from apps.api.app.db.engine import make_engine
from apps.api.app.db.models import Base, EventProjectedRow, IntentRow
from apps.api.app.domain.models import EventEnvelope, Intent


def _make_intent_event() -> EventEnvelope:
    """Build an enriched envelope for a fresh intent_created event."""
    intent = Intent(
        title="Investigate p99 latency",
        description="Rolled out v184; errors spiked",
        environment="prod",
        requested_by="test-operator",
    )
    envelope = EventEnvelope(
        event_type="intent_created",
        entity_type="intent",
        entity_id=intent.id,
        payload=intent.model_dump(mode="json"),
    )
    # Simulate what EventLog.append populates before calling projector.apply.
    return envelope.model_copy(update={"prev_hash": None, "hash": "a" * 64})


def test_make_engine_returns_none_without_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert make_engine() is None


def test_make_engine_normalizes_postgres_shorthand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`postgres://` → `postgresql+psycopg://` and `+asyncpg` → `+psycopg`."""
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@h/d")
    engine = make_engine()
    assert engine is not None
    assert engine.url.drivername == "postgresql+psycopg"
    engine.dispose()

    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/d")
    engine = make_engine()
    assert engine is not None
    assert engine.url.drivername == "postgresql+psycopg"
    engine.dispose()


def test_dispatch_table_covers_all_expected_event_types() -> None:
    """Every event type emitted by the core state machine must have a handler."""
    from apps.api.app.services import postgres_projector

    expected = {
        "intent_created",
        "finding_created",
        "proposal_created",
        "policy_evaluated",
        "proposal_voted",
        "proposal_approved",
        "proposal_blocked",
        "execution_started",
        "execution_succeeded",
        "execution_failed",
        "rollback_started",
        "rollback_completed",
    }
    registered = set(postgres_projector._ENTITY_HANDLERS.keys())
    missing = expected - registered
    assert not missing, f"missing handlers: {sorted(missing)}"


def test_projector_requires_enriched_envelope(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """An envelope lacking `hash` must raise — EventLog should never hand us one."""
    from apps.api.app.services.postgres_projector import PostgresProjector

    # We don't need a real engine for this test — the guard runs before any DB I/O.
    engine = create_engine("sqlite:///:memory:", future=True)
    projector = PostgresProjector(engine)

    raw = EventEnvelope(
        event_type="intent_created",
        entity_type="intent",
        entity_id="intent_abc",
        payload={},
    )
    with pytest.raises(ValueError, match="enriched envelope"):
        projector.apply(raw)
    engine.dispose()


# -------------------------------------------------------------------------
# Integration tests — require live Postgres.
# -------------------------------------------------------------------------


def _live_engine() -> Engine | None:
    """Return an engine against DATABASE_URL, or None if not configured."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return None
    return make_engine(url)


@pytest.fixture
def live_engine() -> Engine:
    engine = _live_engine()
    if engine is None:
        pytest.skip("DATABASE_URL not set; skipping integration test")
    # Ensure a clean slate for each integration test. We create + drop the
    # schema here rather than relying on Alembic, since the CI pipeline for
    # these tests is its own lane and doesn't own migration history.
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.mark.integration
def test_apply_intent_created_upserts_row(live_engine: Engine) -> None:
    from apps.api.app.services.postgres_projector import PostgresProjector

    event = _make_intent_event()
    PostgresProjector(live_engine).apply(event)

    with Session(live_engine) as session:
        rows = session.query(IntentRow).all()
        assert len(rows) == 1
        assert rows[0].id == event.payload["id"]
        assert rows[0].title == event.payload["title"]

        projected = session.query(EventProjectedRow).all()
        assert len(projected) == 1
        assert projected[0].event_id == event.id
        assert projected[0].event_hash == event.hash


@pytest.mark.integration
def test_apply_is_idempotent(live_engine: Engine) -> None:
    from apps.api.app.services.postgres_projector import PostgresProjector

    event = _make_intent_event()
    projector = PostgresProjector(live_engine)

    projector.apply(event)
    projector.apply(event)
    projector.apply(event)

    with Session(live_engine) as session:
        assert session.query(IntentRow).count() == 1
        assert session.query(EventProjectedRow).count() == 1


@pytest.mark.integration
def test_apply_records_unknown_event_types_without_entity_writes(
    live_engine: Engine,
) -> None:
    from apps.api.app.services.postgres_projector import PostgresProjector

    envelope = EventEnvelope(
        event_type="something_unmapped_yet",
        entity_type="future",
        entity_id="future_xyz",
        payload={"k": "v"},
    )
    envelope = envelope.model_copy(update={"prev_hash": None, "hash": "b" * 64})

    PostgresProjector(live_engine).apply(envelope)

    with Session(live_engine) as session:
        assert session.query(IntentRow).count() == 0
        projected = session.query(EventProjectedRow).all()
        assert len(projected) == 1
        assert projected[0].event_type == "something_unmapped_yet"


@pytest.mark.integration
def test_hash_collision_on_same_id_raises(live_engine: Engine) -> None:
    """Two events with the same id but different hashes must blow up loudly."""
    from apps.api.app.services.postgres_projector import PostgresProjector

    projector = PostgresProjector(live_engine)
    original = _make_intent_event()
    projector.apply(original)

    tampered = original.model_copy(update={"hash": "f" * 64})
    with pytest.raises(RuntimeError, match="different hash"):
        projector.apply(tampered)


@pytest.mark.integration
def test_created_at_timezone_preserved(live_engine: Engine) -> None:
    """Postgres timestamptz round-trips UTC without reinterpretation."""
    from apps.api.app.services.postgres_projector import PostgresProjector

    event = _make_intent_event()
    PostgresProjector(live_engine).apply(event)

    with Session(live_engine) as session:
        row = session.query(IntentRow).one()
        assert row.created_at.tzinfo is not None
        assert row.created_at.astimezone(UTC).tzinfo == UTC
        # Round-trip within tolerance (Postgres stores microseconds).
        assert (
            abs(
                (
                    row.created_at - datetime.fromisoformat(event.payload["created_at"])
                ).total_seconds()
            )
            < 1.0
        )
