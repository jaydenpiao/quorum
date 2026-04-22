"""Tests for the Projector Protocol and NoOpProjector default.

Phase 3 capstone PR A: scaffolding only. The JSONL log remains authoritative;
projectors are a best-effort, eventually-consistent derivation. Failure in
the projector MUST NOT revert the JSONL write — the product's audit promise
depends on the log being the single source of truth.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apps.api.app.domain.models import EventEnvelope
from apps.api.app.services.event_log import EventLog
from apps.api.app.services.projector import NoOpProjector, Projector


def _make_event() -> EventEnvelope:
    return EventEnvelope(
        event_type="test_event",
        entity_type="thing",
        entity_id="thing_1",
        payload={"k": "v"},
    )


def test_noop_projector_returns_none() -> None:
    NoOpProjector().apply(_make_event())  # no raise, no side effects


def test_noop_projector_is_a_projector() -> None:
    """NoOpProjector satisfies the Projector Protocol at type-check time."""
    projector: Projector = NoOpProjector()  # type: ignore[unused-ignore]
    projector.apply(_make_event())


def test_event_log_default_projector_is_noop(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "events.jsonl")
    assert isinstance(log.projector, NoOpProjector)


def test_event_log_accepts_custom_projector(tmp_path: Path) -> None:
    class Counting:
        def __init__(self) -> None:
            self.calls: list[EventEnvelope] = []

        def apply(self, event: EventEnvelope) -> None:
            self.calls.append(event)

    counter = Counting()
    log = EventLog(tmp_path / "events.jsonl", projector=counter)
    returned = log.append(_make_event())
    assert len(counter.calls) == 1
    # Projector receives the *enriched* envelope (hash + prev_hash bound).
    assert counter.calls[0].id == returned.id
    assert counter.calls[0].hash == returned.hash
    assert counter.calls[0].prev_hash == returned.prev_hash


def test_projector_failure_does_not_revert_log_write(tmp_path: Path) -> None:
    """A projector that raises must not affect the JSONL append contract."""

    class Exploding:
        def apply(self, event: EventEnvelope) -> None:
            raise RuntimeError("projection crashed")

    path = tmp_path / "events.jsonl"
    log = EventLog(path, projector=Exploding())
    returned = log.append(_make_event())
    # The write must have landed in the JSONL on disk.
    assert path.read_text().strip(), "expected at least one line written"
    # The chain is intact.
    assert returned.hash is not None
    log.verify()  # does not raise


def test_projector_called_after_successful_write_only(tmp_path: Path) -> None:
    """If the JSONL write itself fails, the projector is not called."""

    class Counting:
        def __init__(self) -> None:
            self.calls: list[EventEnvelope] = []

        def apply(self, event: EventEnvelope) -> None:
            self.calls.append(event)

    counter = Counting()
    log = EventLog(tmp_path / "events.jsonl", projector=counter)

    # Force a write failure by monkey-patching the path to a directory we
    # can't write to (a closed file descriptor would also work).
    log.path = Path("/nonexistent-directory-12345/events.jsonl")  # noqa: S108 — test-only path
    with pytest.raises(OSError):
        log.append(_make_event())
    # Projector not called because write raised before we got there.
    assert counter.calls == []
