import pytest
from sqlalchemy import func, select

from scout_email.common.errors import DuplicateOperationError
from scout_email.db.base import Base
from scout_email.db.models import Campaign, Lead, LeadScore, LeadSource
from scout_email.db.session import create_engine_and_sessionmaker
from scout_email.leads.schemas import LeadSourceInput, RawLead
from scout_email.leads.service import LeadIngestService


@pytest.mark.asyncio
async def test_repeated_source_identity_is_idempotent(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'leads.db'}"
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with factory() as session:
        campaign = Campaign(name="Lahore Dentists", status="ACTIVE")
        session.add(campaign)
        await session.commit()

        service = LeadIngestService(session)
        raw = RawLead(
            name="ABC Dental",
            city="Lahore",
            phone="+92 300 1234567",
            website="https://abc.pk",
            rating=4.5,
            review_count=50,
        )
        source = LeadSourceInput(
            source="google_maps_browser",
            source_external_id="place-123",
            source_query="dentist Lahore",
        )

        first = await service.ingest(campaign.id, raw, source)
        await session.commit()
        second = await service.ingest(campaign.id, raw, source)
        await session.commit()

        assert first.lead_id == second.lead_id
        assert second.created is False
        assert await session.scalar(select(func.count()).select_from(Lead)) == 1
        assert await session.scalar(select(func.count()).select_from(LeadSource)) == 1
        assert await session.scalar(select(func.count()).select_from(LeadScore)) == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_source_identity_from_other_campaign_is_blocked(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'cross-campaign.db'}"
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with factory() as session:
        first_campaign = Campaign(name="Campaign A", status="ACTIVE")
        second_campaign = Campaign(name="Campaign B", status="ACTIVE")
        session.add_all([first_campaign, second_campaign])
        await session.commit()

        service = LeadIngestService(session)
        raw = RawLead(name="ABC Dental", phone="+92 300 1234567")
        source = LeadSourceInput(
            source="google_maps_browser",
            source_external_id="place-123",
        )
        await service.ingest(first_campaign.id, raw, source)
        await session.commit()

        with pytest.raises(DuplicateOperationError):
            await service.ingest(second_campaign.id, raw, source)
        await session.rollback()

    await engine.dispose()
