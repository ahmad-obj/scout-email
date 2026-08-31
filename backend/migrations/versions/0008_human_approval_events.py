"""Persist immutable human approval actions and edit metadata.

Revision ID: 0008_human_approval_events
Revises: 0007_draft_generation_metadata
Create Date: 2026-08-31
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_human_approval_events"
down_revision: str | None = "0007_draft_generation_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "human_approval_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "draft_id",
            sa.Integer(),
            sa.ForeignKey("email_drafts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("reviewer", sa.String(length=200), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("subject_snapshot", sa.Text(), nullable=False),
        sa.Column("body_snapshot", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
    )
    op.create_index(
        "ix_human_approval_events_draft_id",
        "human_approval_events",
        ["draft_id"],
    )
    op.create_index(
        "ix_human_approval_events_action",
        "human_approval_events",
        ["action"],
    )

    op.create_table(
        "email_edit_metadata",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "edit_id",
            sa.Integer(),
            sa.ForeignKey("email_edits.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("lead_industry", sa.String(length=200)),
        sa.Column("playbook_hash", sa.String(length=64)),
        sa.Column("writer_prompt_version", sa.String(length=80)),
        sa.UniqueConstraint("edit_id", name="uq_email_edit_metadata_edit"),
    )
    op.create_index(
        "ix_email_edit_metadata_edit_id",
        "email_edit_metadata",
        ["edit_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_email_edit_metadata_edit_id", table_name="email_edit_metadata")
    op.drop_table("email_edit_metadata")
    op.drop_index("ix_human_approval_events_action", table_name="human_approval_events")
    op.drop_index("ix_human_approval_events_draft_id", table_name="human_approval_events")
    op.drop_table("human_approval_events")
