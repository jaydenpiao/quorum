"""Reconcile the Postgres projection from the canonical JSONL event log.

Use cases:

1. After a projector outage — some events landed in JSONL but didn't make
   it into Postgres. Reconcile re-applies them in order.
2. After bringing up a new Postgres (e.g. a new region, a test fixture).
3. After schema additions in PR C that projected previously-unknown
   event types as metadata-only.

What reconcile does NOT do:
- Does NOT edit the JSONL. Ever.
- Does NOT delete rows from Postgres that don't appear in the JSONL.
  Orphan detection is a separate concern; log but don't auto-fix.

The function is pure (well, effectful in PG but pure in terms of JSONL)
and idempotent — calling it twice produces the same final state because
the projector itself is idempotent.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from apps.api.app.services.event_log import EventLog
from apps.api.app.services.projector import Projector

_log = structlog.get_logger(__name__)


@dataclass
class ReconcileReport:
    """Summary of a reconcile run."""

    events_seen: int = 0
    events_applied: int = 0
    events_skipped_errors: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"seen={self.events_seen} applied={self.events_applied} "
            f"skipped_errors={self.events_skipped_errors}"
        )


def reconcile(event_log: EventLog, projector: Projector) -> ReconcileReport:
    """Re-apply every event in `event_log` to `projector`.

    The projector's idempotency (upsert-on-natural-PK plus the
    ``events_projected`` seen-set) means running this against a
    partially-populated Postgres is safe — it only writes rows that
    weren't there, and overwrites rows whose content differs.

    Per-event errors are logged and counted but don't abort the run —
    reconcile's job is to catch up as much as possible. If you need a
    strict "stop on first error" mode, call `projector.apply` in a loop
    from the caller; this function is intentionally forgiving.
    """
    report = ReconcileReport()
    # Use verify() so any chain break surfaces as a RuntimeError before
    # we start writing — a broken chain means the source-of-truth is
    # suspect and we should refuse to project from it.
    event_log.verify()

    for envelope in event_log.read_all():
        report.events_seen += 1
        try:
            projector.apply(envelope)
            report.events_applied += 1
        except Exception as exc:  # noqa: BLE001 — log and continue by design
            report.events_skipped_errors += 1
            message = f"{envelope.event_type} {envelope.id}: {type(exc).__name__}: {exc}"
            report.errors.append(message)
            _log.warning(
                "reconcile_event_failed",
                event_id=envelope.id,
                event_type=envelope.event_type,
                error=repr(exc),
            )

    _log.info(
        "reconcile_done",
        **{
            "events_seen": report.events_seen,
            "events_applied": report.events_applied,
            "events_skipped_errors": report.events_skipped_errors,
        },
    )
    return report
