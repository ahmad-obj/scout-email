"""Persist source page provenance for social profiles.

Revision ID: 0005_social_profile_provenance
Revises: 0004_lead_source_queries
Create Date: 2026-08-30
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_social_profile_provenance"
down_revision: str | None = "0004_lead_source_queries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("social_profiles") as batch_op:
        batch_op.add_column(sa.Column("source_url", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("social_profiles") as batch_op:
        batch_op.drop_column("source_url")
