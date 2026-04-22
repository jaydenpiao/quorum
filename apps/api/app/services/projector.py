"""Event-log projectors.

A projector consumes `EventEnvelope`s after they've been durably appended to
the JSONL log and materializes them into a secondary store (e.g. Postgres
for query-friendly read models). The JSONL log is **always canonical**; a
projector's view is eventually consistent with it and always reconstructible
from it via re-play.

Contract:

- `apply(event)` is called **after** `EventLog.append` has written the line
  to disk and bound it into the hash chain. The envelope handed to the
  projector has `prev_hash` and `hash` populated.
- A projector must be **idempotent**: re-applying the same event must not
  cause duplicate writes in the target store. PR B+ will rely on this
  property when re-projecting the log from scratch during reconciliation.
- A projector **must not mutate** the envelope.
- A projector raising any exception must not revert the JSONL write —
  `EventLog.append` catches and logs; the audit trail stays authoritative.

This module provides the Protocol and a `NoOpProjector` default so the
rest of the codebase can unconditionally call `projector.apply(event)`.
Real Postgres-backed projectors land in PR B.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from apps.api.app.domain.models import EventEnvelope


@runtime_checkable
class Projector(Protocol):
    """Protocol every projector implementation satisfies."""

    def apply(self, event: EventEnvelope) -> None:  # pragma: no cover — abstract
        ...


class NoOpProjector:
    """Do nothing. The default for dev and tests."""

    def apply(self, event: EventEnvelope) -> None:
        return None
