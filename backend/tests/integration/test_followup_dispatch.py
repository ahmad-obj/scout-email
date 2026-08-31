from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

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
from scout_email.messaging.schemas import ProviderCompletionRequest
from scout_email.messaging.service import MessagingEligibilityError, MessagingService


class FakeN8nClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def post(self, url, *, json, headers, timeout):
        self.calls.append(
            {"url": url, "json": json, "headers": headers, "timeout": timeout}
        )
        return SimpleNamespace(status_code=202)


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


@pytest.mark.asyncio
async def test_gmail_followup_handoff_replies_to_original_message_and_callback_advances_stage(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'followup-gmail.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as session:
        _, _, contact, sender, thread, draft, followup = await _seed_approved_followup(session)
        client = FakeN8nClient()
        service = MessagingService(
            session,
            send_mode="gmail",
            n8n_webhook_url="https://n8n.example/webhook/send-approved",
            n8n_secret="test-secret",
            http_client=client,
        )

        queued = await service.queue_and_dispatch_followup(
            followup_id=followup.id,
            recipient_id=contact.id,
            sender_id=sender.id,
        )
        assert queued.state == MessageState.SENDING.value
        assert len(client.calls) == 1
        payload = client.calls[0]["json"]
        assert payload["mode"] == "followup"
        assert payload["provider_thread_id"] == "gmail-thread-1"
        assert payload["reply_to_message_id"] == "gmail-initial-1"
        assert payload["body"] == draft.body

        persisted_followup = await session.get(Followup, followup.id)
        persisted_thread = await session.get(EmailThread, thread.id)
        assert persisted_followup is not None
        assert persisted_followup.state == FollowupState.QUEUED.value
        assert persisted_thread is not None and persisted_thread.followup_stage == 0

        completed = await service.complete_provider_result(
            message_id=queued.id,
            completion=ProviderCompletionRequest(
                status="SENT",
                provider_message_id="gmail-followup-1",
                provider_thread_id="gmail-thread-1",
            ),
        )
        assert completed.state == MessageState.SENT.value
        assert completed.provider_thread_id == "gmail-thread-1"
        await session.refresh(persisted_followup)
        await session.refresh(persisted_thread)
        assert persisted_followup.state == FollowupState.SENT.value
        assert persisted_thread.followup_stage == 1

    await engine.dispose()
