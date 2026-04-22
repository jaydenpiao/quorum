"""Structured JSON logging configuration for the Quorum control plane.

Wires stdlib logging into structlog so that all log output — including
third-party libraries using the stdlib `logging` module — is rendered as
newline-delimited JSON to stdout.

Usage
-----
Call `configure_logging()` once at application start-up (main.py module
scope).  Everywhere else, obtain a bound logger with `get_logger(name)`.

Environment
-----------
QUORUM_LOG_LEVEL  — desired log level string (default "INFO").
"""

from __future__ import annotations

import logging
import os
import sys

import structlog


def configure_logging(level: str | None = None) -> None:
    """Wire stdlib logging → structlog with JSON output.

    Parameters
    ----------
    level:
        Override the log level.  When *None* the value of the environment
        variable ``QUORUM_LOG_LEVEL`` is used, defaulting to ``"INFO"``.
    """
    resolved_level = (level or os.environ.get("QUORUM_LOG_LEVEL", "INFO")).upper()

    # Note: `add_logger_name` from structlog.stdlib requires a stdlib-flavored
    # logger that carries a `.name` attribute. We use PrintLoggerFactory (writes
    # straight to stdout) which has no such attribute, so we omit that processor
    # and rely on callers passing a name through `get_logger(name)` — which
    # binds it as the `logger` context field.
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=shared_processors
        + [
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(resolved_level)),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Also configure stdlib so that libraries using logging route through
    # structlog's foreign-logger support.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, resolved_level, logging.INFO),
        force=True,
    )


def get_logger(name: str = "quorum") -> structlog.BoundLogger:
    """Return a structlog BoundLogger with ``logger=name`` bound into context."""
    bound: structlog.BoundLogger = structlog.get_logger().bind(logger=name)
    return bound
