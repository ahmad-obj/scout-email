from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from scout_email.approval.service import content_hash
from scout_email.common.enums import ApprovalState, MessageState
from scout_email.common.errors import NotFoundError, ScoutEmailError
from scout_email.db.models import (
    Campaign,
    Contact,
    DoNotContact,
    EmailDraft,
    EmailThread,
    Lead,
    OutboundMessage,
    Reply,
    Sender,
)
from scout_email.messaging.eligibility import (
    EligibilityResult,
    EligibilitySnapshot,
    evaluate_send_eligibility,
)
from scout_email.messaging.schemas import MessageView


class MessagingError(ScoutEmailError):
    pass


class MessagingEligibilityError(MessagingError):
    def __init__(self, reasons: list[str]) -> None:
        self.reasons = list(reasons)
        super().__init__(", ".join(self.reasons))


def _message_view(row: OutboundMessage) -> MessageView:
    return MessageView(
        id=row.id,
        state=row.state,
        recipient_email=row.recipient_email,
        subject=row.subject,
        body=row.body,
        provider_message_id=row.gmail_message_id,
        provider_thread_id=row.gmail_thread_id,
    )


def _idempotency_key(
    *,
    campaign_id: int,
    lead_id: int,
    recipient_email: str,
    approved_hash: str,
    sequence_stage: str = "initial",
) -> str:
    raw = (
        f"{campaign_id}|{lead_id}|{recipient_email.casefold()}|"
        f"{approved_hash}|{sequence_stage}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class MessagingService:
    """Queue and dispatch immutable approved copy; Task 19 supports mock only."""

    def __init__(self, session: AsyncSession, *, send_mode: str | None = None) -> None:
        self.session = session
        self.send_mode = (
            send_mode or os.getenv("SCOUT_EMAIL_SEND_MODE", "mock")
        ).strip().casefold()

    async def evaluate_send_eligibility(
        self,
        *,
        draft_id: int,
        recipient_id: int,
        sender_id: int,
        ignore_idempotency_key: str | None = None,
    ) -> EligibilityResult:
        draft = await self.session.get(EmailDraft, draft_id)
        if draft is None:
            raise NotFoundError(f"Draft {draft_id} not found")
        lead = await self.session.get(Lead, draft.lead_id)
        if lead is None:
            raise NotFoundError(f"Lead {draft.lead_id} not found")
        campaign = await self.session.get(Campaign, lead.campaign_id)
        if campaign is None:
            raise NotFoundError(f"Campaign {lead.campaign_id} not found")
        contact = await self.session.get(Contact, recipient_id)
        if contact is None or contact.lead_id != lead.id:
            raise NotFoundError("recipient contact not found for lead")
        sender = await self.session.get(Sender, sender_id)
        if sender is None:
            raise NotFoundError(f"Sender {sender_id} not found")

        normalized_email = contact.normalized_email.casefold()
        email_domain = normalized_email.rsplit("@", 1)[-1] if "@" in normalized_email else ""
        canonical_domain = (lead.canonical_domain or "").strip().casefold()
        domains = {item for item in (email_domain, canonical_domain) if item}
        dnc_conditions = [func.lower(DoNotContact.email) == normalized_email]
        dnc_conditions.extend(func.lower(DoNotContact.domain) == domain for domain in domains)
        if lead.normalized_name:
            dnc_conditions.append(
                func.lower(DoNotContact.business_name) == lead.normalized_name.casefold()
            )
        dnc_match = bool(
            await self.session.scalar(
                select(func.count()).select_from(DoNotContact).where(or_(*dnc_conditions))
            )
        )

        duplicate_query = select(func.count()).select_from(OutboundMessage).where(
            OutboundMessage.campaign_id == campaign.id,
            OutboundMessage.lead_id == lead.id,
            func.lower(OutboundMessage.recipient_email) == normalized_email,
            OutboundMessage.state.in_(
                [
                    MessageState.QUEUED.value,
                    MessageState.SENDING.value,
                    MessageState.SENT.value,
                ]
            ),
        )
        if ignore_idempotency_key:
            duplicate_query = duplicate_query.where(
                OutboundMessage.idempotency_key != ignore_idempotency_key
            )
        duplicate_outreach = bool(await self.session.scalar(duplicate_query))

        human_reply_exists = bool(
            await self.session.scalar(
                select(func.count())
                .select_from(Reply)
                .join(EmailThread, EmailThread.id == Reply.thread_id)
                .where(
                    EmailThread.lead_id == lead.id,
                    EmailThread.campaign_id == campaign.id,
                )
            )
        )

        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        daily_sent_count = int(
            await self.session.scalar(
                select(func.count()).select_from(OutboundMessage).where(
                    OutboundMessage.campaign_id == campaign.id,
                    OutboundMessage.state == MessageState.SENT.value,
                    OutboundMessage.sent_at >= today_start,
                )
            )
            or 0
        )

        approved_hash_matches = bool(
            draft.approved_content_hash
            and draft.approved_content_hash == content_hash(draft.subject, draft.body)
            and draft.approved_at is not None
        )
        snapshot = EligibilitySnapshot(
            approval_state=draft.approval_state,
            approval_hash_matches=approved_hash_matches,
            contact_verified=contact.state == "VERIFIED",
            dnc_match=dnc_match,
            duplicate_outreach=duplicate_outreach,
            human_reply_exists=human_reply_exists,
            campaign_active=campaign.status == "ACTIVE",
            daily_sent_count=daily_sent_count,
            max_per_day=campaign.max_per_day,
            sender_enabled=sender.enabled,
            sender_healthy=sender.health_state == "HEALTHY",
        )
        return evaluate_send_eligibility(snapshot)

    async def queue_and_dispatch(
        self,
        *,
        draft_id: int,
        recipient_id: int,
        sender_id: int,
    ) -> MessageView:
        draft = await self.session.get(EmailDraft, draft_id)
        if draft is None:
            raise NotFoundError(f"Draft {draft_id} not found")
        lead = await self.session.get(Lead, draft.lead_id)
        if lead is None:
            raise NotFoundError(f"Lead {draft.lead_id} not found")
        contact = await self.session.get(Contact, recipient_id)
        if contact is None or contact.lead_id != lead.id:
            raise NotFoundError("recipient contact not found for lead")
        if not draft.approved_content_hash:
            eligibility = await self.evaluate_send_eligibility(
                draft_id=draft_id, recipient_id=recipient_id, sender_id=sender_id
            )
            raise MessagingEligibilityError(eligibility.reasons)

        key = _idempotency_key(
            campaign_id=lead.campaign_id,
            lead_id=lead.id,
            recipient_email=contact.normalized_email,
            approved_hash=draft.approved_content_hash,
        )
        existing = await self.session.scalar(
            select(OutboundMessage).where(OutboundMessage.idempotency_key == key)
        )
        if existing is not None:
            return _message_view(existing)

        eligibility = await self.evaluate_send_eligibility(
            draft_id=draft_id,
            recipient_id=recipient_id,
            sender_id=sender_id,
            ignore_idempotency_key=key,
        )
        if not eligibility.allowed:
            raise MessagingEligibilityError(eligibility.reasons)
        if self.send_mode != "mock":
            raise MessagingError(
                "Task 19 dispatch is mock-only; Gmail handoff is not enabled"
            )

        now = datetime.now(UTC)
        message = OutboundMessage(
            campaign_id=lead.campaign_id,
            lead_id=lead.id,
            draft_id=draft.id,
            sender_id=sender_id,
            recipient_email=contact.normalized_email,
            subject=draft.subject,
            body=draft.body,
            state=MessageState.QUEUED.value,
            idempotency_key=key,
            queued_at=now,
        )
        self.session.add(message)
        await self.session.flush()

        # Mock mode represents the provider handoff without making any external call.
        mock_message_id = f"mock-message-{message.id}"
        mock_thread_id = f"mock-thread-{message.id}"
        message.state = MessageState.SENT.value
        message.gmail_message_id = mock_message_id
        message.gmail_thread_id = mock_thread_id
        message.sent_at = now
        self.session.add(
            EmailThread(
                lead_id=lead.id,
                campaign_id=lead.campaign_id,
                gmail_thread_id=mock_thread_id,
                followup_stage=0,
                followup_cancelled=False,
            )
        )
        await self.session.commit()
        return _message_view(message)
