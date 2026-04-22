"""health_check_results table

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "health_check_results",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("execution_id", sa.String(length=128), nullable=False),
        sa.Column("proposal_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("passed", sa.Boolean, nullable=False),
        sa.Column("detail", sa.String(length=4000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_hcr_execution_id", "health_check_results", ["execution_id"])
    op.create_index("ix_hcr_proposal_id", "health_check_results", ["proposal_id"])
    op.create_index("ix_hcr_kind", "health_check_results", ["kind"])
    op.create_index("ix_hcr_created_at", "health_check_results", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_hcr_created_at", table_name="health_check_results")
    op.drop_index("ix_hcr_kind", table_name="health_check_results")
    op.drop_index("ix_hcr_proposal_id", table_name="health_check_results")
    op.drop_index("ix_hcr_execution_id", table_name="health_check_results")
    op.drop_table("health_check_results")
