"""remaining entity tables: findings, proposals, votes, policy_decisions, executions, rollbacks

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "findings",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("intent_id", sa.String(length=128), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("summary", sa.String(length=4000), nullable=False),
        sa.Column("evidence_refs", JSONB, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_findings_intent_id", "findings", ["intent_id"])
    op.create_index("ix_findings_agent_id", "findings", ["agent_id"])
    op.create_index("ix_findings_created_at", "findings", ["created_at"])

    op.create_table(
        "proposals",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("intent_id", sa.String(length=128), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("action_type", sa.String(length=128), nullable=False),
        sa.Column("target", sa.String(length=256), nullable=False),
        sa.Column("environment", sa.String(length=64), nullable=False),
        sa.Column("risk", sa.String(length=32), nullable=False),
        sa.Column("rationale", sa.String(length=4000), nullable=False),
        sa.Column("evidence_refs", JSONB, nullable=False),
        sa.Column("rollback_steps", JSONB, nullable=False),
        sa.Column("health_checks", JSONB, nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_proposals_intent_id", "proposals", ["intent_id"])
    op.create_index("ix_proposals_agent_id", "proposals", ["agent_id"])
    op.create_index("ix_proposals_action_type", "proposals", ["action_type"])
    op.create_index("ix_proposals_environment", "proposals", ["environment"])
    op.create_index("ix_proposals_risk", "proposals", ["risk"])
    op.create_index("ix_proposals_status", "proposals", ["status"])
    op.create_index("ix_proposals_created_at", "proposals", ["created_at"])

    op.create_table(
        "votes",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("proposal_id", sa.String(length=128), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=2000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_votes_proposal_id", "votes", ["proposal_id"])
    op.create_index("ix_votes_agent_id", "votes", ["agent_id"])
    op.create_index("ix_votes_decision", "votes", ["decision"])
    op.create_index("ix_votes_created_at", "votes", ["created_at"])

    op.create_table(
        "policy_decisions",
        sa.Column("proposal_id", sa.String(length=128), primary_key=True),
        sa.Column("allowed", sa.Boolean, nullable=False),
        sa.Column("requires_human", sa.Boolean, nullable=False),
        sa.Column("votes_required", sa.Integer, nullable=False),
        sa.Column("reasons", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "executions",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("proposal_id", sa.String(length=128), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("health_checks", JSONB, nullable=False),
        sa.Column("detail", sa.String(length=4000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_executions_proposal_id", "executions", ["proposal_id"])
    op.create_index("ix_executions_actor_id", "executions", ["actor_id"])
    op.create_index("ix_executions_status", "executions", ["status"])
    op.create_index("ix_executions_created_at", "executions", ["created_at"])

    op.create_table(
        "rollbacks",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("proposal_id", sa.String(length=128), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("steps", JSONB, nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_rollbacks_proposal_id", "rollbacks", ["proposal_id"])
    op.create_index("ix_rollbacks_actor_id", "rollbacks", ["actor_id"])
    op.create_index("ix_rollbacks_status", "rollbacks", ["status"])
    op.create_index("ix_rollbacks_created_at", "rollbacks", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_rollbacks_created_at", table_name="rollbacks")
    op.drop_index("ix_rollbacks_status", table_name="rollbacks")
    op.drop_index("ix_rollbacks_actor_id", table_name="rollbacks")
    op.drop_index("ix_rollbacks_proposal_id", table_name="rollbacks")
    op.drop_table("rollbacks")

    op.drop_index("ix_executions_created_at", table_name="executions")
    op.drop_index("ix_executions_status", table_name="executions")
    op.drop_index("ix_executions_actor_id", table_name="executions")
    op.drop_index("ix_executions_proposal_id", table_name="executions")
    op.drop_table("executions")

    op.drop_table("policy_decisions")

    op.drop_index("ix_votes_created_at", table_name="votes")
    op.drop_index("ix_votes_decision", table_name="votes")
    op.drop_index("ix_votes_agent_id", table_name="votes")
    op.drop_index("ix_votes_proposal_id", table_name="votes")
    op.drop_table("votes")

    op.drop_index("ix_proposals_created_at", table_name="proposals")
    op.drop_index("ix_proposals_status", table_name="proposals")
    op.drop_index("ix_proposals_risk", table_name="proposals")
    op.drop_index("ix_proposals_environment", table_name="proposals")
    op.drop_index("ix_proposals_action_type", table_name="proposals")
    op.drop_index("ix_proposals_agent_id", table_name="proposals")
    op.drop_index("ix_proposals_intent_id", table_name="proposals")
    op.drop_table("proposals")

    op.drop_index("ix_findings_created_at", table_name="findings")
    op.drop_index("ix_findings_agent_id", table_name="findings")
    op.drop_index("ix_findings_intent_id", table_name="findings")
    op.drop_table("findings")
