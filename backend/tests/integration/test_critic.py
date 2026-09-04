from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select

from scout_email.common.enums import ApprovalState, LeadState, MessageState
from scout_email.db.base import Base
from scout_email.db.models import (
    Campaign,
    Contact,
    DoNotContact,
    EmailDraft,
    EmailDraftClaim,
    EmailReview,
    Evidence,
    Lead,
    OutboundMessage,
)
from scout_email.db.session import create_engine_and_sessionmaker
from scout_email.llm.gateway import LLMGateway
from scout_email.llm.schemas import ProviderResult
from scout_email.writing.critic import CriticService


class FakeProvider:
    name = "fake"
    model = "fake-critic-1"

    def __init__(self, payloads: list[str]) -> None:
        self.payloads = list(payloads)
        self.calls: list[dict] = []

    async def generate_json(self, *, system: str, user: str, schema: dict) -> ProviderResult:
        self.calls.append({"system": system, "user": user, "schema": schema})
        return ProviderResult(provider=self.name, model=self.model, text=self.payloads.pop(0))


async def _database(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'critic.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, factory


async def _seed_draft(session, *, body: str | None = None, evidence_ids: list[int] | None = None):
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
    evidence = Evidence(
        lead_id=lead.id,
        kind="screenshot",
        claim_class="OBSERVED_FACT",
        claim="The mobile booking CTA is difficult to spot.",
        source_type="screenshot",
        source_url="https://example.com/",
        confidence=0.95,
    )
    session.add_all([contact, evidence])
    await session.flush()
    draft = EmailDraft(
        lead_id=lead.id,
        subject="Mobile booking thought",
        body=body or "I noticed the booking action is easy to miss on mobile. That may add friction for visitors trying to book. Would it be useful if I sent one focused idea?",
        writer_prompt_version="writer:v1",
        model_id="fake-writer-1",
        approval_state=ApprovalState.PENDING.value,
    )
    session.add(draft)
    await session.flush()
    session.add(
        EmailDraftClaim(
            draft_id=draft.id,
            claim_text="The mobile booking CTA is difficult to spot.",
            claim_class="OBSERVED_FACT",
            evidence_ids_json=json.dumps(evidence_ids or [evidence.id]),
        )
    )
    await session.commit()
    return campaign, lead, contact, evidence, draft


def _model_review(
    decision: str = "APPROVE",
    *,
    genericness: int = 10,
    evidence_id: int = 1,
) -> str:
    return json.dumps(
        {
            "decision": decision,
            "scores": {
                "specificity": 92,
                "naturalness": 88,
                "persuasiveness": 82,
                "evidence_integrity": 100,
                "genericness": genericness,
                "spamminess": 8,
            },
            "issues": [] if decision == "APPROVE" else ["Opening could fit unrelated businesses."],
            "assertion_audits": [
                {
                    "body_assertion": "The booking action is easy to miss on mobile.",
                    "assertion_type": "PROSPECT_FACT",
                    "ledger_claim": "The mobile booking CTA is difficult to spot.",
                    "evidence_ids": [evidence_id],
                    "company_context_quote": None,
                    "verdict": "ENTAILED",
                    "explanation": "The wording preserves the persisted observation.",
                }
            ],
            "coverage_complete": True,
            "copy_abstractions": [],
        }
    )


@pytest.mark.asyncio
async def test_critic_persists_independent_model_approval(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        _campaign, _lead, _contact, evidence, draft = await _seed_draft(session)
        provider = FakeProvider([_model_review(evidence_id=evidence.id)])
        gateway = LLMGateway(providers={"fake": provider}, task_routes={"critic": "fake"})

        result = await CriticService(session, gateway=gateway).review(draft_id=draft.id)

        assert result.decision == "APPROVE"
        assert len(provider.calls) == 1
        row = await session.scalar(select(EmailReview).where(EmailReview.draft_id == draft.id))
        assert row is not None
        assert row.decision == "APPROVE"
        assert row.model_id == "fake-critic-1"

    await engine.dispose()


@pytest.mark.asyncio
async def test_critic_hard_rejects_unsupported_quantified_loss_without_model_call(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        _campaign, _lead, _contact, _evidence, draft = await _seed_draft(
            session, body="You're losing 40% of bookings because of this."
        )
        provider = FakeProvider([_model_review()])
        gateway = LLMGateway(providers={"fake": provider}, task_routes={"critic": "fake"})

        result = await CriticService(session, gateway=gateway).review(draft_id=draft.id)

        assert result.decision == "REJECT"
        assert "unsupported_quantified_loss" in result.issues
        assert provider.calls == []

    await engine.dispose()


@pytest.mark.asyncio
async def test_critic_hard_rejects_unknown_evidence_without_model_call(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        _campaign, _lead, _contact, _evidence, draft = await _seed_draft(
            session, evidence_ids=[999]
        )
        provider = FakeProvider([_model_review()])
        gateway = LLMGateway(providers={"fake": provider}, task_routes={"critic": "fake"})

        result = await CriticService(session, gateway=gateway).review(draft_id=draft.id)

        assert result.decision == "REJECT"
        assert "unknown_evidence" in result.issues
        assert provider.calls == []

    await engine.dispose()


@pytest.mark.asyncio
async def test_critic_hard_rejects_dnc_and_duplicate_outreach(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        campaign, lead, contact, _evidence, draft = await _seed_draft(session)
        session.add(
            DoNotContact(
                email=contact.normalized_email,
                reason="opt out",
                source="recipient",
            )
        )
        session.add(
            OutboundMessage(
                campaign_id=campaign.id,
                lead_id=lead.id,
                draft_id=draft.id,
                recipient_email=contact.normalized_email,
                subject="Earlier",
                body="Earlier outreach",
                state=MessageState.SENT.value,
                idempotency_key="existing-send",
            )
        )
        await session.commit()
        provider = FakeProvider([_model_review()])
        gateway = LLMGateway(providers={"fake": provider}, task_routes={"critic": "fake"})

        result = await CriticService(session, gateway=gateway).review(draft_id=draft.id)

        assert result.decision == "REJECT"
        assert {"do_not_contact", "duplicate_outreach"} <= set(result.issues)
        assert provider.calls == []
        assert await session.scalar(select(func.count()).select_from(EmailReview)) == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_generic_model_review_requests_rewrite(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        _campaign, _lead, _contact, evidence, draft = await _seed_draft(session)
        provider = FakeProvider([
            _model_review("REWRITE", genericness=88, evidence_id=evidence.id)
        ])
        gateway = LLMGateway(providers={"fake": provider}, task_routes={"critic": "fake"})

        result = await CriticService(session, gateway=gateway).review(draft_id=draft.id)

        assert result.decision == "REWRITE"
        assert result.scores.genericness == 88
        assert result.issues

    await engine.dispose()
