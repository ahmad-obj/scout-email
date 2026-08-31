from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from scout_email.approval.service import content_hash
from scout_email.common.enums import (
    ApprovalState,
    ContactState,
    FollowupState,
    LeadState,
    MessageState,
)
from scout_email.db.base import Base
from scout_email.db.models import (
    Campaign,
    Contact,
    EmailDraft,
    EmailThread,
    Followup,
    Lead,
    OutboundMessage,
    Reply,
    Sender,
)
from scout_email.db.session import create_engine_and_sessionmaker
from scout_email.messaging.service import MessagingEligibilityError, MessagingService


async def _seed_approved_followup(session):
    now = datetime.now(UTC)
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
        canonical_domain="acme.example",
    )
    session.add(lead)
    await session.flush()

    contact = Contact(
        lead_id=lead.id,
        email="hello@acme.example",
        normalized_email="hello@acme.example",
        contact_type="business",
        state=ContactState.VERIFIED.value,
        source_url="https://acme.example/contact",
        confidence=1.0,
    )
    sender = Sender(
        label="WEBERAISE",
        email="hello@weberaise.example",
        enabled=True,
        health_state="HEALTHY",
    )
    session.add_all([contact, sender])
    await session.flush()

    initial_draft = EmailDraft(
        lead_id=lead.id,
        subject="Quick website thought",
        body="Initial note.",
        writer_prompt_version="writer:v1",
        model_id="fake",
        approval_state=ApprovalState.APPROVED.value,
    )
    session.add(initial_draft)
    await session.flush()
    initial = OutboundMessage(
        campaign_id=campaign.id,
        lead_id=lead.id,
        draft_id=initial_draft.id,
        sender_id=sender.id,
        recipient_email=contact.normalized_email,
        subject=initial_draft.subject,
        body=initial_draft.body,
        state=MessageState.SENT.value,
        idempotency_key=f"initial:{lead.id}",
        gmail_message_id="gmail-initial-1",
        gmail_thread_id="gmail-thread-1",
        queued_at=now - timedelta(days=5),
        sent_at=now - timedelta(days=5),
    )
    thread = EmailThread(
        lead_id=lead.id,
        campaign_id=campaign.id,
        gmail_thread_id="gmail-thread-1",
        followup_stage=0,
        followup_cancelled=False,
    )
    session.add_all([initial, thread])
    await session.flush()

    followup_draft = EmailDraft(
        lead_id=lead.id,
        subject="Re: Quick website thought",
        body="One concrete idea: make the booking action visible earlier on mobile.",
        writer_prompt_version="followup_writer:v1",
        model_id="fake-followup-model",
        approval_state=ApprovalState.APPROVED.value,
    )
    session.add(followup_draft)
    await session.flush()
    digest = content_hash(followup_draft.subject, followup_draft.body)
    followup_draft.approved_content_hash = digest
    followup_draft.approved_at = now

    followup = Followup(
        thread_id=thread.id,
        draft_id=followup_draft.id,
        stage=1,
        state=FollowupState.PENDING_APPROVAL.value,
        due_at=now - timedelta(minutes=1),
    )
    session.add(followup)
    await session.commit()
    return campaign, lead, contact, sender, thread, followup_draft, followup


@pytest.mark.asyncio
async def test_approved_followup_dispatch_is_same_thread_and_idempotent(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'followup-dispatch.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as session:
        _, _, contact, sender, thread, draft, followup = await _seed_approved_followup(session)
        service = MessagingService(session, send_mode="mock")

        first = await service.queue_and_dispatch_followup(
            followup_id=followup.id,
            recipient_id=contact.id,
            sender_id=sender.id,
        )
        second = await service.queue_and_dispatch_followup(
            followup_id=followup.id,
            recipient_id=contact.id,
            sender_id=sender.id,
        )

        assert first.id == second.id
        assert first.state == MessageState.SENT.value
        assert first.provider_thread_id == "gmail-thread-1"
        persisted_followup = await session.get(Followup, followup.id)
        persisted_thread = await session.get(EmailThread, thread.id)
        assert persisted_followup is not None
        assert persisted_followup.state == FollowupState.SENT.value
        assert persisted_thread is not None and persisted_thread.followup_stage == 1
        followup_messages = int(
            await session.scalar(
                select(func.count())
                .select_from(OutboundMessage)
                .where(OutboundMessage.draft_id == draft.id)
            )
            or 0
        )
        thread_rows = int(
            await session.scalar(select(func.count()).select_from(EmailThread)) or 0
        )
        assert followup_messages == 1
        assert thread_rows == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_reply_after_approval_blocks_followup_dispatch(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'followup-reply-block.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as session:
        _, _, contact, sender, thread, draft, followup = await _seed_approved_followup(session)
        session.add(
            Reply(
                thread_id=thread.id,
                gmail_message_id="gmail-reply-after-approval",
                classification="POSITIVE",
                summary="Interested",
                raw_text="Sure, tell me more.",
                received_at=datetime.now(UTC),
            )
        )
        await session.commit()

        with pytest.raises(MessagingEligibilityError, match="human_reply_exists"):
            await MessagingService(session, send_mode="mock").queue_and_dispatch_followup(
                followup_id=followup.id,
                recipient_id=contact.id,
                sender_id=sender.id,
            )

        message_count = int(
            await session.scalar(
                select(func.count())
                .select_from(OutboundMessage)
                .where(OutboundMessage.draft_id == draft.id)
            )
            or 0
        )
        assert message_count == 0

    await engine.dispose()
