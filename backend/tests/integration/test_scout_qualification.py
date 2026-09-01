from __future__ import annotations

import pytest
from sqlalchemy import select

from scout_email.browser.schemas import BrowserMapLead
from scout_email.campaigns.schemas import CampaignCreate, QualificationPolicy
from scout_email.campaigns.service import CampaignService
from scout_email.common.enums import LeadState
from scout_email.db.base import Base
from scout_email.db.models import CampaignSearch, Lead
from scout_email.db.session import create_engine_and_sessionmaker
from scout_email.scout.schemas import ScoutSearchJobPayload
from scout_email.scout.service import ScoutService


class QualificationBrowser:
    async def search_maps(self, query: str, max_results: int):
        assert query == "dentist in Lahore"
        assert max_results == 2
        return [
            BrowserMapLead(
                name="Qualified Dental",
                category="Dentist",
                address="Lahore",
                website="https://qualified.example",
                rating=4.6,
                review_count=80,
                maps_url="https://maps.google.com/?cid=qualified",
                source_external_id="qualified-place",
            ),
            BrowserMapLead(
                name="Low Rating Dental",
                category="Dentist",
                address="Lahore",
                website="https://low-rating.example",
                rating=3.2,
                review_count=55,
                maps_url="https://maps.google.com/?cid=low-rating",
                source_external_id="low-rating-place",
            ),
        ]


@pytest.mark.asyncio
async def test_scout_applies_campaign_rating_policy_and_returns_qualified_ids(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'qualification.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as session:
        campaign = await CampaignService(session).create(
            CampaignCreate(
                name="Qualified Lahore dentists",
                searches=["dentist"],
                locations=["Lahore"],
                target_leads=2,
                qualification=QualificationPolicy(
                    minimum_rating=4.0,
                    exclude_chains=False,
                ),
            )
        )
        search = await session.scalar(
            select(CampaignSearch).where(CampaignSearch.campaign_id == campaign.id)
        )
        assert search is not None

        result = await ScoutService(session, QualificationBrowser()).run_search(
            ScoutSearchJobPayload(
                campaign_id=campaign.id,
                campaign_search_id=search.id,
                query="dentist in Lahore",
                search_term="dentist",
                location="Lahore",
                max_results=2,
            )
        )

        leads = list(
            (
                await session.scalars(
                    select(Lead).where(Lead.campaign_id == campaign.id).order_by(Lead.name)
                )
            ).all()
        )
        by_name = {lead.name: lead for lead in leads}
        assert by_name["Qualified Dental"].state == LeadState.QUALIFIED.value
        assert by_name["Low Rating Dental"].state == LeadState.LOW_PRIORITY.value
        assert result["qualified_lead_ids"] == [by_name["Qualified Dental"].id]
        assert result["low_priority_lead_ids"] == [by_name["Low Rating Dental"].id]

    await engine.dispose()
