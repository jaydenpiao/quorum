"""SQLAlchemy engine factory for the Postgres projection.

The engine is lazily created from ``DATABASE_URL``. If the env var is unset,
``make_engine()`` returns ``None`` and callers are expected to fall back to
``NoOpProjector``.
"""

from __future__ import annotations

import os

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def make_engine(database_url: str | None = None) -> Engine | None:
    """Return a SQLAlchemy Engine, or ``None`` when no DATABASE_URL is configured.

    Dialect prefix handling: ``postgresql+asyncpg`` (from the design doc)
    is rewritten to ``postgresql+psycopg`` for PR B's sync implementation.
    PR D+ may swap back to async once all entities project cleanly.
    """
    url = database_url if database_url is not None else os.environ.get("DATABASE_URL", "")
    url = url.strip()
    if not url:
        return None

    # Normalize async dialect hints to sync for the current implementation.
    if url.startswith("postgresql+asyncpg://"):
        url = "postgresql+psycopg://" + url[len("postgresql+asyncpg://") :]
    elif url.startswith("postgres://"):
        # Common shorthand from cloud providers — rewrite to SQLAlchemy form.
        url = "postgresql+psycopg://" + url[len("postgres://") :]

    # pool_pre_ping avoids stale-connection errors after idle periods.
    return create_engine(url, pool_pre_ping=True, future=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
