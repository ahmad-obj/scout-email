from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from scout_email.common.enums import LeadState
from scout_email.db.base import Base
from scout_email.db.models import Campaign, Contact, Evidence, Lead, ResearchReport
from scout_email.db.session import create_engine_and_sessionmaker
from scout_email.llm.gateway import LLMGateway
from scout_email.llm.schemas import ProviderResult
from scout_email.research.service import ResearchEvidenceError, ResearchService


FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures"
    / "intelligence"
    / "dental_evidence.json"
)


class FakeProvider:
    name = "fake"
    model = "fake-research-1"

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
        f"sqlite+aiosqlite:///{tmp_path / 'research.db'}"
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
        state=LeadState.RESEARCH_PENDING.value,
        name=name,
        normalized_name=name.casefold(),
        category="Dentist",
        city="Lahore",
        canonical_domain="example.com",
    )
    session.add(lead)
    await session.flush()
    return lead


@pytest.mark.asyncio
async def test_researcher_builds_and_persists_evidence_linked_dossier(tmp_path):
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
        session.add(contact)
        await session.flush()

        evidence_rows = [
            Evidence(
                lead_id=lead.id,
                kind="website_verification",
                claim_class="OBSERVED_FACT",
                claim="Verified website https://example.com is live over HTTPS",
                source_type="website_verification",
                source_url="https://example.com/",
                confidence=1.0,
            ),
            Evidence(
                lead_id=lead.id,
                kind="crawl_page",
                claim_class="OBSERVED_FACT",
                claim="Homepage clearly lists family and cosmetic dental services",
                source_type="crawl_page",
                source_url="https://example.com/",
                confidence=1.0,
            ),
            Evidence(
                lead_id=lead.id,
                kind="screenshot",
                claim_class="OBSERVED_FACT",
                claim="Mobile homepage screenshot shows booking CTA is not prominent",
                source_type="screenshot",
                source_url="https://example.com/",
                artifact_path="campaigns/1/leads/1/screenshots/homepage-mobile.png",
                confidence=0.95,
            ),
        ]
        session.add_all(evidence_rows)
        await session.commit()

        provider = FakeProvider([FIXTURE.read_text()])
        gateway = LLMGateway(
            providers={"fake": provider},
            task_routes={"researcher": "fake"},
        )
        service = ResearchService(session, gateway=gateway)
        output = await service.research(lead_id=lead.id)

        assert output.outcome == "COMPLETE"
        assert output.strengths
        assert output.website_findings
        assert output.contact is not None
        assert output.contact.contact_id == contact.id
        assert len(provider.calls) == 1

        known_evidence_ids = {row.id for row in evidence_rows}
        referenced = {
            evidence_id
            for finding in (
                output.strengths
                + output.website_findings
                + output.technical_findings
            )
            for evidence_id in finding.evidence_ids
        }
        assert referenced <= known_evidence_ids

        await session.refresh(lead)
        assert lead.state == LeadState.RESEARCHED.value
        assert await session.scalar(select(func.count()).select_from(ResearchReport)) == 1
        report = await session.scalar(select(ResearchReport).where(ResearchReport.lead_id == lead.id))
        assert report is not None
        assert report.status == "COMPLETE"
        persisted = json.loads(report.dossier_json)
        assert persisted["business"]["name"] == "Acme Dental"
        assert report.prompt_version == "researcher:v1"
        assert report.model_id == "fake-research-1"

    await engine.dispose()


@pytest.mark.asyncio
async def test_researcher_short_circuits_insufficient_evidence_without_model_call(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        lead = await _lead(session, name="Evidence Free Co")
        await session.commit()

        provider = FakeProvider([FIXTURE.read_text()])
        gateway = LLMGateway(
            providers={"fake": provider},
            task_routes={"researcher": "fake"},
        )
        service = ResearchService(session, gateway=gateway)
        output = await service.research(lead_id=lead.id)

        assert output.outcome == "INSUFFICIENT_EVIDENCE"
        assert provider.calls == []
        await session.refresh(lead)
        assert lead.state == LeadState.RESEARCH_PENDING.value
        report = await session.scalar(select(ResearchReport).where(ResearchReport.lead_id == lead.id))
        assert report is not None
        assert report.status == "INSUFFICIENT_EVIDENCE"

    await engine.dispose()


@pytest.mark.asyncio
async def test_unknown_evidence_reference_fails_closed_and_exits_researching(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        lead = await _lead(session)
        evidence = Evidence(
            lead_id=lead.id,
            kind="website_verification",
            claim_class="OBSERVED_FACT",
            claim="Website is live",
            source_type="website_verification",
            source_url="https://example.com/",
            confidence=1.0,
        )
        session.add(evidence)
        await session.commit()

        payload = json.loads(FIXTURE.read_text())
        payload["strengths"][0]["evidence_ids"] = [999]
        payload["website_findings"] = []
        payload["technical_findings"] = []
        payload["contact"] = None
        provider = FakeProvider([json.dumps(payload)])
        gateway = LLMGateway(
            providers={"fake": provider},
            task_routes={"researcher": "fake"},
        )
        service = ResearchService(session, gateway=gateway)

        with pytest.raises(ResearchEvidenceError):
            await service.research(lead_id=lead.id)

        await session.refresh(lead)
        assert lead.state == LeadState.RESEARCH_PENDING.value
        assert await session.scalar(select(func.count()).select_from(ResearchReport)) == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_researcher_clears_generated_contact_when_no_verified_contacts(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        lead = await _lead(session, name="No Contact Co")
        evidence = Evidence(
            lead_id=lead.id,
            kind="website_verification",
            claim_class="OBSERVED_FACT",
            claim="Website is live",
            source_type="website_verification",
            source_url="https://example.com/",
            confidence=1.0,
        )
        session.add(evidence)
        await session.commit()
        await session.refresh(evidence)

        payload = json.loads(FIXTURE.read_text())
        payload["strengths"] = [{"text": "Website is live", "evidence_ids": [evidence.id]}]
        payload["website_findings"] = []
        payload["technical_findings"] = []
        payload["contact"] = {"contact_id": 12345}
        provider = FakeProvider([json.dumps(payload)])
        gateway = LLMGateway(
            providers={"fake": provider},
            task_routes={"researcher": "fake"},
        )
        service = ResearchService(session, gateway=gateway)

        output = await service.research(lead_id=lead.id)

        assert output.contact is None
        assert len(provider.calls) == 1
        await session.refresh(lead)
        assert lead.state == LeadState.RESEARCHED.value
        report = await session.scalar(select(ResearchReport).where(ResearchReport.lead_id == lead.id))
        assert report is not None
        assert json.loads(report.dossier_json)["contact"] is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_researcher_context_declares_contact_must_be_null_when_none_are_verified(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        lead = await _lead(session, name="No Contact Context Co")
        evidence = Evidence(
            lead_id=lead.id,
            kind="website_verification",
            claim_class="OBSERVED_FACT",
            claim="Website is live",
            source_type="website_verification",
            source_url="https://example.com/",
            confidence=1.0,
        )
        session.add(evidence)
        await session.commit()
        await session.refresh(evidence)

        payload = json.loads(FIXTURE.read_text())
        payload["strengths"] = [{"text": "Website is live", "evidence_ids": [evidence.id]}]
        payload["website_findings"] = []
        payload["technical_findings"] = []
        payload["contact"] = None
        provider = FakeProvider([json.dumps(payload)])
        gateway = LLMGateway(
            providers={"fake": provider},
            task_routes={"researcher": "fake"},
        )
        service = ResearchService(session, gateway=gateway)

        await service.research(lead_id=lead.id)

        sent_context = json.loads(provider.calls[0]["user"])
        assert sent_context["reference_constraints"] == {
            "allowed_contact_ids": [],
            "contact_must_be_null": True,
        }

    await engine.dispose()


@pytest.mark.asyncio
async def test_unknown_contact_reference_still_fails_closed_when_verified_contacts_exist(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        lead = await _lead(session, name="Verified Contact Co")
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
            kind="website_verification",
            claim_class="OBSERVED_FACT",
            claim="Website is live",
            source_type="website_verification",
            source_url="https://example.com/",
            confidence=1.0,
        )
        session.add_all([contact, evidence])
        await session.commit()
        await session.refresh(evidence)

        payload = json.loads(FIXTURE.read_text())
        payload["strengths"] = [{"text": "Website is live", "evidence_ids": [evidence.id]}]
        payload["website_findings"] = []
        payload["technical_findings"] = []
        payload["contact"] = {"contact_id": 99999}
        provider = FakeProvider([json.dumps(payload)])
        gateway = LLMGateway(
            providers={"fake": provider},
            task_routes={"researcher": "fake"},
        )
        service = ResearchService(session, gateway=gateway)

        with pytest.raises(ResearchEvidenceError, match="invalid contact ID"):
            await service.research(lead_id=lead.id)

        await session.refresh(lead)
        assert lead.state == LeadState.RESEARCH_PENDING.value
        assert await session.scalar(select(func.count()).select_from(ResearchReport)) == 0

    await engine.dispose()
