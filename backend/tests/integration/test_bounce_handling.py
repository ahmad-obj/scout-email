from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from scout_email.approval.service import content_hash
from scout_email.common.enums import ApprovalState, ContactState, LeadState, MessageState
from scout_email.db.base import Base
from scout_email.db.models import (
    Bounce,
    Campaign,
    Contact,
    DoNotContact,
    EmailDraft,
    EmailThread,
    Lead,
    OutboundMessage,
    Sender,
)
from scout_email.db.session import create_engine_and_sessionmaker
from scout_email.messaging.service import MessagingService
from scout_email.replies.schemas import ReplySyncRequest
from scout_email.replies.service import ReplyService


async def _database(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'bounce-handling.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, factory


async def _seed(session):
    campaign = Campaign(
        name="Lahore Dentists",
        status="ACTIVE",
        max_per_day=10,
        human_approval_required=True,
    )
    session.add(campaign)
    await session.flush()
    lead = Lead(
        campaign_id=campaign.id,
        state=LeadState.CONTACTABLE.value,
        name="Acme Dental",
        normalized_name="acme dental",
        category="Dentist",
        city="Lahore",
        canonical_domain="example.com",
    )
    session.add(lead)
    await session.flush()
    contact = Contact(
        lead_id=lead.id,
        email="hello@example.com",
        normalized_email="hello@example.com",
        contact_type="business",
        state=ContactState.VERIFIED.value,
        source_url="https://example.com/contact",
        confidence=1.0,
    )
    sender = Sender(
        label="WEBERAISE Outreach",
        email="outreach@weberaise.example",
        enabled=True,
        health_state="HEALTHY",
    )
    session.add_all([contact, sender])
    await session.flush()
    subject = "Website idea"
    body = "I noticed one concrete booking-flow issue. Would it help if I sent the fix?"
    digest = content_hash(subject, body)
    draft = EmailDraft(
        lead_id=lead.id,
        subject=subject,
        body=body,
        approval_state=ApprovalState.APPROVED.value,
        approved_content_hash=digest,
        approved_at=datetime.now(UTC),
    )
    session.add(draft)
    await session.flush()
    message = OutboundMessage(
        campaign_id=campaign.id,
        lead_id=lead.id,
        draft_id=draft.id,
        sender_id=sender.id,
        recipient_email=contact.normalized_email,
        subject=subject,
        body=body,
        state=MessageState.SENT.value,
        idempotency_key="seed-outbound-message",
        gmail_message_id="gmail-outbound-1",
        gmail_thread_id="gmail-thread-1",
        queued_at=datetime.now(UTC),
        sent_at=datetime.now(UTC),
    )
    thread = EmailThread(
        lead_id=lead.id,
        campaign_id=campaign.id,
        gmail_thread_id="gmail-thread-1",
        followup_stage=0,
        followup_cancelled=False,
    )
    session.add_all([message, thread])
    await session.commit()
    return campaign, lead, contact, sender, draft, message, thread


@pytest.mark.asyncio
async def test_canonical_domain_dnc_blocks_even_if_campaign_is_active(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        _campaign, _lead, contact, sender, draft, _message, _thread = await _seed(session)
        session.add(
            DoNotContact(
                domain=" WWW.EXAMPLE.COM. ",
                reason="manual suppression",
                source="manual",
            )
        )
        await session.commit()

        result = await MessagingService(session, send_mode="mock").evaluate_send_eligibility(
            draft_id=draft.id,
            recipient_id=contact.id,
            sender_id=sender.id,
        )
        assert result.allowed is False
        assert "do_not_contact" in result.reasons

    await engine.dispose()


@pytest.mark.asyncio
async def test_unsubscribe_creates_one_global_dnc_record_across_multiple_messages(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        _campaign, _lead, _contact, _sender, _draft, _message, _thread = await _seed(session)
        service = ReplyService(session)

        for message_id in ("gmail-unsub-1", "gmail-unsub-2"):
            await service.sync(
                ReplySyncRequest(
                    gmail_thread_id="gmail-thread-1",
                    gmail_message_id=message_id,
                    from_email="Hello@Example.COM",
                    subject="Re: website idea",
                    body="Please unsubscribe me and do not contact me again.",
                    headers={},
                    received_at=datetime.now(UTC),
                )
            )

        assert await session.scalar(select(func.count()).select_from(DoNotContact)) == 1
        row = (await session.execute(select(DoNotContact))).scalar_one()
        assert row.email == "hello@example.com"
        assert row.domain == "example.com"
        assert row.business_name == "acme dental"
        assert row.reason == "recipient_unsubscribe"
        assert row.source == "reply"

    await engine.dispose()


@pytest.mark.asyncio
async def test_hard_bounce_invalidates_contact_and_future_send_eligibility(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        _campaign, lead, contact, sender, draft, message, _thread = await _seed(session)

        await ReplyService(session).sync(
            ReplySyncRequest(
                gmail_thread_id="gmail-thread-1",
                gmail_message_id="gmail-bounce-1",
                from_email="mailer-daemon@googlemail.com",
                subject="Delivery Status Notification (Failure)",
                body="The recipient address hello@example.com could not be found.",
                headers={},
                received_at=datetime.now(UTC),
            )
        )

        await session.refresh(contact)
        await session.refresh(lead)
        assert contact.state == ContactState.INVALID.value
        assert lead.state == LeadState.NO_CONTACT.value
        assert await session.scalar(select(func.count()).select_from(Bounce)) == 1
        bounce = (await session.execute(select(Bounce))).scalar_one()
        assert bounce.outbound_message_id == message.id
        assert bounce.email == "hello@example.com"
        assert bounce.bounce_type == "HARD"

        result = await MessagingService(session, send_mode="mock").evaluate_send_eligibility(
            draft_id=draft.id,
            recipient_id=contact.id,
            sender_id=sender.id,
        )
        assert "contact_not_verified" in result.reasons

    await engine.dispose()
