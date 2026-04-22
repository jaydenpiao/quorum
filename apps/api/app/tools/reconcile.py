"""CLI: re-apply the JSONL event log to the Postgres projection.

Usage:

    # default: read DATABASE_URL from env, use the canonical log path
    uv run python -m apps.api.app.tools.reconcile

    # explicit arguments
    uv run python -m apps.api.app.tools.reconcile \
        --log-path data/events.jsonl \
        --database-url postgresql+psycopg://user:pass@host/db

    # dry run (NoOp projector — just re-verifies the hash chain, no writes)
    uv run python -m apps.api.app.tools.reconcile --dry-run

Safe to run repeatedly; the projector is idempotent.
"""

from __future__ import annotations

import argparse
import json
import sys

from apps.api.app.db.engine import make_engine
from apps.api.app.logging_config import configure_logging
from apps.api.app.services.event_log import EventLog
from apps.api.app.services.postgres_projector import PostgresProjector
from apps.api.app.services.projector import NoOpProjector, Projector
from apps.api.app.services.reconcile import reconcile


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="quorum-reconcile")
    parser.add_argument(
        "--log-path",
        default="data/events.jsonl",
        help="Path to the JSONL event log (default: data/events.jsonl)",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Postgres URL; defaults to DATABASE_URL env var",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use NoOpProjector — verifies the hash chain without writing to PG",
    )
    parser.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Report format",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    projector: Projector
    if args.dry_run:
        projector = NoOpProjector()
    else:
        engine = make_engine(args.database_url)
        if engine is None:
            print(
                "error: DATABASE_URL not set and --database-url not provided",
                file=sys.stderr,
            )
            return 2
        projector = PostgresProjector(engine)

    event_log = EventLog(args.log_path)
    report = reconcile(event_log, projector)

    if args.output == "json":
        print(
            json.dumps(
                {
                    "events_seen": report.events_seen,
                    "events_applied": report.events_applied,
                    "events_skipped_errors": report.events_skipped_errors,
                    "errors": report.errors,
                }
            )
        )
    else:
        print(report.summary())
        for err in report.errors:
            print(f"  error: {err}", file=sys.stderr)

    # Exit non-zero iff any event failed to project — CI-style signaling.
    return 1 if report.events_skipped_errors > 0 else 0


if __name__ == "__main__":  # pragma: no cover — CLI entry point
    sys.exit(main())
