"""Persist LLM generation metadata.

Revision ID: 0006_llm_generations
Revises: 0005_social_profile_provenance
Create Date: 2026-08-30
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_llm_generations"
down_revision: str | None = "0005_social_profile_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_generations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task", sa.String(length=80), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("prompt_version", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("repair_attempted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_llm_generations_task", "llm_generations", ["task"])
    op.create_index("ix_llm_generations_provider", "llm_generations", ["provider"])
    op.create_index("ix_llm_generations_prompt_version", "llm_generations", ["prompt_version"])
    op.create_index("ix_llm_generations_status", "llm_generations", ["status"])


def downgrade() -> None:
    op.drop_index("ix_llm_generations_status", table_name="llm_generations")
    op.drop_index("ix_llm_generations_prompt_version", table_name="llm_generations")
    op.drop_index("ix_llm_generations_provider", table_name="llm_generations")
    op.drop_index("ix_llm_generations_task", table_name="llm_generations")
    op.drop_table("llm_generations")
