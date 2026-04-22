from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from threading import Lock

import structlog

from apps.api.app.domain.models import EventEnvelope
from apps.api.app.services.projector import NoOpProjector, Projector

EventCallback = Callable[[EventEnvelope], None]

_log = structlog.get_logger(__name__)


class EventLogTamperError(RuntimeError):
    """Raised when the event log's hash chain does not verify.

    A tamper error means the persisted JSONL file has been modified outside
    the EventLog API (edit, truncate, reorder, or delete). The log is the
    product's audit trail; a broken chain is a P0 integrity incident and the
    service should refuse to continue operating on it.
    """


def _canonical_bytes(envelope: EventEnvelope, prev_hash: str | None) -> bytes:
    """Produce the canonical byte representation hashed into `envelope.hash`.

    Payloads are re-serialized with sorted keys so that pure field re-ordering
    does not change the hash — only semantic content changes do.
    """
    material = {
        "id": envelope.id,
        "event_type": envelope.event_type,
        "entity_type": envelope.entity_type,
        "entity_id": envelope.entity_id,
        "ts": envelope.ts.isoformat(),
        "payload": envelope.payload,
        "prev_hash": prev_hash,
    }
    return json.dumps(material, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_event_hash(envelope: EventEnvelope, prev_hash: str | None) -> str:
    """Return the sha256 hex digest that binds `envelope` into the chain."""
    return hashlib.sha256(_canonical_bytes(envelope, prev_hash)).hexdigest()


class EventLog:
    def __init__(self, path: str | Path, projector: Projector | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = Lock()
        if not self.path.exists():
            self.path.touch()
        self._last_hash: str | None = self._read_last_hash()
        # Projector is called after every successful append. Default is a
        # no-op; real Postgres projection is added in a later PR.
        self.projector: Projector = projector or NoOpProjector()
        # Pub/sub for live consumers (SSE stream, future tail-tools).
        # Invoked after fsync + projector so subscribers only see events
        # that have landed canonically. Subscriber failures are logged
        # + swallowed — a bad subscriber never blocks the append path.
        self._subscribers: list[EventCallback] = []
        self._subscribers_lock = Lock()

    def _read_last_hash(self) -> str | None:
        """Recover the in-memory `last_hash` cache by scanning the file tail."""
        if not self.path.exists():
            return None
        last: str | None = None
        with self.path.open("r", encoding="utf-8") as handle:
            for raw in handle:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                    last = data.get("hash")
                except json.JSONDecodeError:
                    continue
        return last

    def append(self, event: EventEnvelope) -> EventEnvelope:
        """Append `event` to the log, binding it into the hash chain.

        Returns the stored envelope with `prev_hash` and `hash` populated.
        Callers must use the returned envelope if they need those fields.

        The projector is called **after** the JSONL write succeeds. If the
        projector raises, the exception is logged and swallowed: the JSONL
        is the canonical source of truth, so a projector failure is a
        degraded-read-model signal, not a data-integrity event.
        """
        with self.lock:
            prev_hash = self._last_hash
            event = event.model_copy(update={"prev_hash": prev_hash})
            event_hash = compute_event_hash(event, prev_hash)
            event = event.model_copy(update={"hash": event_hash})
            line = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            self._last_hash = event_hash

        # Projector is called outside the lock so a slow projector never
        # blocks other writers. The envelope is immutable after return here.
        try:
            self.projector.apply(event)
        except Exception as exc:  # noqa: BLE001 — by design; never revert the log write
            _log.warning(
                "projector_apply_failed",
                event_id=event.id,
                event_type=event.event_type,
                projector=type(self.projector).__name__,
                error=repr(exc),
            )

        # Notify live subscribers. Snapshot the subscriber list under the
        # lock so concurrent subscribe/unsubscribe doesn't race with the
        # iteration; invoke callbacks outside the lock so a slow
        # subscriber can't block writers.
        with self._subscribers_lock:
            callbacks = list(self._subscribers)
        for cb in callbacks:
            try:
                cb(event)
            except Exception as exc:  # noqa: BLE001 — subscriber failure is not our problem
                _log.warning(
                    "event_log_subscriber_failed",
                    event_id=event.id,
                    event_type=event.event_type,
                    error=repr(exc),
                )

        return event

    def read_all(self) -> list[EventEnvelope]:
        events: list[EventEnvelope] = []
        if not self.path.exists():
            return events
        with self.path.open("r", encoding="utf-8") as handle:
            for raw in handle:
                raw = raw.strip()
                if not raw:
                    continue
                events.append(EventEnvelope.model_validate(json.loads(raw)))
        return events

    def verify(self) -> None:
        """Re-walk the chain and raise EventLogTamperError on any mismatch."""
        prev_hash: str | None = None
        for index, envelope in enumerate(self.read_all()):
            if envelope.prev_hash != prev_hash:
                raise EventLogTamperError(
                    f"event #{index} ({envelope.id}): prev_hash mismatch — "
                    f"expected {prev_hash!r}, stored {envelope.prev_hash!r}"
                )
            expected_hash = compute_event_hash(envelope, prev_hash)
            if envelope.hash != expected_hash:
                raise EventLogTamperError(
                    f"event #{index} ({envelope.id}): hash mismatch — "
                    f"payload or header modified since write"
                )
            prev_hash = envelope.hash

    def reset(self) -> None:
        """Reset the log. Only for dev/test — never call from production paths."""
        with self.lock:
            self.path.write_text("", encoding="utf-8")
            self._last_hash = None

    def subscribe(self, callback: EventCallback) -> Callable[[], None]:
        """Register a callback that fires for every event `append()` stores.

        Returns an ``unsubscribe()`` closure — call it to deregister.
        Callbacks are invoked after the JSONL write fsyncs and the
        projector runs, so a subscriber can trust that any envelope it
        sees has landed canonically. Failures inside a callback are
        logged + swallowed; they never surface into the append path.

        Thread-safe: multiple subscribers + concurrent subscribe/
        unsubscribe are supported. The callback runs on the same thread
        that called ``append()`` (no scheduling / no threadpool), so
        subscribers needing async delivery should hand off via their
        own queue.
        """
        with self._subscribers_lock:
            self._subscribers.append(callback)

        def unsubscribe() -> None:
            with self._subscribers_lock:
                try:
                    self._subscribers.remove(callback)
                except ValueError:
                    # Already removed (double-unsubscribe) — harmless.
                    pass

        return unsubscribe
