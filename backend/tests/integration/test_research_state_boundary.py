from __future__ import annotations

from types import SimpleNamespace

import pytest

from scout_email.common.enums import LeadState, WebsiteState
from scout_email.common.errors import InvalidStateTransitionError
from scout_email.crawl.site import SiteCrawlResult
from scout_email.db.base import Base
from scout_email.db.models import Campaign, Evidence, Lead, Website
from scout_email.db.session import create_engine_and_sessionmaker
from scout_email.research.service import ResearchService


class NoopBrowser:
    async def render(self, url: str, **_kwargs):  # pragma: no cover - empty crawl has no pages
        raise AssertionError(f"unexpected render: {url}")


class ResearchGateway:
    async def generate(self, *, task, context, response_model, prompt_version):
        assert task == "researcher"
        evidence_id = int(context["evidence"][0]["id"])
        output = response_model.model_validate(
            {
                "business": {
                    "name": "Boundary Dental",
                    "summary": "Local dental clinic.",
                    "category": "Dentist",
                    "location": "Lahore",
                },
                "business_model": {
                    "target_customers": ["local patients"],
                    "offerings": ["dental services"],
                    "primary_conversion": "appointment booking",
                },
                "presence": {"website_state": "LIVE", "social_profiles": []},
                "strengths": [
                    {
                        "text": "A public website was verified.",
                        "evidence_ids": [evidence_id],
                    }
                ],
                "website_findings": [],
                "technical_findings": [],
                "contact": None,
                "confidence": 0.8,
                "outcome": "COMPLETE",
            }
        )
        return SimpleNamespace(
            output=output,
            metadata=SimpleNamespace(model="fixture-research-model"),
        )


@pytest.mark.asyncio
async def test_crawl_evidence_hands_qualified_lead_to_research_pending(monkeypatch, tmp_path):
    from scout_email.jobs import runtime

    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'crawl-boundary.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as session:
        campaign = Campaign(
            name="Boundary fixture",
            status="ACTIVE",
            target_leads=1,
            max_per_day=10,
            human_approval_required=True,
        )
        session.add(campaign)
        await session.flush()
        lead = Lead(
            campaign_id=campaign.id,
            state=LeadState.QUALIFIED.value,
            name="Boundary Dental",
            normalized_name="boundary dental",
            category="Dentist",
            city="Lahore",
            canonical_domain="boundary.example",
        )
        session.add(lead)
        await session.flush()
        session.add(
            Website(
                lead_id=lead.id,
                state=WebsiteState.LIVE.value,
                url="https://boundary.example/",
                final_url="https://boundary.example/",
                canonical_domain="boundary.example",
                http_status=200,
            )
        )
        await session.commit()
        lead_id = lead.id

    async def fake_crawl(url: str, **_kwargs):
        return SiteCrawlResult(
            start_url=url,
            pages=[],
            browser_fallback_urls=[],
            skipped_urls={},
        )

    class FakeEvidenceService:
        def __init__(self, *_args, **_kwargs):
            pass

        async def build_bundle(self, **_kwargs):
            return SimpleNamespace(evidence=[], screenshots=[])

    monkeypatch.setattr(runtime, "crawl_site", fake_crawl)
    monkeypatch.setattr(runtime, "EvidenceService", FakeEvidenceService)

    async with factory() as session:
        handlers = runtime.build_handlers(
            session,
            browser=NoopBrowser(),
            gateway=None,
            playbook=None,
            data_root=tmp_path,
        )
        result = await handlers["CRAWL_EVIDENCE"]({"lead_id": lead_id})
        assert result["status"] == "COMPLETE"
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        assert lead.state == LeadState.RESEARCH_PENDING.value

    await engine.dispose()


@pytest.mark.asyncio
async def test_research_refuses_to_skip_research_pending_state(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'research-boundary.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as session:
        campaign = Campaign(
            name="Research state fixture",
            status="ACTIVE",
            target_leads=1,
            max_per_day=10,
            human_approval_required=True,
        )
        session.add(campaign)
        await session.flush()
        lead = Lead(
            campaign_id=campaign.id,
            state=LeadState.QUALIFIED.value,
            name="Boundary Dental",
            normalized_name="boundary dental",
            category="Dentist",
            city="Lahore",
        )
        session.add(lead)
        await session.flush()
        session.add(
            Evidence(
                lead_id=lead.id,
                kind="website_verification",
                claim_class="OBSERVED_FACT",
                claim="Website state is LIVE",
                source_type="website_verification",
                source_url="https://boundary.example/",
                confidence=1.0,
            )
        )
        await session.commit()
        lead_id = lead.id

        with pytest.raises(InvalidStateTransitionError):
            await ResearchService(session, gateway=ResearchGateway()).research(lead_id=lead_id)

        lead = await session.get(Lead, lead_id)
        assert lead is not None
        assert lead.state == LeadState.QUALIFIED.value

    await engine.dispose()
