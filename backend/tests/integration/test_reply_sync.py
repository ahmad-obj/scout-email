from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import func, select

from scout_email.app import app
from scout_email.common.enums import FollowupState, JobState, ReplyClass
from scout_email.db.base import Base
from scout_email.db.models import Campaign, EmailThread, Followup, Job, Lead, Reply
from scout_email.db.session import create_engine_and_sessionmaker, get_session
from scout_email.replies.classifier import ReplyClassifier
from scout_email.replies.routes import get_reply_classifier
from scout_email.replies.schemas import ReplyIntelligence, ReplySyncRequest
from scout_email.replies.service import ReplyService


class FakeClassifier(ReplyClassifier):
    def __init__(self) -> None:
        self.calls = 0

    async def classify(self, request: ReplySyncRequest) -> ReplyIntelligence:
        self.calls += 1
        return ReplyIntelligence(
            classification=ReplyClass.QUESTION,
            summary="The prospect asked for pricing information.",
            intent_score=0.78,
            questions=["What does a redesign cost?"],
            recommended_action="respond_today",
        )


class ExplodingClassifier(ReplyClassifier):
    async def classify(self, request: ReplySyncRequest) -> ReplyIntelligence:
        raise AssertionError("deterministic reply should not invoke classifier")


async def _database(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'reply-sync.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, factory


async def _seed_thread(session):
    campaign = Campaign(name="Lahore Dentists", status="ACTIVE")
    session.add(campaign)
    await session.flush()
    lead = Lead(
        campaign_id=campaign.id,
        name="Acme Dental",
        normalized_name="acme dental",
        city="Lahore",
    )
    session.add(lead)
    await session.flush()
    thread = EmailThread(
        lead_id=lead.id,
        campaign_id=campaign.id,
        gmail_thread_id="gmail-thread-1",
        followup_stage=0,
        followup_cancelled=False,
    )
    session.add(thread)
    await session.flush()
    followup = Followup(
        thread_id=thread.id,
        stage=1,
        state=FollowupState.QUEUED.value,
        due_at=datetime.now(UTC),
    )
    job = Job(
        job_type="followup",
        state=JobState.PENDING.value,
        entity_type="email_thread",
        entity_id=thread.id,
        payload_json=json.dumps({"thread_id": thread.id}),
        idempotency_key=f"followup:{thread.id}:1",
    )
    session.add_all([followup, job])
    await session.commit()
    return thread, followup, job


def _human_question() -> ReplySyncRequest:
    return ReplySyncRequest(
        gmail_thread_id="gmail-thread-1",
        gmail_message_id="gmail-inbound-1",
        from_email="owner@acme.example",
        subject="Re: website idea",
        body="Thanks. What does a redesign usually cost?",
        headers={},
        received_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_ambiguous_human_reply_is_classified_once_and_stops_followup(tmp_path):
    engine, factory = await _database(tmp_path)
    classifier = FakeClassifier()
    async with factory() as session:
        thread, followup, job = await _seed_thread(session)
        service = ReplyService(session, classifier=classifier)

        first = await service.sync(_human_question())
        second = await service.sync(_human_question())

        assert first.id == second.id
        assert classifier.calls == 1
        assert first.classification == ReplyClass.QUESTION
        assert first.summary == "The prospect asked for pricing information."
        assert first.intent_score == pytest.approx(0.78)
        assert first.questions == ["What does a redesign cost?"]
        assert first.recommended_action == "respond_today"
        assert await session.scalar(select(func.count()).select_from(Reply)) == 1

        await session.refresh(thread)
        await session.refresh(followup)
        await session.refresh(job)
        assert thread.followup_cancelled is True
        assert followup.state == FollowupState.CANCELLED.value
        assert followup.cancelled_reason == "inbound_human_reply"
        assert job.state == JobState.SKIPPED.value

    await engine.dispose()


@pytest.mark.asyncio
async def test_obvious_unsubscribe_is_deterministic_and_stops_followup(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        thread, followup, job = await _seed_thread(session)
        request = ReplySyncRequest(
            gmail_thread_id="gmail-thread-1",
            gmail_message_id="gmail-unsubscribe-1",
            from_email="owner@acme.example",
            subject="Re: website idea",
            body="Please remove me from your list and do not contact me again.",
            headers={},
            received_at=datetime.now(UTC),
        )
        result = await ReplyService(session, classifier=ExplodingClassifier()).sync(request)

        assert result.classification == ReplyClass.UNSUBSCRIBE
        assert result.intent_score == 0.0
        assert result.recommended_action == "suppress_contact"
        await session.refresh(thread)
        await session.refresh(followup)
        await session.refresh(job)
        assert thread.followup_cancelled is True
        assert followup.state == FollowupState.CANCELLED.value
        assert job.state == JobState.SKIPPED.value

    await engine.dispose()


@pytest.mark.asyncio
async def test_auto_reply_is_deterministic_but_does_not_cancel_followup(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        thread, followup, job = await _seed_thread(session)
        request = ReplySyncRequest(
            gmail_thread_id="gmail-thread-1",
            gmail_message_id="gmail-auto-1",
            from_email="owner@acme.example",
            subject="Automatic reply: website idea",
            body="I am out of the office until Monday.",
            headers={"Auto-Submitted": "auto-replied"},
            received_at=datetime.now(UTC),
        )
        result = await ReplyService(session, classifier=ExplodingClassifier()).sync(request)

        assert result.classification == ReplyClass.AUTO_REPLY
        await session.refresh(thread)
        await session.refresh(followup)
        await session.refresh(job)
        assert thread.followup_cancelled is False
        assert followup.state == FollowupState.QUEUED.value
        assert job.state == JobState.PENDING.value

    await engine.dispose()


@pytest.mark.asyncio
async def test_reply_sync_route_requires_secret_and_uses_injected_classifier(tmp_path, monkeypatch):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        await _seed_thread(session)

    classifier = FakeClassifier()

    async def override_session():
        async with factory() as session:
            yield session

    def override_classifier():
        return classifier

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_reply_classifier] = override_classifier
    monkeypatch.setenv("SCOUT_EMAIL_N8N_WEBHOOK_SECRET", "reply-secret")
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            unauthenticated = await client.post("/replies/sync", json=_human_question().model_dump(mode="json"))
            assert unauthenticated.status_code == 401

            response = await client.post(
                "/replies/sync",
                json=_human_question().model_dump(mode="json"),
                headers={"X-Scout-Email-Secret": "reply-secret"},
            )
            assert response.status_code == 200
            assert response.json()["classification"] == "QUESTION"
            assert response.json()["questions"] == ["What does a redesign cost?"]
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
