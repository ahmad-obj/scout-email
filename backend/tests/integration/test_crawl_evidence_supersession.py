from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from scout_email.browser.schemas import BrowserRenderResponse
from scout_email.common.enums import ClaimClass, LeadState
from scout_email.db.base import Base
from scout_email.db.models import Campaign, CrawlPage, Evidence, Lead, Website
from scout_email.db.session import create_engine_and_sessionmaker
from scout_email.evidence.service import EvidenceService


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
        for viewport, relative_path in (("desktop", desktop_path), ("mobile", mobile_path)):
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


@pytest.mark.asyncio
async def test_richer_crawl_evidence_supersedes_same_page_generic_claim_in_place(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'crawl-supersede.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as session:
        campaign = Campaign(
            name="Crawl supersession fixture",
            status="ACTIVE",
            max_per_day=10,
            human_approval_required=True,
        )
        session.add(campaign)
        await session.flush()
        lead = Lead(
            campaign_id=campaign.id,
            state=LeadState.QUALIFIED.value,
            name="Legacy Evidence Co",
            normalized_name="legacy evidence co",
            canonical_domain="example.com",
        )
        session.add(lead)
        await session.flush()
        session.add(
            Website(
                lead_id=lead.id,
                url="https://example.com/",
                canonical_domain="example.com",
                state="LIVE",
                final_url="https://example.com/",
                http_status=200,
            )
        )
        page_url = "https://example.com/products"
        session.add(
            CrawlPage(
                lead_id=lead.id,
                url=page_url,
                title="Imaging Products",
                important_text="Public page describes digital imaging products and service support.",
                http_status=200,
                extracted_json=json.dumps(
                    {
                        "technical_signals": {
                            "uses_https": True,
                            "has_viewport": True,
                            "missing_meta_description": False,
                        }
                    }
                ),
            )
        )
        stale = Evidence(
            lead_id=lead.id,
            kind="crawl_page",
            claim_class=ClaimClass.OBSERVED_FACT.value,
            claim=(
                f"Crawled page {page_url} returned HTTP 200 and stored deterministic page facts"
            ),
            source_type="crawl_page",
            source_url=page_url,
            confidence=1.0,
        )
        session.add(stale)
        await session.commit()
        stale_id = stale.id

        data_root = tmp_path / "data"
        await EvidenceService(
            session,
            data_root=data_root,
            browser_client=FakeBrowserClient(data_root),
        ).build_bundle(
            campaign_id=campaign.id,
            lead_id=lead.id,
            homepage_url="https://example.com/",
        )

        rows = list(
            (
                await session.scalars(
                    select(Evidence).where(
                        Evidence.lead_id == lead.id,
                        Evidence.kind == "crawl_page",
                        Evidence.source_type == "crawl_page",
                        Evidence.source_url == page_url,
                    )
                )
            ).all()
        )
        assert len(rows) == 1
        assert rows[0].id == stale_id
        assert "Imaging Products" in rows[0].claim
        assert "Public page describes digital imaging products" in rows[0].claim
        assert await session.scalar(
            select(func.count()).select_from(Evidence).where(
                Evidence.lead_id == lead.id,
                Evidence.kind == "crawl_page",
                Evidence.source_url == page_url,
            )
        ) == 1

    await engine.dispose()
