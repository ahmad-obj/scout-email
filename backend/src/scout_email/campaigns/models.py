from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from scout_email.db.base import Base


class CampaignPolicy(Base):
    """One-to-one persisted policy configuration for a campaign."""

    __tablename__ = "campaign_policies"

    campaign_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        primary_key=True,
    )
    qualification_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    follow_up_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
