from __future__ import annotations

import json

import pytest

from scout_email.common.enums import LeadState
from scout_email.db.base import Base
from scout_email.db.models import Campaign, Contact, Evidence, Lead
from scout_email.db.session import create_engine_and_sessionmaker
from scout_email.llm.gateway import LLMGateway
from scout_email.llm.schemas import ProviderResult
from scout_email.research.service import ResearchService


class FakeProvider:
    name = "fake"
    model = "fake-research-contact-schema"

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


def _contact_id_schema(node: object) -> dict:
    if isinstance(node, dict):
        properties = node.get("properties")
        if isinstance(properties, dict) and "contact_id" in properties:
            contact_schema = properties["contact_id"]
            assert isinstance(contact_schema, dict)
            return contact_schema
        for value in node.values():
            try:
                return _contact_id_schema(value)
            except LookupError:
                pass
    elif isinstance(node, list):
        for value in node:
            try:
                return _contact_id_schema(value)
            except LookupError:
                pass
    raise LookupError("contact_id schema not found")


async def _database(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'research-contact-schema.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, factory


async def _fixture(session):
    campaign = Campaign(
        name="Contact schema fixture",
        status="ACTIVE",
        max_per_day=10,
        human_approval_required=True,
    )
    session.add(campaign)
    await session.flush()

    unrelated = Lead(
        campaign_id=campaign.id,
        state=LeadState.RESEARCH_PENDING.value,
        name="Unrelated Co",
        normalized_name="unrelated co",
        canonical_domain="unrelated.example",
    )
    lead = Lead(
        campaign_id=campaign.id,
        state=LeadState.RESEARCH_PENDING.value,
        name="Constrained Contact Co",
        normalized_name="constrained contact co",
        category="Services",
        city="Portland",
        canonical_domain="example.com",
    )
    session.add_all([unrelated, lead])
    await session.flush()

    unrelated_contact = Contact(
        lead_id=unrelated.id,
        email="other@unrelated.example",
        normalized_email="other@unrelated.example",
        contact_type="business",
        state="VERIFIED",
        source_url="https://unrelated.example/contact",
        confidence=1.0,
    )
    session.add(unrelated_contact)
    await session.flush()

    contacts = [
        Contact(
            lead_id=lead.id,
            email="sales@example.com",
            normalized_email="sales@example.com",
            contact_type="business",
            state="VERIFIED",
            source_url="https://example.com/contact",
            confidence=1.0,
        ),
        Contact(
            lead_id=lead.id,
            email="hello@example.com",
            normalized_email="hello@example.com",
            contact_type="business",
            state="VERIFIED",
            source_url="https://example.com/about",
            confidence=1.0,
        ),
    ]
    evidence = Evidence(
        lead_id=lead.id,
        kind="website_verification",
        claim_class="OBSERVED_FACT",
        claim="Website is live",
        source_type="website_verification",
        source_url="https://example.com/",
        confidence=1.0,
    )
    session.add_all([*contacts, evidence])
    await session.commit()
    await session.refresh(unrelated_contact)
    await session.refresh(lead)
    await session.refresh(evidence)
    for contact in contacts:
        await session.refresh(contact)
    return lead, unrelated_contact, contacts, evidence


def _payload(*, lead: Lead, evidence_id: int, contact_id: int) -> str:
    return json.dumps(
        {
            "business": {
                "name": lead.name,
                "summary": "Public website is live.",
                "category": lead.category,
                "location": lead.city,
            },
            "business_model": {
                "target_customers": [],
                "offerings": [],
                "primary_conversion": None,
            },
            "presence": {"website_state": "LIVE", "social_profiles": []},
            "strengths": [
                {"text": "Website is live", "evidence_ids": [evidence_id]}
            ],
            "website_findings": [],
            "technical_findings": [],
            "contact": {"contact_id": contact_id},
            "confidence": 0.8,
            "outcome": "COMPLETE",
        }
    )


@pytest.mark.asyncio
async def test_researcher_schema_restricts_contact_id_to_verified_lead_contacts(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        lead, unrelated_contact, contacts, evidence = await _fixture(session)
        allowed_ids = [contact.id for contact in contacts]
        assert unrelated_contact.id not in allowed_ids

        provider = FakeProvider(
            [
                _payload(
                    lead=lead,
                    evidence_id=evidence.id,
                    contact_id=allowed_ids[0],
                )
            ]
        )
        gateway = LLMGateway(
            providers={"fake": provider},
            task_routes={"researcher": "fake"},
        )

        output = await ResearchService(session, gateway=gateway).research(lead_id=lead.id)

        assert output.contact is not None
        assert output.contact.contact_id == allowed_ids[0]
        assert len(provider.calls) == 1
        contact_schema = _contact_id_schema(provider.calls[0]["schema"])
        assert contact_schema.get("enum") == allowed_ids
        assert unrelated_contact.id not in contact_schema["enum"]

    await engine.dispose()


@pytest.mark.asyncio
async def test_researcher_repairs_out_of_set_contact_id_inside_gateway_schema_validation(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        lead, unrelated_contact, contacts, evidence = await _fixture(session)
        allowed_ids = [contact.id for contact in contacts]
        assert unrelated_contact.id not in allowed_ids

        provider = FakeProvider(
            [
                _payload(
                    lead=lead,
                    evidence_id=evidence.id,
                    contact_id=unrelated_contact.id,
                ),
                _payload(
                    lead=lead,
                    evidence_id=evidence.id,
                    contact_id=allowed_ids[0],
                ),
            ]
        )
        gateway = LLMGateway(
            providers={"fake": provider},
            task_routes={"researcher": "fake"},
        )

        output = await ResearchService(session, gateway=gateway).research(lead_id=lead.id)

        assert output.contact is not None
        assert output.contact.contact_id == allowed_ids[0]
        assert len(provider.calls) == 2
        assert _contact_id_schema(provider.calls[0]["schema"]).get("enum") == allowed_ids
        assert _contact_id_schema(provider.calls[1]["schema"]).get("enum") == allowed_ids

    await engine.dispose()
