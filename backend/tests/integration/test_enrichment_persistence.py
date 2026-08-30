import pytest
from sqlalchemy import func, select

from scout_email.common.enums import WebsiteState
from scout_email.db.base import Base
from scout_email.db.models import Campaign, Contact, Lead, SocialProfile, Website
from scout_email.db.session import create_engine_and_sessionmaker
from scout_email.enrichment.service import EnrichmentService, PublicPage
from scout_email.enrichment.website import WebsiteVerification


@pytest.mark.asyncio
async def test_enrichment_persists_provenance_idempotently(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'enrichment.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as session:
        campaign = Campaign(name="Test", status="ACTIVE", max_per_day=10, human_approval_required=True)
        session.add(campaign)
        await session.flush()
        lead = Lead(
            campaign_id=campaign.id,
            state="QUALIFIED",
            name="Acme Dental",
            normalized_name="acme dental",
            canonical_domain="example.com",
        )
        session.add(lead)
        await session.commit()

        verification = WebsiteVerification(
            state=WebsiteState.LIVE,
            requested_url="https://example.com/",
            final_url="https://example.com/",
            canonical_domain="example.com",
            http_status=200,
        )
        pages = [
            PublicPage(
                url="https://example.com/",
                html='<a href="https://instagram.com/acme">Instagram</a>',
                verified=True,
            ),
            PublicPage(
                url="https://example.com/contact",
                html='<a href="mailto:hello@example.com">Email us</a>',
                verified=True,
            ),
        ]

        service = EnrichmentService(session)
        await service.persist(lead.id, verification, pages)
        await service.persist(lead.id, verification, pages)

        assert await session.scalar(select(func.count()).select_from(Website)) == 1
        assert await session.scalar(select(func.count()).select_from(Contact)) == 1
        assert await session.scalar(select(func.count()).select_from(SocialProfile)) == 1

        contact = (await session.execute(select(Contact))).scalar_one()
        assert contact.source_url == "https://example.com/contact"
        social = (await session.execute(select(SocialProfile))).scalar_one()
        assert social.source_url == "https://example.com/"
        assert social.verified is True

    await engine.dispose()


@pytest.mark.asyncio
async def test_unverified_page_cannot_create_contact_or_social_evidence(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'unverified.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as session:
        campaign = Campaign(name="Test", status="ACTIVE", max_per_day=10, human_approval_required=True)
        session.add(campaign)
        await session.flush()
        lead = Lead(
            campaign_id=campaign.id,
            state="QUALIFIED",
            name="Acme Dental",
            normalized_name="acme dental",
        )
        session.add(lead)
        await session.commit()

        verification = WebsiteVerification(state=WebsiteState.UNCERTAIN, requested_url="https://example.com/")
        pages = [
            PublicPage(
                url="https://example.com/contact",
                html='<a href="mailto:invented-risk@example.com">Email</a><a href="https://facebook.com/acme">FB</a>',
                verified=False,
            )
        ]
        await EnrichmentService(session).persist(lead.id, verification, pages)

        assert await session.scalar(select(func.count()).select_from(Contact)) == 0
        assert await session.scalar(select(func.count()).select_from(SocialProfile)) == 0

    await engine.dispose()
