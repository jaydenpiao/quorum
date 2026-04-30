"""vote llm metadata columns

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-30

Extends the existing votes projection row with server-owned LLM voting
audit metadata. This does not add a new event type or projection table;
the projector fills these columns from existing ``proposal_voted``
payloads and defaults historical votes to normal counted agent votes.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "votes",
        sa.Column("voter_kind", sa.String(length=32), nullable=False, server_default="agent"),
    )
    op.add_column("votes", sa.Column("llm_model", sa.String(length=128), nullable=True))
    op.add_column("votes", sa.Column("system_prompt_sha256", sa.String(length=64), nullable=True))
    op.add_column("votes", sa.Column("observed_event_cursor", sa.String(length=128), nullable=True))
    op.add_column(
        "votes",
        sa.Column("counted", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "votes",
        sa.Column(
            "counted_reason",
            sa.String(length=256),
            nullable=False,
            server_default="non_llm_vote",
        ),
    )


def downgrade() -> None:
    op.drop_column("votes", "counted_reason")
    op.drop_column("votes", "counted")
    op.drop_column("votes", "observed_event_cursor")
    op.drop_column("votes", "system_prompt_sha256")
    op.drop_column("votes", "llm_model")
    op.drop_column("votes", "voter_kind")
