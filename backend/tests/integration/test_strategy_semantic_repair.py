from __future__ import annotations

import json

import pytest

from scout_email.common.enums import LeadState
from scout_email.db.base import Base
from scout_email.db.models import Campaign, Contact, Evidence, Lead, ResearchReport
from scout_email.db.session import create_engine_and_sessionmaker
from scout_email.llm.gateway import LLMGateway
from scout_email.llm.schemas import ProviderResult
from scout_email.strategy.service import StrategyService


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


def _contact_payload(*, evidence_id: int, safe_to_reference: bool) -> str:
    return json.dumps(
        {
            "decision": "CONTACT",
            "candidates": [
                {
                    "problem": "The homepage lacks responsive viewport signals.",
                    "angle": "Improve mobile usability and presentation.",
                    "evidence_ids": [evidence_id],
                    "score": {
                        "severity": 0.7,
                        "evidence_confidence": 0.95,
                        "business_impact": 0.7,
                        "weberaise_fit": 0.95,
                        "explainability": 0.9,
                        "generic_speculation_risk": 0.1,
                    },
                    "safe_to_reference": safe_to_reference,
                }
            ],
            "persuasion_brief": {
                "primary_angle": "improve mobile website presentation",
                "do_not_use": ["invented conversion claims"],
            },
            "supporting_evidence_ids": [evidence_id],
            "score_components": {
                "severity": 0.7,
                "evidence_confidence": 0.95,
                "business_impact": 0.7,
                "weberaise_fit": 0.95,
                "explainability": 0.9,
                "generic_speculation_risk": 0.1,
            },
            "confidence": 0.9,
            "rationale": "The issue is specific and supported by persisted technical evidence.",
        }
    )


@pytest.mark.asyncio
async def test_unsafe_contact_supporting_evidence_enters_gateway_repair_path(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'strategy-semantic-repair.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as session:
        campaign = Campaign(
            name="Strategy semantic repair fixture",
            status="ACTIVE",
            max_per_day=10,
            human_approval_required=True,
        )
        session.add(campaign)
        await session.flush()
        lead = Lead(
            campaign_id=campaign.id,
            state=LeadState.RESEARCHED.value,
            name="Safe Evidence Co",
            normalized_name="safe evidence co",
            canonical_domain="example.com",
        )
        session.add(lead)
        await session.flush()
        evidence = Evidence(
            lead_id=lead.id,
            kind="crawl_page",
            claim_class="OBSERVED_FACT",
            claim="Homepage deterministic technical facts include has_viewport=false",
            source_type="crawl_page",
            source_url="https://example.com/",
            confidence=1.0,
        )
        session.add(evidence)
        session.add(
            Contact(
                lead_id=lead.id,
                email="sales@example.com",
                normalized_email="sales@example.com",
                contact_type="business",
                state="VERIFIED",
                source_url="https://example.com/contact",
                confidence=1.0,
            )
        )
        session.add(
            ResearchReport(
                lead_id=lead.id,
                status="COMPLETE",
                dossier_json=json.dumps(
                    {
                        "business": {"name": "Safe Evidence Co"},
                        "website_findings": [
                            {
                                "text": "Homepage lacks a viewport signal.",
                                "evidence_ids": [evidence.id],
                            }
                        ],
                        "outcome": "COMPLETE",
                    }
                ),
                confidence=0.9,
                prompt_version="researcher:v1",
                model_id="fake-research-1",
            )
        )
        await session.commit()

        provider = FakeProvider(
            [
                _contact_payload(evidence_id=evidence.id, safe_to_reference=False),
                _contact_payload(evidence_id=evidence.id, safe_to_reference=True),
            ]
        )
        gateway = LLMGateway(
            providers={"fake": provider},
            task_routes={"strategist": "fake"},
        )

        output = await StrategyService(session, gateway=gateway).strategize(lead_id=lead.id)

        assert output.decision == "CONTACT"
        assert output.candidates[0].safe_to_reference is True
        assert output.supporting_evidence_ids == [evidence.id]
        assert len(provider.calls) == 2
        assert "safe-to-reference" in provider.calls[1]["system"].casefold() or "validation" in provider.calls[1]["user"].casefold()
        await session.refresh(lead)
        assert lead.state == LeadState.CONTACTABLE.value

    await engine.dispose()
