from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select

from scout_email.common.enums import LeadState
from scout_email.db.base import Base
from scout_email.db.models import (
    AuditFinding,
    Campaign,
    Contact,
    Evidence,
    Job,
    Lead,
    ResearchReport,
    Strategy,
)
from scout_email.db.session import create_engine_and_sessionmaker
from scout_email.llm.gateway import LLMGateway
from scout_email.llm.schemas import ProviderResult
from scout_email.strategy.service import StrategyEvidenceError, StrategyService


class FakeProvider:
    name = "fake"
    model = "fake-strategy-1"

    def __init__(self, payloads: list[str]) -> None:
        self.payloads = list(payloads)
        self.calls: list[dict] = []

    async def generate_json(self, *, system: str, user: str, schema: dict) -> ProviderResult:
        self.calls.append({"system": system, "user": user, "schema": schema})
        return ProviderResult(
            provider=self.name,
            model=self.model,
            text=self.payloads.pop(0),
        )


async def _database(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'strategy.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, factory


async def _lead(session, *, name: str = "Acme Dental") -> Lead:
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
        state=LeadState.RESEARCHED.value,
        name=name,
        normalized_name=name.casefold(),
        category="Dentist",
        city="Lahore",
        canonical_domain="example.com",
    )
    session.add(lead)
    await session.flush()
    return lead


def _research_dossier(*, outcome: str = "COMPLETE") -> dict:
    return {
        "business": {
            "name": "Acme Dental",
            "summary": "Established local dental clinic.",
            "category": "Dentist",
            "location": "Lahore",
        },
        "business_model": {
            "target_customers": ["local patients"],
            "offerings": ["family dentistry"],
            "primary_conversion": "book appointment",
        },
        "presence": {"website_state": "LIVE", "social_profiles": []},
        "strengths": [],
        "website_findings": [],
        "technical_findings": [],
        "contact": None,
        "confidence": 0.9,
        "outcome": outcome,
    }


def _contact_payload(*, evidence_ids: list[int]) -> str:
    return json.dumps(
        {
            "decision": "CONTACT",
            "candidates": [
                {
                    "problem": "The booking CTA is difficult to notice on mobile.",
                    "angle": "Reduce booking friction on mobile.",
                    "evidence_ids": evidence_ids,
                    "score": {
                        "severity": 0.75,
                        "evidence_confidence": 0.95,
                        "business_impact": 0.8,
                        "weberaise_fit": 0.95,
                        "explainability": 0.9,
                        "generic_speculation_risk": 0.1,
                    },
                    "safe_to_reference": True,
                }
            ],
            "persuasion_brief": {
                "primary_angle": "reduce mobile booking friction",
                "do_not_use": ["revenue-loss percentages", "fake familiarity"],
            },
            "supporting_evidence_ids": evidence_ids,
            "score_components": {
                "severity": 0.75,
                "evidence_confidence": 0.95,
                "business_impact": 0.8,
                "weberaise_fit": 0.95,
                "explainability": 0.9,
                "generic_speculation_risk": 0.1,
            },
            "confidence": 0.92,
            "rationale": "The issue is visible, specific, and directly related to website conversion UX.",
        }
    )


@pytest.mark.asyncio
async def test_contact_strategy_persists_audit_and_requires_known_evidence_and_contact(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        lead = await _lead(session)
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
            claim="Mobile homepage screenshot shows booking CTA is not prominent",
            source_type="screenshot",
            source_url="https://example.com/",
            artifact_path="campaigns/1/leads/1/screenshots/homepage-mobile.png",
            confidence=0.95,
        )
        session.add_all([contact, evidence])
        await session.flush()
        report = ResearchReport(
            lead_id=lead.id,
            status="COMPLETE",
            dossier_json=json.dumps(_research_dossier()),
            confidence=0.9,
            prompt_version="researcher:v1",
            model_id="fake-research-1",
        )
        session.add(report)
        await session.commit()

        provider = FakeProvider([_contact_payload(evidence_ids=[evidence.id])])
        gateway = LLMGateway(
            providers={"fake": provider},
            task_routes={"strategist": "fake"},
        )
        service = StrategyService(session, gateway=gateway)
        output = await service.strategize(lead_id=lead.id)

        assert output.decision == "CONTACT"
        assert output.persuasion_brief is not None
        assert output.persuasion_brief.primary_angle == "reduce mobile booking friction"
        assert output.supporting_evidence_ids == [evidence.id]
        assert len(provider.calls) == 1

        await session.refresh(lead)
        assert lead.state == LeadState.CONTACTABLE.value
        assert await session.scalar(select(func.count()).select_from(AuditFinding)) == 1
        assert await session.scalar(select(func.count()).select_from(Strategy)) == 1
        assert await session.scalar(select(func.count()).select_from(Job)) == 0
        row = await session.scalar(select(Strategy).where(Strategy.lead_id == lead.id))
        assert row is not None
        assert row.decision == "CONTACT"
        assert row.primary_angle == "reduce mobile booking friction"
        assert json.loads(row.score_components_json)["overall_score"] > 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_excellent_presence_can_be_skipped_without_writer_job(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        lead = await _lead(session, name="Excellent Co")
        evidence = Evidence(
            lead_id=lead.id,
            kind="crawl_page",
            claim_class="OBSERVED_FACT",
            claim="Website has clear service hierarchy and prominent conversion actions",
            source_type="crawl_page",
            source_url="https://example.com/",
            confidence=0.95,
        )
        session.add(evidence)
        session.add(
            ResearchReport(
                lead_id=lead.id,
                status="COMPLETE",
                dossier_json=json.dumps(_research_dossier()),
                confidence=0.95,
                prompt_version="researcher:v1",
                model_id="fake-research-1",
            )
        )
        await session.commit()

        provider = FakeProvider(
            [
                json.dumps(
                    {
                        "decision": "SKIP",
                        "candidates": [],
                        "persuasion_brief": None,
                        "supporting_evidence_ids": [],
                        "score_components": None,
                        "confidence": 0.94,
                        "rationale": "No specific, evidence-backed WEBERAISE opportunity is compelling enough to justify outreach.",
                    }
                )
            ]
        )
        gateway = LLMGateway(
            providers={"fake": provider},
            task_routes={"strategist": "fake"},
        )
        output = await StrategyService(session, gateway=gateway).strategize(lead_id=lead.id)

        assert output.decision == "SKIP"
        await session.refresh(lead)
        assert lead.state == LeadState.SKIPPED.value
        assert await session.scalar(select(func.count()).select_from(Job)) == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_missing_research_evidence_returns_research_more_without_model_or_writer_job(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        lead = await _lead(session, name="Thin Evidence Co")
        session.add(
            ResearchReport(
                lead_id=lead.id,
                status="INSUFFICIENT_EVIDENCE",
                dossier_json=json.dumps(_research_dossier(outcome="INSUFFICIENT_EVIDENCE")),
                confidence=0.0,
                prompt_version="researcher:v1",
                model_id=None,
            )
        )
        await session.commit()

        provider = FakeProvider([])
        gateway = LLMGateway(
            providers={"fake": provider},
            task_routes={"strategist": "fake"},
        )
        output = await StrategyService(session, gateway=gateway).strategize(lead_id=lead.id)

        assert output.decision == "RESEARCH_MORE"
        assert provider.calls == []
        await session.refresh(lead)
        assert lead.state == LeadState.RESEARCH_PENDING.value
        assert await session.scalar(select(func.count()).select_from(Job)) == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_contact_with_unknown_evidence_fails_closed(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        lead = await _lead(session)
        session.add(
            Contact(
                lead_id=lead.id,
                email="hello@example.com",
                normalized_email="hello@example.com",
                contact_type="business",
                state="VERIFIED",
                source_url="https://example.com/contact",
                confidence=1.0,
            )
        )
        session.add(
            Evidence(
                lead_id=lead.id,
                kind="crawl_page",
                claim_class="OBSERVED_FACT",
                claim="Website is live",
                source_type="crawl_page",
                source_url="https://example.com/",
                confidence=1.0,
            )
        )
        session.add(
            ResearchReport(
                lead_id=lead.id,
                status="COMPLETE",
                dossier_json=json.dumps(_research_dossier()),
                confidence=0.9,
                prompt_version="researcher:v1",
                model_id="fake-research-1",
            )
        )
        await session.commit()

        provider = FakeProvider([_contact_payload(evidence_ids=[999])])
        gateway = LLMGateway(
            providers={"fake": provider},
            task_routes={"strategist": "fake"},
        )

        with pytest.raises(StrategyEvidenceError):
            await StrategyService(session, gateway=gateway).strategize(lead_id=lead.id)

        await session.refresh(lead)
        assert lead.state == LeadState.RESEARCHED.value
        assert await session.scalar(select(func.count()).select_from(Strategy)) == 0
        assert await session.scalar(select(func.count()).select_from(Job)) == 0

    await engine.dispose()
