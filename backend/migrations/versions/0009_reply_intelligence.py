"""Persist structured reply intelligence.

Revision ID: 0009_reply_intelligence
Revises: 0008_human_approval_events
Create Date: 2026-08-31
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_reply_intelligence"
down_revision: str | None = "0008_human_approval_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reply_intelligence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "reply_id",
            sa.Integer(),
            sa.ForeignKey("replies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("intent_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("questions_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("recommended_action", sa.String(length=120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.UniqueConstraint("reply_id", name="uq_reply_intelligence_reply"),
    )
    op.create_index(
        "ix_reply_intelligence_reply_id",
        "reply_intelligence",
        ["reply_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_reply_intelligence_reply_id", table_name="reply_intelligence")
    op.drop_table("reply_intelligence")
