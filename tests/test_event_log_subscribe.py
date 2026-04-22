"""Tests for EventLog.subscribe / unsubscribe / notification path.

Pure EventLog-level — the SSE route smoke-test lives in test_sse_stream.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from apps.api.app.domain.models import EventEnvelope
from apps.api.app.services.event_log import EventLog


def _envelope(event_type: str = "intent_created") -> EventEnvelope:
    return EventEnvelope(
        event_type=event_type,
        entity_type="intent",
        entity_id="intent_abc",
        payload={"id": "intent_abc", "title": "t"},
    )


def test_subscribe_fires_on_append(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "events.jsonl")
    seen: list[EventEnvelope] = []
    log.subscribe(seen.append)

    log.append(_envelope("intent_created"))
    log.append(_envelope("finding_created"))

    assert len(seen) == 2
    assert [e.event_type for e in seen] == ["intent_created", "finding_created"]


def test_subscriber_sees_enriched_envelope(tmp_path: Path) -> None:
    """Subscribers must see prev_hash + hash populated — that's the
    contract; a subscriber using the hash chain for anything (e.g.
    SSE dedupe) depends on it."""
    log = EventLog(tmp_path / "events.jsonl")
    captured: list[EventEnvelope] = []
    log.subscribe(captured.append)

    log.append(_envelope())

    (event,) = captured
    assert event.hash is not None
    assert event.prev_hash is None  # first event in the chain


def test_unsubscribe_stops_notifications(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "events.jsonl")
    seen: list[EventEnvelope] = []
    unsubscribe = log.subscribe(seen.append)

    log.append(_envelope())
    unsubscribe()
    log.append(_envelope())

    assert len(seen) == 1


def test_double_unsubscribe_is_safe(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "events.jsonl")
    seen: list[EventEnvelope] = []
    unsubscribe = log.subscribe(seen.append)

    unsubscribe()
    unsubscribe()  # no-op the second time; must not raise


def test_multiple_subscribers_all_fire(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "events.jsonl")
    a: list[EventEnvelope] = []
    b: list[EventEnvelope] = []
    log.subscribe(a.append)
    log.subscribe(b.append)

    log.append(_envelope())

    assert len(a) == 1
    assert len(b) == 1


def test_subscriber_exception_does_not_block_others(tmp_path: Path) -> None:
    """A buggy callback must not eat events from siblings."""
    log = EventLog(tmp_path / "events.jsonl")
    good: list[EventEnvelope] = []

    def bad_subscriber(_event: EventEnvelope) -> None:
        raise RuntimeError("kaboom")

    log.subscribe(bad_subscriber)
    log.subscribe(good.append)

    log.append(_envelope())

    assert len(good) == 1  # sibling still received


def test_subscriber_exception_does_not_corrupt_log(tmp_path: Path) -> None:
    """A subscriber exception must not prevent the JSONL write."""
    log = EventLog(tmp_path / "events.jsonl")

    def bad_subscriber(_event: EventEnvelope) -> None:
        raise RuntimeError("kaboom")

    log.subscribe(bad_subscriber)

    log.append(_envelope("intent_created"))
    log.append(_envelope("finding_created"))

    events = log.read_all()
    assert len(events) == 2
    assert [e.event_type for e in events] == ["intent_created", "finding_created"]


def test_unsubscribe_during_iteration_is_safe(tmp_path: Path) -> None:
    """Callback that unsubscribes itself mid-notify must not crash.

    We snapshot the subscriber list before iterating (see
    event_log.py:append), so a self-unsubscribe only affects future
    appends, not the current one.
    """
    log = EventLog(tmp_path / "events.jsonl")
    seen: list[EventEnvelope] = []

    unsubscribers: list[Any] = []

    def self_removing(event: EventEnvelope) -> None:
        seen.append(event)
        if unsubscribers:
            unsubscribers[0]()

    unsub = log.subscribe(self_removing)
    unsubscribers.append(unsub)

    log.append(_envelope())
    log.append(_envelope())

    assert len(seen) == 1  # self-unsub took effect for the second append
