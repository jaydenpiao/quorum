"""SQLAlchemy database layer.

Holds the ORM models and engine bootstrap for the Postgres-backed
derived read-model. Nothing here changes the canonical JSONL event log —
the DB is always reconstructible from the log.
"""
