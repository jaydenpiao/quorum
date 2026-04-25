"""SQLAlchemy engine factory for the Postgres projection.

The engine is lazily created from ``DATABASE_URL``. If the env var is unset,
``make_engine()`` returns ``None`` and callers are expected to fall back to
``NoOpProjector``.
"""

from __future__ import annotations

import os

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def normalize_database_url(database_url: str) -> str:
    """Return a URL that uses the repo's installed sync Postgres driver."""
    url = database_url.strip()
    if url.startswith("postgresql+asyncpg://"):
        return "postgresql+psycopg://" + url[len("postgresql+asyncpg://") :]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def make_engine(database_url: str | None = None) -> Engine | None:
    """Return a SQLAlchemy Engine, or ``None`` when no DATABASE_URL is configured.

    Dialect prefix handling: cloud/provider defaults such as
    ``postgresql://`` and ``postgres://`` plus the design-doc
    ``postgresql+asyncpg://`` form are rewritten to
    ``postgresql+psycopg://`` for the current sync implementation.
    """
    url = database_url if database_url is not None else os.environ.get("DATABASE_URL", "")
    url = url.strip()
    if not url:
        return None

    url = normalize_database_url(url)

    # pool_pre_ping avoids stale-connection errors after idle periods.
    return create_engine(url, pool_pre_ping=True, future=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
