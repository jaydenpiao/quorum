"""human_approvals table

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-22

One row per ``human_approval_*`` event. The ``status`` column
distinguishes ``requested`` (marker) from ``granted`` / ``denied``
(decisions). Multiple rows can share a ``proposal_id`` — one request +
at most one decision — so the primary key is the event's own id.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "human_approvals",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("proposal_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        # ``proposer_id`` populated for requests; ``approver_id`` for decisions.
        # Both nullable because they're kind-dependent.
        sa.Column("proposer_id", sa.String(length=128), nullable=True),
        sa.Column("approver_id", sa.String(length=128), nullable=True),
        sa.Column("reason", sa.String(length=2000), nullable=False, server_default=""),
        # Policy reasons carried on the request row for audit context.
        sa.Column("reasons", JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_human_approvals_proposal_id", "human_approvals", ["proposal_id"])
    op.create_index("ix_human_approvals_status", "human_approvals", ["status"])
    op.create_index("ix_human_approvals_created_at", "human_approvals", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_human_approvals_created_at", table_name="human_approvals")
    op.drop_index("ix_human_approvals_status", table_name="human_approvals")
    op.drop_index("ix_human_approvals_proposal_id", table_name="human_approvals")
    op.drop_table("human_approvals")
