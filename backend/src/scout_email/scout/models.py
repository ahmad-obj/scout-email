from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from scout_email.db.base import Base


class LeadSourceQuery(Base):
    """One query-level discovery event for a canonical lead source."""

    __tablename__ = "lead_source_queries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    source_identity: Mapped[str] = mapped_column(String(500), nullable=False)
    source_query: Mapped[str] = mapped_column(String(300), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False)
    __table_args__ = (UniqueConstraint("campaign_id", "source", "source_identity", "source_query", name="uq_lead_source_query_hit"),)
