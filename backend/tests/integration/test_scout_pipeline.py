import pytest
from sqlalchemy import func, select

from scout_email.browser.schemas import BrowserMapLead
from scout_email.campaigns.models import CampaignPolicy  # noqa: F401
from scout_email.db.base import Base
from scout_email.db.models import Campaign, CampaignSearch, Lead, LeadScore
from scout_email.db.session import create_engine_and_sessionmaker
from scout_email.scout.models import LeadSourceQuery
from scout_email.scout.schemas import ScoutSearchJobPayload
from scout_email.scout.service import ScoutService


class FakeBrowser:
    async def search_maps(self, query: str, max_results: int):
        return [BrowserMapLead(name="ABC Dental", category="Dentist", address="Main Road", phone="+92 300 1234567", website="https://abc.pk", rating=4.6, review_count=120, maps_url="https://maps.google.com/x", source_external_id="place-123")]


@pytest.mark.asyncio
async def test_two_queries_dedupe_lead_but_preserve_query_provenance(tmp_path):
    engine, factory = create_engine_and_sessionmaker(f"sqlite+aiosqlite:///{tmp_path / 'scout.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as session:
        campaign = Campaign(name="Lahore Dentists", status="ACTIVE", target_leads=10, max_per_day=10, human_approval_required=True)
        session.add(campaign)
        await session.flush()
        first = CampaignSearch(campaign_id=campaign.id, search_term="dentist", location="Lahore")
        second = CampaignSearch(campaign_id=campaign.id, search_term="dental clinic", location="Lahore")
        session.add_all([first, second])
        await session.commit()
        service = ScoutService(session, FakeBrowser())
        await service.run_search(ScoutSearchJobPayload(campaign_id=campaign.id, campaign_search_id=first.id, query="dentist in Lahore", search_term="dentist", location="Lahore", max_results=10))
        await service.run_search(ScoutSearchJobPayload(campaign_id=campaign.id, campaign_search_id=second.id, query="dental clinic in Lahore", search_term="dental clinic", location="Lahore", max_results=10))
        assert await session.scalar(select(func.count()).select_from(Lead)) == 1
        assert await session.scalar(select(func.count()).select_from(LeadSourceQuery)) == 2
        score = (await session.execute(select(LeadScore))).scalar_one()
        assert score.total == sum(__import__('json').loads(score.components_json).values())
    await engine.dispose()
