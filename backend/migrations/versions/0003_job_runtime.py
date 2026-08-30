"""Add job runtime lease metadata.

Revision ID: 0003_job_runtime
Revises: 0002_campaign_policies
Create Date: 2026-08-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_job_runtime"
down_revision: str | None = "0002_campaign_policies"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """CREATE TABLE job_runtime (
            job_id INTEGER PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
            locked_by VARCHAR(200),
            lease_expires_at DATETIME,
            last_error_code VARCHAR(120),
            last_error_message TEXT
        )"""
    )
    op.execute(
        "CREATE INDEX ix_job_runtime_lease_expires_at "
        "ON job_runtime(lease_expires_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS job_runtime")
