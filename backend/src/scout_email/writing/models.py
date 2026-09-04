from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from scout_email.db.base import Base


class DraftGenerationMetadata(Base):
    __tablename__ = "draft_generation_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int] = mapped_column(
        ForeignKey("email_drafts.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    playbook_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_label: Mapped[str] = mapped_column(String(200), nullable=False)
    recent_similarity: Mapped[float] = mapped_column(Float, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False
    )


class EmailReviewAudit(Base):
    __tablename__ = "email_review_audits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    review_id: Mapped[int] = mapped_column(
        ForeignKey("email_reviews.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    draft_id: Mapped[int] = mapped_column(
        ForeignKey("email_drafts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    audit_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False
    )
