import json

import pytest
from sqlalchemy import func, select

from scout_email.crawl.persistence import CrawlPersistenceService
from scout_email.crawl.site import CrawledPage, SiteCrawlResult
from scout_email.db.base import Base
from scout_email.db.models import Campaign, CrawlPage, Lead
from scout_email.db.session import create_engine_and_sessionmaker


@pytest.mark.asyncio
async def test_crawl_result_persists_structured_pages_idempotently(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'crawl.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as session:
        campaign = Campaign(
            name="Test",
            status="ACTIVE",
            max_per_day=10,
            human_approval_required=True,
        )
        session.add(campaign)
        await session.flush()
        lead = Lead(
            campaign_id=campaign.id,
            state="RESEARCHING",
            name="Acme Dental",
            normalized_name="acme dental",
            canonical_domain="example.com",
        )
        session.add(lead)
        await session.commit()

        result = SiteCrawlResult(
            start_url="https://example.com/",
            pages=[
                CrawledPage(
                    url="https://example.com/",
                    http_status=200,
                    title="Acme Dental",
                    headings=["Acme Dental"],
                    important_text="Dental care for Lahore families.",
                    calls_to_action=["Book appointment"],
                    forms=[],
                    links=["https://example.com/services"],
                    technical_signals={"has_viewport": True},
                ),
                CrawledPage(
                    url="https://example.com/services",
                    http_status=200,
                    title="Services",
                    headings=["Dental implants"],
                    important_text="Dental implants and cosmetic dentistry.",
                    calls_to_action=["Request consultation"],
                    forms=[],
                    links=[],
                    technical_signals={"has_viewport": False},
                ),
            ],
            browser_fallback_urls=["https://example.com/services"],
            skipped_urls={},
        )

        service = CrawlPersistenceService(session)
        await service.persist(lead.id, result)
        await service.persist(lead.id, result)

        assert await session.scalar(select(func.count()).select_from(CrawlPage)) == 2
        rows = (
            await session.execute(select(CrawlPage).order_by(CrawlPage.url))
        ).scalars().all()

        homepage = next(row for row in rows if row.url == "https://example.com/")
        assert homepage.http_status == 200
        assert homepage.title == "Acme Dental"
        assert homepage.important_text == "Dental care for Lahore families."
        homepage_data = json.loads(homepage.extracted_json)
        assert homepage_data["headings"] == ["Acme Dental"]
        assert homepage_data["browser_fallback_required"] is False

        services = next(row for row in rows if row.url.endswith("/services"))
        services_data = json.loads(services.extracted_json)
        assert services_data["calls_to_action"] == ["Request consultation"]
        assert services_data["technical_signals"]["has_viewport"] is False
        assert services_data["browser_fallback_required"] is True

    await engine.dispose()
