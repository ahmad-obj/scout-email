from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from scout_email.db.base import Base


class ReplyIntelligenceRecord(Base):
    __tablename__ = "reply_intelligence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reply_id: Mapped[int] = mapped_column(
        ForeignKey("replies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    intent_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    questions_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    recommended_action: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False
    )
    __table_args__ = (UniqueConstraint("reply_id", name="uq_reply_intelligence_reply"),)

    @property
    def questions(self) -> list[str]:
        value = json.loads(self.questions_json or "[]")
        return [str(item) for item in value] if isinstance(value, list) else []
