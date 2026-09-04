"""Persist structured Critic assertion audits.

Revision ID: 0010_email_review_audits
Revises: 0009_reply_intelligence
Create Date: 2026-09-04
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_email_review_audits"
down_revision: str | None = "0009_reply_intelligence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "email_review_audits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "review_id",
            sa.Integer(),
            sa.ForeignKey("email_reviews.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "draft_id",
            sa.Integer(),
            sa.ForeignKey("email_drafts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("audit_json", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.UniqueConstraint("review_id", name="uq_email_review_audits_review"),
    )
    op.create_index(
        "ix_email_review_audits_review_id",
        "email_review_audits",
        ["review_id"],
    )
    op.create_index(
        "ix_email_review_audits_draft_id",
        "email_review_audits",
        ["draft_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_email_review_audits_draft_id", table_name="email_review_audits")
    op.drop_index("ix_email_review_audits_review_id", table_name="email_review_audits")
    op.drop_table("email_review_audits")
