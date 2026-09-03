from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from scout_email.browser.schemas import BrowserRenderResponse
from scout_email.common.enums import LeadState
from scout_email.db.base import Base
from scout_email.db.models import Campaign, CrawlPage, Evidence, Lead, ResearchReport, Website
from scout_email.db.session import create_engine_and_sessionmaker
from scout_email.evidence.service import EvidenceService
from scout_email.llm.gateway import LLMGateway
from scout_email.llm.prompts import build_system_prompt
from scout_email.llm.schemas import ProviderResult
from scout_email.research.service import ResearchService


class FakeBrowserClient:
    def __init__(self, artifact_root: Path) -> None:
        self.artifact_root = artifact_root

    async def capture_homepage_screenshots(
        self,
        url: str,
        *,
        desktop_path: str,
        mobile_path: str,
    ):
        results = []
        for viewport, relative_path in (
            ("desktop", desktop_path),
            ("mobile", mobile_path),
        ):
            path = self.artifact_root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fake-png")
            results.append(
                BrowserRenderResponse(
                    final_url=url,
                    title="Example",
                    html="<html><body>Example</body></html>",
                    screenshot_path=str(path),
                )
            )
        return results


class FakeProvider:
    name = "fake"
    model = "fake-intelligence-1"

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
        f"sqlite+aiosqlite:///{tmp_path / 'quality.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, factory


@pytest.mark.asyncio
async def test_crawl_evidence_preserves_bounded_page_content_and_technical_facts(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        campaign = Campaign(
            name="Evidence quality fixture",
            status="ACTIVE",
            max_per_day=10,
            human_approval_required=True,
        )
        session.add(campaign)
        await session.flush()
        lead = Lead(
            campaign_id=campaign.id,
            state=LeadState.QUALIFIED.value,
            name="Northwest Imaging",
            normalized_name="northwest imaging",
            canonical_domain="example.com",
        )
        session.add(lead)
        await session.flush()
        session.add(
            Website(
                lead_id=lead.id,
                url="http://www.example.com/",
                canonical_domain="example.com",
                state="LIVE",
                final_url="http://www.example.com/",
                http_status=200,
            )
        )
        session.add(
            CrawlPage(
                lead_id=lead.id,
                url="http://www.example.com/products",
                title="Digital X-Ray Products",
                important_text=(
                    "We supply digital X-ray equipment, imaging accessories, and service support "
                    "to clinics and medical imaging teams across the Pacific Northwest."
                ),
                http_status=200,
                extracted_json=json.dumps(
                    {
                        "headings": ["Digital X-Ray Products"],
                        "calls_to_action": ["Contact Sales"],
                        "technical_signals": {
                            "uses_https": False,
                            "title_present": True,
                            "missing_meta_description": True,
                            "has_viewport": False,
                            "has_responsive_indicators": False,
                            "has_open_graph": False,
                            "has_structured_data": False,
                            "cta_count": 1,
                            "image_count": 4,
                            "declared_image_dimension_count": 0,
                        },
                    }
                ),
            )
        )
        await session.commit()

        data_root = tmp_path / "data"
        bundle = await EvidenceService(
            session,
            data_root=data_root,
            browser_client=FakeBrowserClient(data_root),
        ).build_bundle(
            campaign_id=campaign.id,
            lead_id=lead.id,
            homepage_url="http://www.example.com/",
        )

        page_evidence = next(item for item in bundle.evidence if item.kind == "crawl_page")
        assert "Digital X-Ray Products" in page_evidence.claim
        assert "We supply digital X-ray equipment" in page_evidence.claim
        assert "uses_https=false" in page_evidence.claim
        assert "has_viewport=false" in page_evidence.claim
        assert "missing_meta_description=true" in page_evidence.claim
        assert "HTTP 200" in page_evidence.claim
        assert len(page_evidence.claim) <= 1_500

    await engine.dispose()


@pytest.mark.asyncio
async def test_empty_complete_research_is_repaired_to_research_more(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        campaign = Campaign(
            name="Research quality fixture",
            status="ACTIVE",
            max_per_day=10,
            human_approval_required=True,
        )
        session.add(campaign)
        await session.flush()
        lead = Lead(
            campaign_id=campaign.id,
            state=LeadState.RESEARCH_PENDING.value,
            name="Sparse Research Co",
            normalized_name="sparse research co",
            canonical_domain="example.com",
        )
        session.add(lead)
        await session.flush()
        evidence = Evidence(
            lead_id=lead.id,
            kind="crawl_page",
            claim_class="OBSERVED_FACT",
            claim="Homepage exposes a public product catalog and deterministic technical facts",
            source_type="crawl_page",
            source_url="https://example.com/",
            confidence=1.0,
        )
        session.add(evidence)
        await session.commit()

        empty_complete = {
            "business": {
                "name": "Sparse Research Co",
                "summary": "",
                "category": None,
                "location": None,
            },
            "business_model": {
                "target_customers": [],
                "offerings": [],
                "primary_conversion": None,
            },
            "presence": {"website_state": "LIVE", "social_profiles": []},
            "strengths": [],
            "website_findings": [],
            "technical_findings": [],
            "contact": None,
            "confidence": 1.0,
            "outcome": "COMPLETE",
        }
        repaired = dict(empty_complete)
        repaired["confidence"] = 0.5
        repaired["outcome"] = "RESEARCH_MORE"

        provider = FakeProvider([json.dumps(empty_complete), json.dumps(repaired)])
        gateway = LLMGateway(
            providers={"fake": provider},
            task_routes={"researcher": "fake"},
        )
        output = await ResearchService(session, gateway=gateway).research(lead_id=lead.id)

        assert output.outcome == "RESEARCH_MORE"
        assert len(provider.calls) == 2
        assert "Schema repair attempt" in provider.calls[1]["system"]
        await session.refresh(lead)
        assert lead.state == LeadState.RESEARCH_PENDING.value
        assert await session.scalar(select(func.count()).select_from(ResearchReport)) == 1
        report = await session.scalar(select(ResearchReport).where(ResearchReport.lead_id == lead.id))
        assert report is not None
        assert report.status == "RESEARCH_MORE"

    await engine.dispose()


def test_research_and_strategy_system_prompts_define_task_semantics():
    researcher = build_system_prompt(task="researcher", prompt_version="researcher:v1")
    strategist = build_system_prompt(task="strategist", prompt_version="strategist:v1")

    assert "evidence" in researcher.casefold()
    assert "evidence id" in researcher.casefold()
    assert "research_more" in researcher.casefold()
    assert "do not invent" in researcher.casefold()

    assert "outreach" in strategist.casefold()
    assert "contact" in strategist.casefold()
    assert "research_more" in strategist.casefold()
    assert "do not enrich" in strategist.casefold()
