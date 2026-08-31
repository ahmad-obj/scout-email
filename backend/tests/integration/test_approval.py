from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select

from scout_email.approval.models import EmailEditMetadata, HumanApprovalEvent
from scout_email.approval.service import ApprovalService, content_hash
from scout_email.common.enums import ApprovalState, LeadState
from scout_email.common.errors import InvalidStateTransitionError
from scout_email.db.base import Base
from scout_email.db.models import Campaign, EmailDraft, EmailEdit, EmailReview, Lead, Strategy
from scout_email.db.session import create_engine_and_sessionmaker
from scout_email.jobs.models import JobRuntime  # noqa: F401 - register runtime table
from scout_email.writing.models import DraftGenerationMetadata


async def _database(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'approval.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, factory


async def _seed_reviewed_draft(session):
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
    )
    session.add(lead)
    await session.flush()
    strategy = Strategy(
        lead_id=lead.id,
        decision="CONTACT",
        primary_angle="mobile booking friction",
        persuasion_brief_json=json.dumps({"primary_angle": "mobile booking friction"}),
        score_components_json="{}",
        confidence=0.92,
        prompt_version="strategist:v1",
        model_id="fake-strategy",
    )
    session.add(strategy)
    await session.flush()
    draft = EmailDraft(
        lead_id=lead.id,
        strategy_id=strategy.id,
        subject="Mobile booking thought",
        body="Your mobile booking action is easy to miss. Would it be useful if I sent one focused idea?",
        writer_prompt_version="writer:v1",
        model_id="fake-writer",
        approval_state=ApprovalState.PENDING.value,
    )
    session.add(draft)
    await session.flush()
    session.add_all(
        [
            EmailReview(
                draft_id=draft.id,
                decision="APPROVE",
                scores_json=json.dumps({"specificity": 90}),
                issues_json="[]",
                prompt_version="critic:v1",
                model_id="fake-critic",
            ),
            DraftGenerationMetadata(
                draft_id=draft.id,
                playbook_hash="a" * 64,
                strategy_label="CONVERSION_PROBLEM",
                recent_similarity=0.1,
            ),
        ]
    )
    await session.commit()
    return campaign, lead, draft


@pytest.mark.asyncio
async def test_approval_is_bound_to_exact_content_and_edit_invalidates_it(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        _campaign, lead, draft = await _seed_reviewed_draft(session)
        service = ApprovalService(session)

        approved = await service.approve(draft_id=draft.id, reviewer="human")
        first_hash = content_hash(draft.subject, draft.body)
        assert approved.content_hash == first_hash
        assert draft.approval_state == ApprovalState.APPROVED.value
        assert draft.approved_content_hash == first_hash

        edited = await service.edit(
            draft_id=draft.id,
            subject="Quick mobile booking thought",
            body="The booking action is easy to miss on mobile. Want me to send one focused idea?",
            reviewer="human",
            edit_context="CTA",
        )
        assert edited.approval_state == ApprovalState.PENDING.value
        assert draft.approved_content_hash is None
        assert content_hash(draft.subject, draft.body) != first_hash
        assert await service.is_currently_approved(draft.id) is False

        edit = await session.scalar(select(EmailEdit).where(EmailEdit.draft_id == draft.id))
        assert edit is not None
        metadata = await session.scalar(
            select(EmailEditMetadata).where(EmailEditMetadata.edit_id == edit.id)
        )
        assert metadata is not None
        assert metadata.lead_industry == lead.category
        assert metadata.playbook_hash == "a" * 64
        assert metadata.writer_prompt_version == "writer:v1"

        events = list(
            (
                await session.scalars(
                    select(HumanApprovalEvent)
                    .where(HumanApprovalEvent.draft_id == draft.id)
                    .order_by(HumanApprovalEvent.id)
                )
            ).all()
        )
        assert [event.action for event in events] == ["APPROVE", "EDIT"]
        assert events[0].subject_snapshot == "Mobile booking thought"
        assert events[1].subject_snapshot == "Quick mobile booking thought"

    await engine.dispose()


@pytest.mark.asyncio
async def test_rejected_draft_is_terminal_but_can_request_regeneration(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        _campaign, _lead, draft = await _seed_reviewed_draft(session)
        service = ApprovalService(session)

        rejected = await service.reject(draft_id=draft.id, reviewer="human", reason="not suitable")
        assert rejected.approval_state == ApprovalState.REJECTED.value

        with pytest.raises(InvalidStateTransitionError):
            await service.approve(draft_id=draft.id, reviewer="human")
        with pytest.raises(InvalidStateTransitionError):
            await service.edit(
                draft_id=draft.id,
                subject="Changed",
                body="Changed body",
                reviewer="human",
            )

        regeneration = await service.regenerate(draft_id=draft.id, reviewer="human")
        assert regeneration.job.kind == "writer_critic"
        assert regeneration.job.payload == {"lead_id": draft.lead_id, "source_draft_id": draft.id}
        assert regeneration.job.state == "PENDING"

        again = await service.regenerate(draft_id=draft.id, reviewer="human")
        assert again.job.id == regeneration.job.id
        assert await session.scalar(select(func.count()).select_from(HumanApprovalEvent)) == 3

    await engine.dispose()
