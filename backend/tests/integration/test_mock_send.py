from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import func, select

from scout_email.approval.models import EmailEditMetadata, HumanApprovalEvent  # noqa: F401
from scout_email.approval.service import content_hash
from scout_email.app import app
from scout_email.common.enums import ApprovalState, LeadState, MessageState
from scout_email.db.base import Base
from scout_email.db.models import (
    Campaign,
    Contact,
    EmailDraft,
    EmailThread,
    Lead,
    OutboundMessage,
    Sender,
)
from scout_email.db.session import create_engine_and_sessionmaker, get_session
from scout_email.jobs.models import JobRuntime  # noqa: F401
from scout_email.messaging.service import MessagingEligibilityError, MessagingService
from scout_email.writing.models import DraftGenerationMetadata  # noqa: F401


async def _database(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'mock-send.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, factory


async def _seed_eligible(session):
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
        state="VERIFIED",
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
    subject = "Mobile booking thought"
    body = "Your mobile booking action is easy to miss. Would it be useful if I sent one focused idea?"
    digest = content_hash(subject, body)
    draft = EmailDraft(
        lead_id=lead.id,
        subject=subject,
        body=body,
        writer_prompt_version="writer:v1",
        model_id="fake-writer",
        approval_state=ApprovalState.APPROVED.value,
        approved_content_hash=digest,
        approved_at=datetime.now(UTC),
    )
    session.add(draft)
    await session.commit()
    return campaign, lead, contact, sender, draft


@pytest.mark.asyncio
async def test_mock_dispatch_is_idempotent_and_creates_one_thread(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        _campaign, _lead, contact, sender, draft = await _seed_eligible(session)
        service = MessagingService(session, send_mode="mock")

        first = await service.queue_and_dispatch(
            draft_id=draft.id,
            recipient_id=contact.id,
            sender_id=sender.id,
        )
        second = await service.queue_and_dispatch(
            draft_id=draft.id,
            recipient_id=contact.id,
            sender_id=sender.id,
        )

        assert first.id == second.id
        assert first.state == MessageState.SENT.value
        assert first.provider_message_id.startswith("mock-message-")
        assert first.provider_thread_id.startswith("mock-thread-")
        assert await session.scalar(select(func.count()).select_from(OutboundMessage)) == 1
        assert await session.scalar(select(func.count()).select_from(EmailThread)) == 1
        row = await session.get(OutboundMessage, first.id)
        assert row is not None
        assert row.subject == draft.subject
        assert row.body == draft.body
        assert row.recipient_email == contact.normalized_email

    await engine.dispose()


@pytest.mark.asyncio
async def test_dispatch_rechecks_current_approval_hash_before_creating_message(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        _campaign, _lead, contact, sender, draft = await _seed_eligible(session)
        draft.body += " Changed after approval."
        await session.commit()

        with pytest.raises(MessagingEligibilityError) as error:
            await MessagingService(session, send_mode="mock").queue_and_dispatch(
                draft_id=draft.id,
                recipient_id=contact.id,
                sender_id=sender.id,
            )
        assert "approval_hash_mismatch" in error.value.reasons
        assert await session.scalar(select(func.count()).select_from(OutboundMessage)) == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_message_queue_route_uses_same_fail_closed_mock_service(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as seed_session:
        _campaign, _lead, contact, sender, draft = await _seed_eligible(seed_session)

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/messages/{draft.id}/queue",
                json={"recipient_id": contact.id, "sender_id": sender.id},
            )
            assert response.status_code == 202
            assert response.json()["state"] == "SENT"

            repeated = await client.post(
                f"/messages/{draft.id}/queue",
                json={"recipient_id": contact.id, "sender_id": sender.id},
            )
            assert repeated.status_code == 202
            assert repeated.json()["id"] == response.json()["id"]
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
