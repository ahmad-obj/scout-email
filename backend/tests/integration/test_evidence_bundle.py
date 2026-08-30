import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from scout_email.browser.schemas import BrowserRenderResponse
from scout_email.common.enums import ClaimClass
from scout_email.db.base import Base
from scout_email.db.models import Campaign, Contact, CrawlPage, Evidence, Lead, Screenshot, Website
from scout_email.db.session import create_engine_and_sessionmaker
from scout_email.evidence.provenance import assert_claim_supported
from scout_email.evidence.service import EvidenceService


class FakeBrowserClient:
    def __init__(self, artifact_root: Path) -> None:
        self.artifact_root = artifact_root
        self.calls: list[tuple[str, str, str | None]] = []

    async def render(self, url: str, *, viewport: str = "desktop", screenshot_path: str | None = None):
        self.calls.append((url, viewport, screenshot_path))
        assert screenshot_path is not None
        relative = Path(screenshot_path)
        assert not relative.is_absolute()
        assert ".." not in relative.parts
        path = self.artifact_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-png")
        return BrowserRenderResponse(
            final_url=url,
            title="Acme Dental",
            html="<html><body><h1>Acme Dental</h1></body></html>",
            screenshot_path=str(path),
        )

    async def capture_homepage_screenshots(
        self,
        url: str,
        *,
        desktop_path: str,
        mobile_path: str,
    ):
        return [
            await self.render(url, viewport="desktop", screenshot_path=desktop_path),
            await self.render(url, viewport="mobile", screenshot_path=mobile_path),
        ]


@pytest.mark.asyncio
async def test_build_bundle_persists_verified_facts_and_two_scoped_screenshots(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'evidence.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as session:
        campaign = Campaign(
            name="Lahore Dentists",
            status="ACTIVE",
            max_per_day=10,
            human_approval_required=True,
        )
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
        session.add(
            Contact(
                lead_id=lead.id,
                email="hello@example.com",
                normalized_email="hello@example.com",
                contact_type="business",
                state="VERIFIED",
                source_url="https://example.com/contact",
                confidence=1.0,
            )
        )
        session.add(
            CrawlPage(
                lead_id=lead.id,
                url="https://example.com/",
                title="Acme Dental",
                important_text="Family and cosmetic dental care in Lahore.",
                http_status=200,
                extracted_json=json.dumps(
                    {
                        "technical_signals": {
                            "uses_https": True,
                            "title_present": True,
                            "has_viewport": True,
                            "cta_count": 2,
                        }
                    }
                ),
            )
        )
        await session.commit()

        data_root = tmp_path / "data"
        browser = FakeBrowserClient(data_root)
        service = EvidenceService(session, data_root=data_root, browser_client=browser)
        bundle = await service.build_bundle(
            campaign_id=campaign.id,
            lead_id=lead.id,
            homepage_url="https://example.com/",
        )

        assert [call[1] for call in browser.calls] == ["desktop", "mobile"]
        assert len(bundle.screenshots) == 2
        assert {item.viewport for item in bundle.screenshots} == {"desktop", "mobile"}
        assert len(bundle.evidence) >= 5
        assert {item.kind for item in bundle.evidence} >= {
            "website_verification",
            "contact",
            "crawl_page",
            "screenshot",
        }

        for shot in bundle.screenshots:
            relative = Path(shot.artifact_path)
            assert not relative.is_absolute()
            assert ".." not in relative.parts
            assert relative.parts[:5] == (
                "campaigns",
                str(campaign.id),
                "leads",
                str(lead.id),
                "screenshots",
            )
            assert (data_root / relative).exists()

        for item in bundle.evidence:
            assert item.id > 0
            assert item.claim_class == ClaimClass.OBSERVED_FACT
            assert_claim_supported([item.id], item.claim_class)

        contact_evidence = next(item for item in bundle.evidence if item.kind == "contact")
        assert contact_evidence.source_url == "https://example.com/contact"
        assert "hello@example.com" in contact_evidence.claim

        assert await session.scalar(select(func.count()).select_from(Screenshot)) == 2
        evidence_count = await session.scalar(select(func.count()).select_from(Evidence))
        assert evidence_count == len(bundle.evidence)

        first_ids = [item.id for item in bundle.evidence]
        second = await service.build_bundle(
            campaign_id=campaign.id,
            lead_id=lead.id,
            homepage_url="https://example.com/",
        )
        assert [item.id for item in second.evidence] == first_ids
        assert await session.scalar(select(func.count()).select_from(Screenshot)) == 2
        assert await session.scalar(select(func.count()).select_from(Evidence)) == evidence_count

    await engine.dispose()
