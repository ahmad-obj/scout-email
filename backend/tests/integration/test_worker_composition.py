from importlib import import_module
from importlib.util import find_spec
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from scout_email.browser.schemas import BrowserMapLead
from scout_email.db.base import Base
from scout_email.db.models import Campaign, CampaignSearch, Evidence, Job, Lead, ResearchReport
from scout_email.db.session import create_engine_and_sessionmaker
from scout_email.jobs.service import JobService
from scout_email.research.schemas import (
    BusinessModelSummary,
    BusinessSummary,
    EvidenceFinding,
    PresenceSummary,
    ResearchOutput,
)
from scout_email.scout.schemas import ScoutSearchJobPayload
from scout_email.scout.service import SCOUT_JOB_KIND


EXPECTED_JOB_KINDS = {
    "MAPS_SCOUT_SEARCH",
    "ENRICH",
    "CRAWL_EVIDENCE",
    "RESEARCH",
    "STRATEGY",
    "WRITER_CRITIC",
}


def test_deployment_starts_background_job_worker():
    repo_root = Path(__file__).resolve().parents[3]
    compose = (repo_root / "docker-compose.yml").read_text(encoding="utf-8")

    assert "\n  outreach-worker:" in compose
    assert "python -m scout_email.jobs.runtime" in compose


def test_browser_worker_artifacts_share_backend_data_root():
    repo_root = Path(__file__).resolve().parents[3]
    compose = (repo_root / "docker-compose.yml").read_text(encoding="utf-8")

    assert "BROWSER_WORKER_ARTIFACT_DIR: /data\n" in compose


def test_worker_runtime_declares_every_n8n_job_kind():
    spec = find_spec("scout_email.jobs.runtime")
    assert spec is not None, "deployed stack has no job worker runtime module"

    from scout_email.jobs.runtime import WORKER_JOB_KINDS

    assert set(WORKER_JOB_KINDS) == EXPECTED_JOB_KINDS


class FixtureMapsBrowser:
    async def search_maps(self, query: str, max_results: int):
        assert query == "dentist in Lahore"
        assert max_results == 1
        return [
            BrowserMapLead(
                name="Worker Dental",
                category="Dentist",
                address="Lahore",
                website="https://worker-dental.example",
                rating=4.7,
                review_count=80,
                maps_url="https://maps.google.com/?cid=worker-dental",
                source_external_id="worker-dental-place",
            )
        ]


class FixtureResearchGateway:
    async def generate(self, *, task, context, response_model, prompt_version):
        assert task == "researcher"
        evidence_id = context["evidence"][0]["id"]
        output = ResearchOutput(
            business=BusinessSummary(
                name=context["business"]["name"],
                summary="Public evidence confirms a local business website.",
                category=context["business"]["category"],
                location=context["business"]["city"],
            ),
            business_model=BusinessModelSummary(),
            presence=PresenceSummary(website_state="LIVE"),
            strengths=[
                EvidenceFinding(
                    text="The business has a public website.",
                    evidence_ids=[evidence_id],
                )
            ],
            website_findings=[],
            technical_findings=[],
            contact=None,
            confidence=0.9,
            outcome="COMPLETE",
        )
        assert isinstance(output, response_model)
        return SimpleNamespace(
            output=output,
            metadata=SimpleNamespace(model="fixture-research-model"),
        )


@pytest.mark.asyncio
async def test_worker_runtime_consumes_maps_job_and_persists_lead(tmp_path):
    runtime = import_module("scout_email.jobs.runtime")
    assert hasattr(runtime, "run_worker_once"), "worker process never claims queued jobs"

    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'worker.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as session:
        campaign = Campaign(
            name="Worker fixture",
            status="ACTIVE",
            target_leads=1,
            max_per_day=10,
            human_approval_required=True,
        )
        session.add(campaign)
        await session.flush()
        search = CampaignSearch(
            campaign_id=campaign.id,
            search_term="dentist",
            location="Lahore",
        )
        session.add(search)
        await session.flush()
        payload = ScoutSearchJobPayload(
            campaign_id=campaign.id,
            campaign_search_id=search.id,
            query="dentist in Lahore",
            search_term="dentist",
            location="Lahore",
            max_results=1,
        )
        queued = await JobService(session).enqueue_job(
            SCOUT_JOB_KIND,
            payload.model_dump(mode="json"),
            "worker-maps-fixture",
        )
        job_id = queued.id

    processed = await runtime.run_worker_once(
        factory,
        browser=FixtureMapsBrowser(),
        worker_id="fixture-worker",
        gateway=None,
        playbook=None,
        data_root=tmp_path,
    )
    assert processed is True

    async with factory() as session:
        job = await session.get(Job, job_id)
        assert job is not None
        assert job.state == "COMPLETE"
        assert await session.scalar(select(func.count()).select_from(Lead)) == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_worker_runtime_consumes_research_job(tmp_path):
    runtime = import_module("scout_email.jobs.runtime")
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'research-worker.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as session:
        campaign = Campaign(
            name="Research worker fixture",
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
            name="Research Dental",
            normalized_name="research dental",
            category="Dentist",
            city="Lahore",
            canonical_domain="research-dental.example",
        )
        session.add(lead)
        await session.flush()
        evidence = Evidence(
            lead_id=lead.id,
            kind="website_verification",
            claim_class="OBSERVED_FACT",
            claim="Website state is LIVE",
            source_type="website_verification",
            source_url="https://research-dental.example/",
            confidence=1.0,
        )
        session.add(evidence)
        await session.flush()
        queued = await JobService(session).enqueue_job(
            "RESEARCH",
            {"lead_id": lead.id},
            "research-worker-fixture",
        )
        job_id = queued.id
        lead_id = lead.id

    processed = await runtime.run_worker_once(
        factory,
        browser=FixtureMapsBrowser(),
        worker_id="fixture-worker",
        gateway=FixtureResearchGateway(),
        playbook=None,
        data_root=tmp_path,
    )
    assert processed is True

    async with factory() as session:
        job = await session.get(Job, job_id)
        assert job is not None
        assert job.state == "COMPLETE"
        report = await session.scalar(
            select(ResearchReport).where(ResearchReport.lead_id == lead_id)
        )
        assert report is not None
        assert report.status == "COMPLETE"

    await engine.dispose()


@pytest.mark.asyncio
async def test_worker_run_loop_calls_worker_iteration(monkeypatch, tmp_path):
    runtime = import_module("scout_email.jobs.runtime")
    calls = 0

    async def fake_run_worker_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        return False

    monkeypatch.setattr(runtime, "run_worker_once", fake_run_worker_once)
    await runtime.run_forever(
        session_factory=object(),
        browser=object(),
        gateway=None,
        playbook=None,
        data_root=tmp_path,
        worker_id="fixture-loop",
        poll_interval_seconds=0,
        max_iterations=1,
    )
    assert calls == 1
