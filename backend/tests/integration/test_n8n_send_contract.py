from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from scout_email.approval.models import EmailEditMetadata, HumanApprovalEvent  # noqa: F401
from scout_email.approval.service import content_hash
from scout_email.app import app
from scout_email.common.enums import ApprovalState, LeadState, MessageState
from scout_email.db.base import Base
from scout_email.db.models import Campaign, Contact, EmailDraft, EmailThread, Lead, OutboundMessage, Sender
from scout_email.db.session import create_engine_and_sessionmaker, get_session
from scout_email.jobs.models import JobRuntime  # noqa: F401
from scout_email.messaging.schemas import ProviderCompletionRequest
from scout_email.messaging.service import MessagingConfigurationError, MessagingService
from scout_email.writing.models import DraftGenerationMetadata  # noqa: F401


class FakeN8NClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def post(self, url: str, *, json: dict, headers: dict, timeout: float):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return httpx.Response(202, json={"accepted": True})


async def _database(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'n8n-send.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, factory


async def _seed(session):
    campaign = Campaign(name="Lahore Dentists", status="ACTIVE", max_per_day=10, human_approval_required=True)
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
    draft = EmailDraft(
        lead_id=lead.id,
        subject=subject,
        body=body,
        writer_prompt_version="writer:v1",
        model_id="fake-writer",
        approval_state=ApprovalState.APPROVED.value,
        approved_content_hash=content_hash(subject, body),
        approved_at=datetime.now(UTC),
    )
    session.add(draft)
    await session.commit()
    return campaign, lead, contact, sender, draft


@pytest.mark.asyncio
async def test_gmail_mode_handoff_uses_only_immutable_backend_copy(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        _campaign, _lead, contact, sender, draft = await _seed(session)
        client = FakeN8NClient()
        service = MessagingService(
            session,
            send_mode="gmail",
            n8n_webhook_url="https://n8n.example/webhook/send-approved",
            n8n_secret="shared-secret",
            http_client=client,
        )

        result = await service.queue_and_dispatch(
            draft_id=draft.id,
            recipient_id=contact.id,
            sender_id=sender.id,
        )

        assert result.state == MessageState.SENDING.value
        assert len(client.calls) == 1
        call = client.calls[0]
        assert call["url"] == "https://n8n.example/webhook/send-approved"
        assert call["headers"]["X-Scout-Email-Secret"] == "shared-secret"
        assert call["json"] == {
            "message_id": result.id,
            "recipient": contact.normalized_email,
            "sender": sender.email,
            "subject": draft.subject,
            "body": draft.body,
        }
        row = await session.get(OutboundMessage, result.id)
        assert row is not None
        assert row.subject == draft.subject
        assert row.body == draft.body
        assert row.state == MessageState.SENDING.value

    await engine.dispose()


@pytest.mark.asyncio
async def test_gmail_mode_fails_closed_before_message_creation_when_transport_config_missing(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        _campaign, _lead, contact, sender, draft = await _seed(session)
        with pytest.raises(MessagingConfigurationError):
            await MessagingService(session, send_mode="gmail").queue_and_dispatch(
                draft_id=draft.id,
                recipient_id=contact.id,
                sender_id=sender.id,
            )
        assert await session.scalar(select(func.count()).select_from(OutboundMessage)) == 0
    await engine.dispose()


def test_provider_completion_schema_cannot_override_approved_copy():
    with pytest.raises(ValidationError):
        ProviderCompletionRequest.model_validate(
            {
                "status": "SENT",
                "provider_message_id": "gmail-message-1",
                "provider_thread_id": "gmail-thread-1",
                "subject": "attacker replacement",
                "body": "attacker replacement",
            }
        )


@pytest.mark.asyncio
async def test_provider_completion_endpoint_accepts_ids_only_and_creates_thread(tmp_path, monkeypatch):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        campaign, lead, contact, sender, draft = await _seed(session)
        client = FakeN8NClient()
        queued = await MessagingService(
            session,
            send_mode="gmail",
            n8n_webhook_url="https://n8n.example/webhook/send-approved",
            n8n_secret="shared-secret",
            http_client=client,
        ).queue_and_dispatch(draft_id=draft.id, recipient_id=contact.id, sender_id=sender.id)

    async def override_session():
        async with factory() as session:
            yield session

    monkeypatch.setenv("SCOUT_EMAIL_N8N_WEBHOOK_SECRET", "shared-secret")
    app.dependency_overrides[get_session] = override_session
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as api:
            response = await api.post(
                f"/messages/{queued.id}/provider-result",
                headers={"X-Scout-Email-Secret": "shared-secret"},
                json={
                    "status": "SENT",
                    "provider_message_id": "gmail-message-1",
                    "provider_thread_id": "gmail-thread-1",
                },
            )
            assert response.status_code == 200
            assert response.json()["state"] == "SENT"

            override_attempt = await api.post(
                f"/messages/{queued.id}/provider-result",
                headers={"X-Scout-Email-Secret": "shared-secret"},
                json={
                    "status": "SENT",
                    "provider_message_id": "gmail-message-1",
                    "provider_thread_id": "gmail-thread-1",
                    "subject": "replacement",
                },
            )
            assert override_attempt.status_code == 422

        async with factory() as verify:
            row = await verify.get(OutboundMessage, queued.id)
            assert row is not None
            assert row.state == MessageState.SENT.value
            assert row.gmail_message_id == "gmail-message-1"
            assert row.gmail_thread_id == "gmail-thread-1"
            thread = await verify.scalar(
                select(EmailThread).where(
                    EmailThread.lead_id == lead.id,
                    EmailThread.campaign_id == campaign.id,
                    EmailThread.gmail_thread_id == "gmail-thread-1",
                )
            )
            assert thread is not None
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
