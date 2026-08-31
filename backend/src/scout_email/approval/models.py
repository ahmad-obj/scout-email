from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from scout_email.db.base import Base


class HumanApprovalEvent(Base):
    __tablename__ = "human_approval_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int] = mapped_column(
        ForeignKey("email_drafts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    reviewer: Mapped[str] = mapped_column(String(200), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    body_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False
    )


class EmailEditMetadata(Base):
    __tablename__ = "email_edit_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    edit_id: Mapped[int] = mapped_column(
        ForeignKey("email_edits.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    lead_industry: Mapped[str | None] = mapped_column(String(200))
    playbook_hash: Mapped[str | None] = mapped_column(String(64))
    writer_prompt_version: Mapped[str | None] = mapped_column(String(80))
