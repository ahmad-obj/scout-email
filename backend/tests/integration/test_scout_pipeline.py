import json

import pytest
from sqlalchemy import func, select

from scout_email.browser.schemas import BrowserMapLead
from scout_email.campaigns.models import CampaignPolicy  # noqa: F401
from scout_email.common.errors import InvalidStateTransitionError
from scout_email.db.base import Base
from scout_email.db.models import Campaign, CampaignSearch, Lead, LeadScore, LeadSource
from scout_email.db.session import create_engine_and_sessionmaker
from scout_email.scout.models import LeadSourceQuery
from scout_email.scout.schemas import ScoutSearchJobPayload
from scout_email.scout.service import ScoutService


class FakeBrowser:
    async def search_maps(self, query: str, max_results: int):
        return [
            BrowserMapLead(
                name="ABC Dental",
                category="Dentist",
                address="Main Road",
                phone="+92 300 1234567",
                website="https://abc.pk",
                rating=4.6,
                review_count=120,
                maps_url="https://maps.google.com/x",
                source_external_id="place-123",
            )
        ][:max_results]


class FakeBrowserNoExternalId:
    async def search_maps(self, query: str, max_results: int):
        return [
            BrowserMapLead(
                name="No ID Dental",
                phone="+92 311 7654321",
                website="https://noid.example",
                maps_url="https://maps.google.com/no-id",
            )
        ][:max_results]


async def make_campaign(session, *, status: str = "ACTIVE", target: int = 10):
    campaign = Campaign(
        name="Lahore Dentists",
        status=status,
        target_leads=target,
        max_per_day=10,
        human_approval_required=True,
    )
    session.add(campaign)
    await session.flush()
    first = CampaignSearch(
        campaign_id=campaign.id,
        search_term="dentist",
        location="Lahore",
    )
    second = CampaignSearch(
        campaign_id=campaign.id,
        search_term="dental clinic",
        location="Lahore",
    )
    session.add_all([first, second])
    await session.commit()
    return campaign, first, second


@pytest.mark.asyncio
async def test_two_queries_dedupe_lead_but_preserve_query_provenance(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'scout.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as session:
        campaign, first, second = await make_campaign(session)
        service = ScoutService(session, FakeBrowser())
        await service.run_search(
            ScoutSearchJobPayload(
                campaign_id=campaign.id,
                campaign_search_id=first.id,
                query="dentist in Lahore",
                search_term="dentist",
                location="Lahore",
                max_results=10,
            )
        )
        await service.run_search(
            ScoutSearchJobPayload(
                campaign_id=campaign.id,
                campaign_search_id=second.id,
                query="dental clinic in Lahore",
                search_term="dental clinic",
                location="Lahore",
                max_results=10,
            )
        )

        assert await session.scalar(select(func.count()).select_from(Lead)) == 1
        assert await session.scalar(select(func.count()).select_from(LeadSource)) == 1
        assert await session.scalar(select(func.count()).select_from(LeadSourceQuery)) == 2
        assert await session.scalar(select(func.count()).select_from(LeadScore)) == 1

        score = (await session.execute(select(LeadScore))).scalar_one()
        assert score.total == sum(json.loads(score.components_json).values())
    await engine.dispose()


@pytest.mark.asyncio
async def test_repeat_same_query_is_idempotent_even_without_maps_external_id(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'scout-no-id.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as session:
        campaign, first, _ = await make_campaign(session)
        service = ScoutService(session, FakeBrowserNoExternalId())
        payload = ScoutSearchJobPayload(
            campaign_id=campaign.id,
            campaign_search_id=first.id,
            query="dentist in Lahore",
            search_term="dentist",
            location="Lahore",
            max_results=10,
        )
        await service.run_search(payload)
        await service.run_search(payload)

        assert await session.scalar(select(func.count()).select_from(Lead)) == 1
        assert await session.scalar(select(func.count()).select_from(LeadSource)) == 1
        assert await session.scalar(select(func.count()).select_from(LeadSourceQuery)) == 1
        source = (await session.execute(select(LeadSource))).scalar_one()
        assert source.source_external_id is not None
        assert "maps:" in source.source_external_id
    await engine.dispose()


@pytest.mark.asyncio
async def test_paused_campaign_cannot_enqueue_scout_jobs(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'paused.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as session:
        campaign, _, _ = await make_campaign(session, status="PAUSED")
        with pytest.raises(InvalidStateTransitionError):
            await ScoutService(session).enqueue_campaign(campaign.id)
    await engine.dispose()


@pytest.mark.asyncio
async def test_target_reached_does_not_enqueue_more_scout_jobs(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'target.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as session:
        campaign, _, _ = await make_campaign(session, target=1)
        session.add(
            Lead(
                campaign_id=campaign.id,
                state="DISCOVERED",
                name="Existing Lead",
                normalized_name="existing lead",
            )
        )
        await session.commit()
        result = await ScoutService(session).enqueue_campaign(campaign.id)
        assert result.job_ids == []
    await engine.dispose()
