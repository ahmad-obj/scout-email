import json

import pytest

from scout_email.common.enums import LeadState, WebsiteState
from scout_email.db.base import Base
from scout_email.db.models import Campaign, Lead, LeadSource
from scout_email.db.session import create_engine_and_sessionmaker
from scout_email.enrichment.website import WebsiteVerification
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


@pytest.mark.asyncio
async def test_worker_verification_falls_back_to_www_http_for_canonical_domain(monkeypatch, tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'homepage-variants.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as session:
        campaign = Campaign(
            name="Homepage variants fixture",
            status="ACTIVE",
            target_leads=1,
            max_per_day=10,
            human_approval_required=True,
        )
        session.add(campaign)
        await session.flush()
        lead = Lead(
            campaign_id=campaign.id,
            state=LeadState.DISCOVERED.value,
            name="Legacy Public Site",
            normalized_name="legacy public site",
            canonical_domain="pnwx.com",
        )
        session.add(lead)
        await session.commit()

        calls: list[str] = []

        async def fake_verify(url: str | None, **_kwargs):
            assert url is not None
            calls.append(url)
            if url == "http://www.pnwx.com/":
                return WebsiteVerification(
                    state=WebsiteState.LIVE,
                    requested_url=url,
                    final_url=url,
                    canonical_domain="pnwx.com",
                    http_status=200,
                )
            return WebsiteVerification(
                state=WebsiteState.UNCERTAIN,
                requested_url=url,
                final_url=url,
                canonical_domain="pnwx.com",
                error_code="NETWORK_ERROR",
            )

        monkeypatch.setattr(runtime, "verify_website", fake_verify)

        result = await runtime._verify_lead_website(session, lead)

        assert result.state == WebsiteState.LIVE
        assert result.final_url == "http://www.pnwx.com/"
        assert calls == [
            "https://pnwx.com/",
            "https://www.pnwx.com/",
            "http://pnwx.com/",
            "http://www.pnwx.com/",
        ]

    await engine.dispose()


@pytest.mark.asyncio
async def test_mark_research_pending_promotes_discovered_through_qualified(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'research-pending-promotion.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as session:
        campaign = Campaign(
            name="Manual lead pipeline fixture",
            status="ACTIVE",
            target_leads=1,
            max_per_day=10,
            human_approval_required=True,
        )
        session.add(campaign)
        await session.flush()
        lead = Lead(
            campaign_id=campaign.id,
            state=LeadState.DISCOVERED.value,
            name="Manual Business",
            normalized_name="manual business",
            canonical_domain="manual.example",
        )
        session.add(lead)
        await session.commit()

        await runtime._mark_research_pending(session, lead)
        await session.refresh(lead)

        assert lead.state == LeadState.RESEARCH_PENDING.value

    await engine.dispose()
