import json

import pytest

from scout_email.db.base import Base
from scout_email.db.models import Campaign, Lead, LeadSource
from scout_email.db.session import create_engine_and_sessionmaker
from scout_email.jobs import runtime


@pytest.mark.asyncio
async def test_worker_prefers_discovered_website_url_over_reconstructed_domain(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'homepage-resolution.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as session:
        campaign = Campaign(
            name="Homepage fixture",
            status="ACTIVE",
            target_leads=1,
            max_per_day=10,
            human_approval_required=True,
        )
        session.add(campaign)
        await session.flush()
        lead = Lead(
            campaign_id=campaign.id,
            state="DISCOVERED",
            name="Legacy Business",
            normalized_name="legacy business",
            canonical_domain="legacy.example",
        )
        session.add(lead)
        await session.flush()
        session.add(
            LeadSource(
                lead_id=lead.id,
                source="google_maps_browser",
                source_external_id="legacy-place",
                source_url="https://maps.google.com/?cid=legacy-place",
                raw_json=json.dumps(
                    {"website": "http://legacy.example/book-now?source=maps"}
                ),
            )
        )
        await session.commit()

        assert await runtime._lead_homepage(session, lead) == (
            "http://legacy.example/book-now?source=maps"
        )

    await engine.dispose()


@pytest.mark.asyncio
async def test_worker_falls_back_to_canonical_https_when_source_has_no_website(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'homepage-fallback.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as session:
        campaign = Campaign(
            name="Homepage fallback fixture",
            status="ACTIVE",
            target_leads=1,
            max_per_day=10,
            human_approval_required=True,
        )
        session.add(campaign)
        await session.flush()
        lead = Lead(
            campaign_id=campaign.id,
            state="DISCOVERED",
            name="Fallback Business",
            normalized_name="fallback business",
            canonical_domain="fallback.example",
        )
        session.add(lead)
        await session.commit()

        assert await runtime._lead_homepage(session, lead) == "https://fallback.example/"

    await engine.dispose()
