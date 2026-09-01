from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from scout_email.browser.schemas import BrowserRenderResponse
from scout_email.common.enums import LeadState, WebsiteState
from scout_email.crawl.site import CrawledPage, SiteCrawlResult
from scout_email.db.base import Base
from scout_email.db.models import Campaign, Contact, EmailDraft, Job, Lead
from scout_email.db.session import create_engine_and_sessionmaker
from scout_email.enrichment.website import WebsiteVerification
from scout_email.jobs.service import JobService
from scout_email.writing.playbook import load_playbook


PLAYBOOK_DIR = Path(__file__).resolve().parents[3] / "config" / "weberaise"


class FixtureBrowser:
    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root

    async def render(self, url: str, *, viewport="desktop", screenshot_path=None):
        html = (
            "<html><body><h1>Contact</h1>"
            "<a href='mailto:hello@worker-dental.example'>hello@worker-dental.example</a>"
            "</body></html>"
            if "/contact" in url
            else "<html><body><h1>Worker Dental</h1><a href='/contact'>Contact</a>"
            "<a href='/book'>Book appointment</a></body></html>"
        )
        stored = None
        if screenshot_path is not None:
            relative = Path(screenshot_path)
            assert not relative.is_absolute()
            assert ".." not in relative.parts
            target = self.data_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(f"fixture-{viewport}".encode())
            stored = str(target)
        return BrowserRenderResponse(
            final_url=url,
            title="Worker Dental",
            html=html,
            screenshot_path=stored,
        )

    async def capture_homepage_screenshots(
        self, url: str, *, desktop_path: str, mobile_path: str
    ):
        return [
            await self.render(url, viewport="desktop", screenshot_path=desktop_path),
            await self.render(url, viewport="mobile", screenshot_path=mobile_path),
        ]


class FixtureGateway:
    async def generate(self, *, task, context, response_model, prompt_version):
        if task == "researcher":
            evidence_id = int(context["evidence"][0]["id"])
            contact_id = int(context["verified_contacts"][0]["contact_id"])
            payload = {
                "business": {
                    "name": "Worker Dental",
                    "summary": "A local dental clinic with a public website.",
                    "category": "Dentist",
                    "location": "Lahore",
                },
                "business_model": {
                    "target_customers": ["local patients"],
                    "offerings": ["dental services"],
                    "primary_conversion": "book appointment",
                },
                "presence": {"website_state": "LIVE", "social_profiles": []},
                "strengths": [
                    {
                        "text": "The clinic has a public website.",
                        "evidence_ids": [evidence_id],
                    }
                ],
                "website_findings": [
                    {
                        "text": "The booking path can be made more prominent.",
                        "evidence_ids": [evidence_id],
                    }
                ],
                "technical_findings": [],
                "contact": {"contact_id": contact_id},
                "confidence": 0.92,
                "outcome": "COMPLETE",
            }
        elif task == "strategist":
            evidence_id = int(context["evidence"][0]["id"])
            payload = {
                "decision": "CONTACT",
                "candidates": [
                    {
                        "problem": "The booking action is not prominent.",
                        "angle": "Reduce booking friction.",
                        "evidence_ids": [evidence_id],
                        "score": {
                            "severity": 0.7,
                            "evidence_confidence": 0.95,
                            "business_impact": 0.8,
                            "weberaise_fit": 0.95,
                            "explainability": 0.9,
                            "generic_speculation_risk": 0.1,
                        },
                        "safe_to_reference": True,
                    }
                ],
                "persuasion_brief": {
                    "primary_angle": "reduce booking friction",
                    "do_not_use": ["unsupported revenue claims"],
                },
                "supporting_evidence_ids": [evidence_id],
                "score_components": {
                    "severity": 0.7,
                    "evidence_confidence": 0.95,
                    "business_impact": 0.8,
                    "weberaise_fit": 0.95,
                    "explainability": 0.9,
                    "generic_speculation_risk": 0.1,
                },
                "confidence": 0.92,
                "rationale": "A specific evidence-backed conversion opportunity exists.",
            }
        elif task == "writer":
            evidence_id = int(context["allowed_evidence"][0]["id"])
            payload = {
                "subject": "Booking path thought",
                "body": (
                    "I noticed the booking path on your site could be easier to spot. "
                    "WEBERAISE designs and builds business websites; happy to send one focused idea if useful."
                ),
                "claims": [
                    {
                        "text": "The booking path could be easier to spot.",
                        "claim_class": "OBSERVED_FACT",
                        "evidence_ids": [evidence_id],
                    }
                ],
                "strategy_label": "CONVERSION_PROBLEM",
            }
        elif task == "critic":
            payload = {
                "decision": "APPROVE",
                "scores": {
                    "specificity": 90,
                    "naturalness": 90,
                    "persuasiveness": 82,
                    "evidence_integrity": 100,
                    "genericness": 8,
                    "spamminess": 5,
                },
                "issues": [],
            }
        else:  # pragma: no cover
            raise AssertionError(f"unexpected task: {task}")

        return SimpleNamespace(
            output=response_model.model_validate(payload),
            metadata=SimpleNamespace(model="fixture-worker-model"),
        )


async def _database(tmp_path: Path, name: str):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / name}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, factory


async def _enqueue(factory, *, kind: str, lead_id: int, key: str) -> int:
    async with factory() as session:
        job = await JobService(session).enqueue_job(kind, {"lead_id": lead_id}, key)
        return job.id


async def _run_and_assert_complete(
    runtime, factory, *, job_id: int, browser, gateway, playbook, data_root
):
    assert await runtime.run_worker_once(
        factory,
        browser=browser,
        worker_id="fixture-pipeline-worker",
        gateway=gateway,
        playbook=playbook,
        data_root=data_root,
    )
    async with factory() as session:
        job = await session.get(Job, job_id)
        assert job is not None
        assert job.state == "COMPLETE", job.error_message


@pytest.mark.asyncio
async def test_worker_executes_enrich_crawl_research_strategy_and_writer(monkeypatch, tmp_path):
    from scout_email.jobs import runtime

    engine, factory = await _database(tmp_path, "worker-pipeline.db")
    async with factory() as session:
        campaign = Campaign(
            name="Worker pipeline fixture",
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
            name="Worker Dental",
            normalized_name="worker dental",
            category="Dentist",
            city="Lahore",
            canonical_domain="worker-dental.example",
        )
        session.add(lead)
        await session.commit()
        lead_id = lead.id

    async def fake_verify(url: str | None, **_kwargs):
        assert url == "https://worker-dental.example/"
        return WebsiteVerification(
            state=WebsiteState.LIVE,
            requested_url=url,
            final_url=url,
            canonical_domain="worker-dental.example",
            http_status=200,
        )

    async def fake_crawl(url: str, **_kwargs):
        contact_url = "https://worker-dental.example/contact"
        return SiteCrawlResult(
            start_url=url,
            pages=[
                CrawledPage(
                    url=url,
                    title="Worker Dental",
                    headings=["Worker Dental"],
                    important_text="Dental services with online appointment booking.",
                    calls_to_action=["Book appointment"],
                    forms=[],
                    links=[contact_url],
                    images=[],
                    technical_signals={"mobile_viewport_present": True},
                    http_status=200,
                ),
                CrawledPage(
                    url=contact_url,
                    title="Contact",
                    headings=["Contact"],
                    important_text="Email hello@worker-dental.example for appointments.",
                    calls_to_action=[],
                    forms=[],
                    links=[],
                    images=[],
                    technical_signals={},
                    http_status=200,
                ),
            ],
            browser_fallback_urls=[],
            skipped_urls={},
        )

    monkeypatch.setattr(runtime, "verify_website", fake_verify)
    monkeypatch.setattr(runtime, "crawl_site", fake_crawl)

    browser = FixtureBrowser(tmp_path)
    gateway = FixtureGateway()
    playbook = load_playbook(PLAYBOOK_DIR)

    for index, kind in enumerate(
        ("ENRICH", "CRAWL_EVIDENCE", "RESEARCH", "STRATEGY", "WRITER_CRITIC"),
        start=1,
    ):
        job_id = await _enqueue(
            factory,
            kind=kind,
            lead_id=lead_id,
            key=f"pipeline:{index}:{kind}",
        )
        await _run_and_assert_complete(
            runtime,
            factory,
            job_id=job_id,
            browser=browser,
            gateway=gateway,
            playbook=playbook,
            data_root=tmp_path,
        )

    async with factory() as session:
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        assert lead.state == LeadState.CONTACTABLE.value
        assert await session.scalar(
            select(func.count()).select_from(Contact).where(Contact.lead_id == lead_id)
        ) == 1
        draft = await session.scalar(select(EmailDraft).where(EmailDraft.lead_id == lead_id))
        assert draft is not None
        assert draft.approval_state == "PENDING"

    await engine.dispose()


@pytest.mark.asyncio
async def test_writer_stage_is_terminal_noop_for_skipped_lead(tmp_path):
    from scout_email.jobs import runtime

    engine, factory = await _database(tmp_path, "worker-skip.db")
    async with factory() as session:
        campaign = Campaign(
            name="Skip fixture",
            status="ACTIVE",
            target_leads=1,
            max_per_day=10,
            human_approval_required=True,
        )
        session.add(campaign)
        await session.flush()
        lead = Lead(
            campaign_id=campaign.id,
            state=LeadState.SKIPPED.value,
            name="Excellent Business",
            normalized_name="excellent business",
            city="Lahore",
        )
        session.add(lead)
        await session.commit()
        lead_id = lead.id

    job_id = await _enqueue(
        factory,
        kind="WRITER_CRITIC",
        lead_id=lead_id,
        key="skip-writer-stage",
    )
    await _run_and_assert_complete(
        runtime,
        factory,
        job_id=job_id,
        browser=FixtureBrowser(tmp_path),
        gateway=None,
        playbook=None,
        data_root=tmp_path,
    )

    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(EmailDraft)) == 0

    await engine.dispose()
