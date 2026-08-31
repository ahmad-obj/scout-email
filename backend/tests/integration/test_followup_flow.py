from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from scout_email.approval.service import ApprovalService
from scout_email.campaigns.models import CampaignPolicy
from scout_email.common.enums import (
    ApprovalState,
    ClaimClass,
    ContactState,
    DraftReviewDecision,
    FollowupState,
    LeadState,
    MessageState,
)
from scout_email.db.base import Base
from scout_email.db.models import (
    Campaign,
    Contact,
    EmailDraft,
    EmailDraftClaim,
    EmailThread,
    Evidence,
    Followup,
    Lead,
    OutboundMessage,
    ResearchReport,
    Strategy,
)
from scout_email.db.session import create_engine_and_sessionmaker
from scout_email.llm.schemas import GenerationMetadata, StructuredGeneration
from scout_email.replies.followup import (
    FollowupPreparationError,
    FollowupService,
)
from scout_email.writing.playbook import WritingPlaybook


class FakeFollowupGateway:
    def __init__(self, *, evidence_id: int | None = None) -> None:
        self.evidence_id = evidence_id
        self.calls: list[tuple[str, dict]] = []

    async def generate(self, *, task, context, response_model, prompt_version):
        self.calls.append((task, context))
        evidence_id = self.evidence_id or int(context["allowed_evidence"][0]["id"])
        if task == "followup_writer":
            output = response_model.model_validate(
                {
                    "strategy": "ADD_CONCRETE_IDEA",
                    "subject": "Re: website idea",
                    "body": (
                        "One concrete idea: make the appointment action visible earlier "
                        "on mobile so interested visitors can reach it with less friction."
                    ),
                    "claims": [
                        {
                            "text": "The mobile booking action appears later than the first viewport.",
                            "claim_class": "OBSERVED_FACT",
                            "evidence_ids": [evidence_id],
                        }
                    ],
                }
            )
        elif task == "followup_critic":
            output = response_model.model_validate(
                {
                    "decision": "APPROVE",
                    "issues": [],
                }
            )
        else:  # pragma: no cover - protects the fake contract
            raise AssertionError(f"unexpected task {task}")
        return StructuredGeneration(
            output=output,
            metadata=GenerationMetadata(
                task=task,
                provider="fake",
                model="fake-followup-model",
                prompt_version=prompt_version,
                status="COMPLETE",
                repair_attempted=False,
                generated_at=datetime.now(UTC),
            ),
        )


def _playbook() -> WritingPlaybook:
    return WritingPlaybook(
        company_context="WEBERAISE designs and develops business websites.",
        writing_rules="Be concise, specific, respectful, and evidence-backed.",
        banned_phrases=("elevate your online presence",),
        cta_rules="Use a low-pressure CTA.",
        approved_examples=(),
        rejected_patterns=(),
        version_hash="a" * 64,
    )


async def _seed(session, *, sent_at: datetime):
    campaign = Campaign(
        name="Lahore Dentists",
        status="ACTIVE",
        max_per_day=10,
        human_approval_required=True,
    )
    session.add(campaign)
    await session.flush()
    session.add(
        CampaignPolicy(
            campaign_id=campaign.id,
            qualification_json="{}",
            follow_up_json=json.dumps(
                {"enabled": True, "max_followups": 1, "delay_days": 4}
            ),
        )
    )
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
    evidence = Evidence(
        lead_id=lead.id,
        kind="ux_observation",
        source_type="mobile_screenshot",
        source_url="https://acme.example/",
        artifact_path="campaigns/1/leads/1/mobile-home.png",
        claim_class=ClaimClass.OBSERVED_FACT.value,
        claim="The booking action appears below the first mobile viewport.",
        confidence=0.96,
    )
    report = ResearchReport(
        lead_id=lead.id,
        status="COMPLETE",
        dossier_json=json.dumps(
            {
                "business": {"name": "Acme Dental"},
                "website_findings": ["Booking action is later on mobile."],
                "strengths": ["Clear service specialization."],
            }
        ),
        confidence=0.9,
    )
    session.add_all([contact, evidence, report])
    await session.flush()
    strategy = Strategy(
        lead_id=lead.id,
        decision="CONTACT",
        primary_angle="mobile booking friction",
        persuasion_brief_json=json.dumps(
            {
                "primary_angle": "mobile booking friction",
                "observation": "Booking action is later on mobile.",
                "business_implication": "Interested visitors may face extra friction.",
            }
        ),
        score_components_json=json.dumps(
            {
                "severity": 0.8,
                "evidence_confidence": 0.96,
                "business_impact": 0.8,
                "weberaise_fit": 0.9,
                "explainability": 0.9,
                "generic_speculation_risk": 0.1,
            }
        ),
        confidence=0.9,
    )
    session.add(strategy)
    await session.flush()
    original_draft = EmailDraft(
        lead_id=lead.id,
        strategy_id=strategy.id,
        subject="Quick website thought",
        body="I noticed the booking path could be clearer on mobile.",
        writer_prompt_version="writer:v1",
        model_id="fake",
        approval_state=ApprovalState.APPROVED.value,
    )
    session.add(original_draft)
    await session.flush()
    outbound = OutboundMessage(
        campaign_id=campaign.id,
        lead_id=lead.id,
        draft_id=original_draft.id,
        recipient_email=contact.normalized_email,
        subject=original_draft.subject,
        body=original_draft.body,
        state=MessageState.SENT.value,
        idempotency_key=f"initial:{lead.id}",
        gmail_message_id="gmail-initial-1",
        gmail_thread_id="gmail-thread-1",
        sent_at=sent_at,
    )
    thread = EmailThread(
        lead_id=lead.id,
        campaign_id=campaign.id,
        gmail_thread_id="gmail-thread-1",
        followup_stage=0,
        followup_cancelled=False,
    )
    session.add_all([outbound, thread])
    await session.commit()
    return campaign, lead, contact, evidence, report, strategy, outbound, thread


@pytest.mark.asyncio
async def test_prepare_followup_uses_evidence_independent_critique_and_human_approval(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'followup.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    now = datetime.now(UTC)
    async with factory() as session:
        _, _, _, evidence, _, _, _, thread = await _seed(
            session, sent_at=now - timedelta(days=5)
        )
        gateway = FakeFollowupGateway()
        prepared = await FollowupService(
            session,
            gateway=gateway,
            playbook=_playbook(),
        ).prepare(thread_id=thread.id, now=now)

        assert prepared.stage == 1
        assert prepared.state == FollowupState.PENDING_APPROVAL
        assert prepared.critic_decision == DraftReviewDecision.APPROVE
        assert [task for task, _ in gateway.calls] == ["followup_writer", "followup_critic"]
        writer_context = gateway.calls[0][1]
        assert writer_context["original_message"]["gmail_thread_id"] == "gmail-thread-1"
        assert writer_context["allowed_evidence"][0]["id"] == evidence.id
        assert "raw_html" not in json.dumps(writer_context).casefold()

        followup = await session.get(Followup, prepared.followup_id)
        draft = await session.get(EmailDraft, prepared.draft_id)
        claims = list(
            (
                await session.scalars(
                    select(EmailDraftClaim).where(EmailDraftClaim.draft_id == draft.id)
                )
            ).all()
        )
        assert followup is not None and followup.stage == 1
        assert followup.draft_id == draft.id
        assert draft is not None and draft.approval_state == ApprovalState.PENDING.value
        assert json.loads(claims[0].evidence_ids_json) == [evidence.id]

        approval = await ApprovalService(session).approve(
            draft_id=draft.id, reviewer="ahmad"
        )
        assert approval.approval_state == ApprovalState.APPROVED.value
        assert await ApprovalService(session).is_currently_approved(draft.id) is True

        with pytest.raises(FollowupPreparationError, match="followup_already_exists"):
            await FollowupService(
                session,
                gateway=FakeFollowupGateway(),
                playbook=_playbook(),
            ).prepare(thread_id=thread.id, now=now)

    await engine.dispose()


@pytest.mark.asyncio
async def test_unknown_followup_evidence_fails_before_draft_or_followup_persistence(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'followup-unsafe.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    now = datetime.now(UTC)
    async with factory() as session:
        _, _, _, _, _, _, _, thread = await _seed(
            session, sent_at=now - timedelta(days=5)
        )
        with pytest.raises(FollowupPreparationError, match="unknown_or_unsafe_evidence"):
            await FollowupService(
                session,
                gateway=FakeFollowupGateway(evidence_id=999999),
                playbook=_playbook(),
            ).prepare(thread_id=thread.id, now=now)

        followup_count = int(
            await session.scalar(select(func.count()).select_from(Followup)) or 0
        )
        followup_draft_count = int(
            await session.scalar(
                select(func.count())
                .select_from(EmailDraft)
                .where(EmailDraft.writer_prompt_version == "followup_writer:v1")
            )
            or 0
        )
        assert followup_count == 0
        assert followup_draft_count == 0

    await engine.dispose()
