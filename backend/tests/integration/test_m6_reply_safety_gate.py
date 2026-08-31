from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from scout_email.common.enums import FollowupState, JobState, ReplyClass
from scout_email.db.base import Base
from scout_email.db.models import Campaign, EmailThread, Followup, Job, Lead
from scout_email.db.session import create_engine_and_sessionmaker
from scout_email.replies.classifier import ReplyClassifier
from scout_email.replies.schemas import ReplyIntelligence, ReplySyncRequest
from scout_email.replies.service import ReplyService


class PositiveClassifier(ReplyClassifier):
    async def classify(self, request: ReplySyncRequest) -> ReplyIntelligence:
        return ReplyIntelligence(
            classification=ReplyClass.POSITIVE,
            summary="The prospect wants to continue the conversation.",
            intent_score=0.95,
            questions=[],
            recommended_action="respond_today",
        )


@pytest.mark.asyncio
async def test_positive_reply_is_thread_matched_and_stops_pending_followup(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'm6-positive.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as session:
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
            gmail_thread_id="gmail-thread-positive",
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

        request = ReplySyncRequest(
            gmail_thread_id="gmail-thread-positive",
            gmail_message_id="gmail-positive-1",
            from_email="owner@acme.example",
            subject="Re: website idea",
            body="Yes, this sounds useful. Let's discuss it.",
            headers={},
            received_at=datetime.now(UTC),
        )
        first = await ReplyService(session, classifier=PositiveClassifier()).sync(request)
        second = await ReplyService(session, classifier=PositiveClassifier()).sync(request)

        assert first.id == second.id
        assert first.classification == ReplyClass.POSITIVE
        assert first.intent_score == pytest.approx(0.95)
        await session.refresh(thread)
        await session.refresh(followup)
        await session.refresh(job)
        assert thread.followup_cancelled is True
        assert followup.state == FollowupState.CANCELLED.value
        assert followup.cancelled_reason == "inbound_human_reply"
        assert job.state == JobState.SKIPPED.value

    await engine.dispose()
