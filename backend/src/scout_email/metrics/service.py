from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from scout_email.common.enums import LeadState
from scout_email.common.errors import NotFoundError
from scout_email.db.models import (
    Bounce,
    Campaign,
    Contact,
    EmailDraft,
    EmailReview,
    EmailThread,
    Lead,
    OutboundMessage,
    Reply,
    ResearchReport,
)

_QUALIFIED_OR_LATER = {
    LeadState.QUALIFIED.value,
    LeadState.RESEARCH_PENDING.value,
    LeadState.RESEARCHING.value,
    LeadState.RESEARCHED.value,
    LeadState.CONTACTABLE.value,
    LeadState.NO_CONTACT.value,
    LeadState.SKIPPED.value,
}


def _ratio(numerator: int, denominator: int) -> float:
    return float(numerator / denominator) if denominator else 0.0


class CampaignMetricsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _count(self, statement) -> int:
        return int((await self.session.scalar(statement)) or 0)

    async def get_metrics(self, campaign_id: int) -> dict[str, object]:
        if await self.session.get(Campaign, campaign_id) is None:
            raise NotFoundError(f"Campaign {campaign_id} not found")

        discovered = await self._count(
            select(func.count(Lead.id)).where(Lead.campaign_id == campaign_id)
        )
        qualified = await self._count(
            select(func.count(Lead.id)).where(
                Lead.campaign_id == campaign_id,
                Lead.state.in_(_QUALIFIED_OR_LATER),
            )
        )
        researched = await self._count(
            select(func.count(func.distinct(ResearchReport.lead_id)))
            .join(Lead, Lead.id == ResearchReport.lead_id)
            .where(
                Lead.campaign_id == campaign_id,
                ResearchReport.status == "COMPLETE",
            )
        )
        contactable = await self._count(
            select(func.count(func.distinct(Contact.lead_id)))
            .join(Lead, Lead.id == Contact.lead_id)
            .where(
                Lead.campaign_id == campaign_id,
                Contact.state == "VERIFIED",
            )
        )
        drafted = await self._count(
            select(func.count(func.distinct(EmailDraft.lead_id)))
            .join(Lead, Lead.id == EmailDraft.lead_id)
            .where(Lead.campaign_id == campaign_id)
        )
        critic_approved = await self._count(
            select(func.count(func.distinct(EmailDraft.lead_id)))
            .join(EmailReview, EmailReview.draft_id == EmailDraft.id)
            .join(Lead, Lead.id == EmailDraft.lead_id)
            .where(
                Lead.campaign_id == campaign_id,
                EmailReview.decision == "APPROVE",
            )
        )
        human_approved = await self._count(
            select(func.count(func.distinct(EmailDraft.lead_id)))
            .join(Lead, Lead.id == EmailDraft.lead_id)
            .where(
                Lead.campaign_id == campaign_id,
                EmailDraft.approval_state == "APPROVED",
            )
        )
        sent = await self._count(
            select(func.count(func.distinct(OutboundMessage.lead_id))).where(
                OutboundMessage.campaign_id == campaign_id,
                OutboundMessage.state == "SENT",
            )
        )
        bounced = await self._count(
            select(func.count(func.distinct(OutboundMessage.lead_id)))
            .join(Bounce, Bounce.outbound_message_id == OutboundMessage.id)
            .where(OutboundMessage.campaign_id == campaign_id)
        )
        replied = await self._count(
            select(func.count(func.distinct(EmailThread.lead_id)))
            .join(Reply, Reply.thread_id == EmailThread.id)
            .where(EmailThread.campaign_id == campaign_id)
        )
        positive = await self._count(
            select(func.count(func.distinct(EmailThread.lead_id)))
            .join(Reply, Reply.thread_id == EmailThread.id)
            .where(
                EmailThread.campaign_id == campaign_id,
                Reply.classification == "POSITIVE",
            )
        )
        skipped = await self._count(
            select(func.count(Lead.id)).where(
                Lead.campaign_id == campaign_id,
                Lead.state == LeadState.SKIPPED.value,
            )
        )

        counts = {
            "discovered": discovered,
            "qualified": qualified,
            "researched": researched,
            "contactable": contactable,
            "drafted": drafted,
            "critic_approved": critic_approved,
            "human_approved": human_approved,
            "sent": sent,
            "bounced": bounced,
            "replied": replied,
            "positive": positive,
            "skipped": skipped,
        }
        ratios = {
            "qualification_rate": _ratio(qualified, discovered),
            "contact_discovery_rate": _ratio(contactable, researched),
            "human_approval_rate": _ratio(human_approved, critic_approved),
            "bounce_rate": _ratio(bounced, sent),
            "reply_rate": _ratio(replied, sent),
            "positive_reply_rate": _ratio(positive, replied),
        }
        return {"campaign_id": campaign_id, "counts": counts, "ratios": ratios}
