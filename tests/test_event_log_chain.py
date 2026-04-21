"""Tests for the tamper-evident event log hash chain.

Each EventEnvelope carries `prev_hash` and `hash`. `hash` is sha256 of the
canonical JSON of a subset of envelope fields plus `prev_hash`. On startup
(and on-demand) the log can be verified — a mismatch means the log was
tampered with.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apps.api.app.domain.models import EventEnvelope
from apps.api.app.services.event_log import EventLog, EventLogTamperError, compute_event_hash


def _make_event(event_type: str = "thing_happened", payload: dict | None = None) -> EventEnvelope:
    return EventEnvelope(
        event_type=event_type,
        entity_type="thing",
        entity_id="thing_1",
        payload=payload or {"k": "v"},
    )


def test_append_computes_chain(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "events.jsonl")
    a = _make_event("a")
    b = _make_event("b")
    stored_a = log.append(a)
    stored_b = log.append(b)

    assert stored_a.prev_hash is None
    assert stored_a.hash is not None
    assert stored_b.prev_hash == stored_a.hash
    assert stored_b.hash is not None and stored_b.hash != stored_a.hash


def test_verify_on_clean_log(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "events.jsonl")
    log.append(_make_event("a"))
    log.append(_make_event("b"))
    log.append(_make_event("c"))
    # Should not raise.
    log.verify()


def test_verify_detects_tampered_payload(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    log = EventLog(path)
    log.append(_make_event("a", {"k": "original"}))
    log.append(_make_event("b"))

    # Tamper: rewrite the first line's payload without recomputing hashes.
    lines = path.read_text().splitlines()
    lines[0] = lines[0].replace('"original"', '"mutated"')
    path.write_text("\n".join(lines) + "\n")

    with pytest.raises(EventLogTamperError):
        log.verify()


def test_verify_detects_deleted_line(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    log = EventLog(path)
    log.append(_make_event("a"))
    log.append(_make_event("b"))
    log.append(_make_event("c"))

    # Tamper: drop the middle line; chain continuity breaks.
    lines = path.read_text().splitlines()
    path.write_text(lines[0] + "\n" + lines[2] + "\n")

    with pytest.raises(EventLogTamperError):
        log.verify()


def test_compute_event_hash_deterministic() -> None:
    a = EventEnvelope(
        id="evt_fixed",
        event_type="x",
        entity_type="y",
        entity_id="z",
        payload={"one": 1, "two": 2},
    )
    # Frozen timestamp via model_copy for determinism.
    a2 = a.model_copy(deep=True)
    # Payload field order must not matter.
    a2.payload = {"two": 2, "one": 1}

    h1 = compute_event_hash(a, prev_hash=None)
    h2 = compute_event_hash(a2, prev_hash=None)
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_verify_on_empty_log(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "events.jsonl")
    log.verify()  # no raise


def test_verify_endpoint_returns_ok_after_demo() -> None:
    """Integration: POST /demo/incident, then /events/verify should report ok."""
    from fastapi.testclient import TestClient

    from apps.api.app.main import app
    from tests.conftest import AUTH

    client = TestClient(app)
    client.post("/api/v1/demo/incident", headers=AUTH)
    response = client.get("/api/v1/events/verify")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["event_count"] > 0
    assert isinstance(body["last_hash"], str) and len(body["last_hash"]) == 64
