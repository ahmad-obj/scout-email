"""Persist Writer generation metadata.

Revision ID: 0007_draft_generation_metadata
Revises: 0006_llm_generations
Create Date: 2026-08-30
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_draft_generation_metadata"
down_revision: str | None = "0006_llm_generations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "draft_generation_metadata",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "draft_id",
            sa.Integer(),
            sa.ForeignKey("email_drafts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("playbook_hash", sa.String(length=64), nullable=False),
        sa.Column("strategy_label", sa.String(length=200), nullable=False),
        sa.Column("recent_similarity", sa.Float(), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.UniqueConstraint("draft_id", name="uq_draft_generation_metadata_draft"),
    )
    op.create_index(
        "ix_draft_generation_metadata_draft_id",
        "draft_generation_metadata",
        ["draft_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_draft_generation_metadata_draft_id",
        table_name="draft_generation_metadata",
    )
    op.drop_table("draft_generation_metadata")
