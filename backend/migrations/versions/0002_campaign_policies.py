"""Persist campaign qualification and follow-up policies.

Revision ID: 0002_campaign_policies
Revises: 0001_initial_schema
Create Date: 2026-08-30
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0002_campaign_policies"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """CREATE TABLE campaign_policies (
            campaign_id INTEGER PRIMARY KEY REFERENCES campaigns(id) ON DELETE CASCADE,
            qualification_json TEXT NOT NULL DEFAULT '{}',
            follow_up_json TEXT NOT NULL DEFAULT '{}'
        )"""
    )
    op.execute(
        """INSERT INTO campaign_policies(campaign_id, qualification_json, follow_up_json)
        SELECT id, '{}', '{}' FROM campaigns"""
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS campaign_policies")
