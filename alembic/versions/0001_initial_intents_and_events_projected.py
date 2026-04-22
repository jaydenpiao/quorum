"""initial: intents and events_projected tables

Revision ID: 0001
Revises:
Create Date: 2026-04-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "intents",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.String(length=4000), nullable=False),
        sa.Column("environment", sa.String(length=64), nullable=False),
        sa.Column("requested_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_intents_environment", "intents", ["environment"])
    op.create_index("ix_intents_requested_by", "intents", ["requested_by"])
    op.create_index("ix_intents_created_at", "intents", ["created_at"])

    op.create_table(
        "events_projected",
        sa.Column("event_id", sa.String(length=128), primary_key=True),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=True),
        sa.Column("projected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("envelope", JSONB, nullable=False),
    )
    op.create_index("ix_events_projected_event_type", "events_projected", ["event_type"])


def downgrade() -> None:
    op.drop_index("ix_events_projected_event_type", table_name="events_projected")
    op.drop_table("events_projected")
    op.drop_index("ix_intents_created_at", table_name="intents")
    op.drop_index("ix_intents_requested_by", table_name="intents")
    op.drop_index("ix_intents_environment", table_name="intents")
    op.drop_table("intents")
