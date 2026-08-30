"""Add query-level scouting provenance.

Revision ID: 0004_lead_source_queries
Revises: 0003_job_runtime
Create Date: 2026-08-30
"""
from collections.abc import Sequence
from alembic import op

revision: str = "0004_lead_source_queries"
down_revision: str | None = "0003_job_runtime"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""CREATE TABLE lead_source_queries (
        id INTEGER PRIMARY KEY,
        campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
        lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
        source VARCHAR(80) NOT NULL,
        source_identity VARCHAR(500) NOT NULL,
        source_query VARCHAR(300) NOT NULL,
        source_url TEXT,
        discovered_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT uq_lead_source_query_hit UNIQUE(campaign_id, source, source_identity, source_query)
    )""")
    op.execute("CREATE INDEX ix_lead_source_queries_campaign_id ON lead_source_queries(campaign_id)")
    op.execute("CREATE INDEX ix_lead_source_queries_lead_id ON lead_source_queries(lead_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS lead_source_queries")
