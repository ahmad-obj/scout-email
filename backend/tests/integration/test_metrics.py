import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from scout_email.app import app
from scout_email.db.base import Base
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
from scout_email.db.session import create_engine_and_sessionmaker, get_session


@pytest.fixture
def metrics_client(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'metrics.db'}"
    )

    async def prepare() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(prepare())

    async def override_session() -> AsyncIterator:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        yield client, factory
    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())


async def _seed_funnel(factory) -> int:
    async with factory() as session:
        campaign = Campaign(
            name="Metrics Campaign",
            status="ACTIVE",
            target_leads=20,
            max_per_day=10,
            human_approval_required=True,
        )
        session.add(campaign)
        await session.flush()

        states = [
            "DISCOVERED",
            "QUALIFIED",
            "RESEARCHED",
            "CONTACTABLE",
            "CONTACTABLE",
            "SKIPPED",
        ]
        leads = []
        for index, state in enumerate(states, start=1):
            lead = Lead(
                campaign_id=campaign.id,
                state=state,
                name=f"Lead {index}",
                normalized_name=f"lead {index}",
            )
            session.add(lead)
            leads.append(lead)
        await session.flush()

        for lead in leads[2:]:
            session.add(
                ResearchReport(
                    lead_id=lead.id,
                    status="COMPLETE",
                    dossier_json="{}",
                    confidence=0.9,
                )
            )

        for index, lead in enumerate(leads[3:5], start=1):
            session.add(
                Contact(
                    lead_id=lead.id,
                    email=f"hello{index}@example.com",
                    normalized_email=f"hello{index}@example.com",
                    contact_type="business",
                    state="VERIFIED",
                    source_url="https://example.com/contact",
                    confidence=1.0,
                )
            )

        drafts = []
        for index, lead in enumerate(leads[3:5], start=1):
            draft = EmailDraft(
                lead_id=lead.id,
                subject=f"Subject {index}",
                body=f"Body {index}",
                approval_state="APPROVED",
                approved_content_hash=f"hash-{index}",
                approved_at=datetime(2026, 8, 31, tzinfo=UTC),
            )
            session.add(draft)
            drafts.append(draft)
        await session.flush()

        for draft in drafts:
            session.add(
                EmailReview(
                    draft_id=draft.id,
                    decision="APPROVE",
                    scores_json="{}",
                    issues_json="[]",
                )
            )

        messages = []
        for index, (lead, draft) in enumerate(zip(leads[3:5], drafts, strict=True), start=1):
            message = OutboundMessage(
                campaign_id=campaign.id,
                lead_id=lead.id,
                draft_id=draft.id,
                recipient_email=f"hello{index}@example.com",
                subject=draft.subject,
                body=draft.body,
                state="SENT",
                idempotency_key=f"metrics-message-{index}",
                gmail_message_id=f"gmail-message-{index}",
                gmail_thread_id=f"gmail-thread-{index}",
                sent_at=datetime(2026, 8, 31, tzinfo=UTC),
            )
            session.add(message)
            messages.append(message)
        await session.flush()

        session.add(
            Bounce(
                outbound_message_id=messages[0].id,
                email=messages[0].recipient_email,
                bounce_type="HARD",
                diagnostic="550 mailbox unavailable",
            )
        )
        thread = EmailThread(
            lead_id=leads[4].id,
            campaign_id=campaign.id,
            gmail_thread_id="gmail-thread-2",
        )
        session.add(thread)
        await session.flush()
        session.add(
            Reply(
                thread_id=thread.id,
                gmail_message_id="reply-positive-1",
                classification="POSITIVE",
                summary="Interested",
                raw_text="Yes, send details.",
                received_at=datetime(2026, 8, 31, tzinfo=UTC),
            )
        )
        await session.commit()
        return campaign.id


def test_campaign_metrics_return_funnel_counts_and_ratios(metrics_client):
    client, factory = metrics_client
    campaign_id = asyncio.run(_seed_funnel(factory))

    response = client.get(f"/campaigns/{campaign_id}/metrics")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["campaign_id"] == campaign_id
    assert body["counts"] == {
        "discovered": 6,
        "qualified": 5,
        "researched": 4,
        "contactable": 2,
        "drafted": 2,
        "critic_approved": 2,
        "human_approved": 2,
        "sent": 2,
        "bounced": 1,
        "replied": 1,
        "positive": 1,
        "skipped": 1,
    }
    assert body["ratios"] == pytest.approx(
        {
            "qualification_rate": 5 / 6,
            "contact_discovery_rate": 2 / 4,
            "human_approval_rate": 1.0,
            "bounce_rate": 1 / 2,
            "reply_rate": 1 / 2,
            "positive_reply_rate": 1.0,
        }
    )


def test_campaign_metrics_zero_denominators_are_zero(metrics_client):
    client, factory = metrics_client

    async def seed_empty() -> int:
        async with factory() as session:
            campaign = Campaign(
                name="Empty Campaign",
                status="ACTIVE",
                target_leads=10,
                max_per_day=10,
                human_approval_required=True,
            )
            session.add(campaign)
            await session.commit()
            return campaign.id

    campaign_id = asyncio.run(seed_empty())
    response = client.get(f"/campaigns/{campaign_id}/metrics")
    assert response.status_code == 200, response.text
    assert set(response.json()["ratios"].values()) == {0.0}


def test_operational_events_are_structured_and_redact_secrets(caplog):
    from scout_email.logging import log_operational_event

    caplog.set_level(logging.INFO, logger="scout_email.events")
    log_operational_event(
        "job.completed",
        correlation_id="corr-123",
        campaign_id=7,
        lead_id=11,
        job_id=13,
        outcome="COMPLETE",
        duration_ms=42.5,
        details={
            "safe_field": "visible",
            "Authorization": "Bearer top-secret-token",
            "api_key": "super-secret-key",
            "oauth_token": "oauth-secret",
        },
    )

    event = json.loads(caplog.records[-1].message)
    assert event["event_type"] == "job.completed"
    assert event["correlation_id"] == "corr-123"
    assert event["campaign_id"] == 7
    assert event["lead_id"] == 11
    assert event["job_id"] == 13
    assert event["outcome"] == "COMPLETE"
    assert event["duration_ms"] == 42.5
    assert event["details"]["safe_field"] == "visible"
    serialized = json.dumps(event).lower()
    assert "top-secret-token" not in serialized
    assert "super-secret-key" not in serialized
    assert "oauth-secret" not in serialized
    assert "[redacted]" in serialized
