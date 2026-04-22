"""Tests for reconcile(event_log, projector).

Unit-only (no DB required). Uses a stub projector that records calls or
raises on demand to exercise the happy and failure paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from apps.api.app.domain.models import EventEnvelope
from apps.api.app.services.event_log import EventLog
from apps.api.app.services.reconcile import reconcile


@dataclass
class StubProjector:
    raise_on_event_types: set[str] = field(default_factory=set)
    calls: list[EventEnvelope] = field(default_factory=list)

    def apply(self, event: EventEnvelope) -> None:
        if event.event_type in self.raise_on_event_types:
            raise RuntimeError(f"stub projector failing on {event.event_type}")
        self.calls.append(event)


def _seed_log(path: Path, count: int = 3) -> EventLog:
    log = EventLog(path)
    for i in range(count):
        log.append(
            EventEnvelope(
                event_type="intent_created" if i == 0 else f"test_event_{i}",
                entity_type="thing",
                entity_id=f"thing_{i}",
                payload={"n": i},
            )
        )
    return log


def test_reconcile_empty_log(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "events.jsonl")
    report = reconcile(log, StubProjector())
    assert report.events_seen == 0
    assert report.events_applied == 0
    assert report.errors == []


def test_reconcile_applies_every_event_in_order(tmp_path: Path) -> None:
    log = _seed_log(tmp_path / "events.jsonl", count=4)
    stub = StubProjector()
    report = reconcile(log, stub)
    assert report.events_seen == 4
    assert report.events_applied == 4
    assert report.events_skipped_errors == 0
    # Events were applied in log order.
    assert [c.entity_id for c in stub.calls] == ["thing_0", "thing_1", "thing_2", "thing_3"]


def test_reconcile_continues_after_per_event_failure(tmp_path: Path) -> None:
    log = _seed_log(tmp_path / "events.jsonl", count=4)
    stub = StubProjector(raise_on_event_types={"test_event_2"})
    report = reconcile(log, stub)
    assert report.events_seen == 4
    assert report.events_applied == 3
    assert report.events_skipped_errors == 1
    assert len(report.errors) == 1
    assert "test_event_2" in report.errors[0]


def test_reconcile_verifies_hash_chain_before_applying(tmp_path: Path) -> None:
    log = _seed_log(tmp_path / "events.jsonl", count=3)
    # Tamper with the persisted file — corrupt the first line's payload.
    raw = log.path.read_text().splitlines()
    raw[0] = raw[0].replace('"n": 0', '"n": 999')
    log.path.write_text("\n".join(raw) + "\n")

    from apps.api.app.services.event_log import EventLogTamperError

    stub = StubProjector()
    with pytest.raises(EventLogTamperError):
        reconcile(log, stub)
    # Nothing was applied — verify() failed before the loop.
    assert stub.calls == []


def test_reconcile_is_idempotent_under_re_run(tmp_path: Path) -> None:
    """Running reconcile twice applies each event twice to the stub —
    real projectors are idempotent so the final state is identical."""
    log = _seed_log(tmp_path / "events.jsonl", count=2)
    stub = StubProjector()
    r1 = reconcile(log, stub)
    r2 = reconcile(log, stub)
    # Stub counts every call; it doesn't dedupe. That's intentional — the
    # idempotency guarantee belongs to the real Postgres projector, not
    # reconcile itself.
    assert r1.events_applied == 2
    assert r2.events_applied == 2
    assert len(stub.calls) == 4


def test_reconcile_report_summary_text() -> None:
    """The summary() method is used by the CLI."""
    from apps.api.app.services.reconcile import ReconcileReport

    report = ReconcileReport(events_seen=10, events_applied=9, events_skipped_errors=1)
    text = report.summary()
    assert "seen=10" in text
    assert "applied=9" in text
    assert "skipped_errors=1" in text
