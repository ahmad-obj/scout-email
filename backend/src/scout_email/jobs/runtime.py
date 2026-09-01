from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from sqlalchemy import select

from scout_email.browser.client import BrowserWorkerClient, BrowserWorkerError
from scout_email.common.enums import LeadState, WebsiteState
from scout_email.crawl.persistence import CrawlPersistenceService
from scout_email.crawl.site import crawl_site
from scout_email.db.models import Evidence, Lead, Website
from scout_email.db.session import SessionLocal
from scout_email.enrichment.service import EnrichmentService, PublicPage
from scout_email.enrichment.website import WebsiteVerification, verify_website
from scout_email.evidence.service import EvidenceService
from scout_email.jobs.service import JobService
from scout_email.jobs.worker import run_one
from scout_email.research.service import ResearchService
from scout_email.scout.jobs import scout_handlers
from scout_email.settings import settings
from scout_email.strategy.service import StrategyService
from scout_email.writing.critic import CriticService
from scout_email.writing.quality import WriterCriticQualityLoop
from scout_email.writing.writer import WriterService


WORKER_JOB_KINDS = (
    "MAPS_SCOUT_SEARCH",
    "ENRICH",
    "CRAWL_EVIDENCE",
    "RESEARCH",
    "STRATEGY",
    "WRITER_CRITIC",
)


def _lead_id(payload: dict) -> int:
    lead_id = int(payload["lead_id"])
    if lead_id <= 0:
        raise ValueError("lead_id must be positive")
    return lead_id


def _lead_homepage(lead: Lead) -> str | None:
    if not lead.canonical_domain:
        return None
    return f"https://{lead.canonical_domain.strip().strip('/')}/"


def _website_verification(row: Website) -> WebsiteVerification:
    return WebsiteVerification(
        state=WebsiteState(row.state),
        requested_url=row.url,
        final_url=row.final_url,
        canonical_domain=row.canonical_domain,
        http_status=row.http_status,
    )


async def _persist_non_live_website_evidence(session, *, lead_id: int, website: Website) -> None:
    claim = f"Website state is {website.state}"
    existing = await session.scalar(
        select(Evidence).where(
            Evidence.lead_id == lead_id,
            Evidence.kind == "website_verification",
            Evidence.claim == claim,
            Evidence.source_type == "website_verification",
        )
    )
    if existing is None:
        session.add(
            Evidence(
                lead_id=lead_id,
                kind="website_verification",
                claim_class="OBSERVED_FACT",
                claim=claim,
                source_type="website_verification",
                source_url=website.final_url or website.url,
                confidence=1.0,
            )
        )
        await session.commit()


def _research_page_urls(result) -> list[str]:
    urls = list(dict.fromkeys(page.url for page in result.pages))

    def priority(url: str) -> tuple[int, str]:
        lowered = url.casefold()
        if any(token in lowered for token in ("/contact", "/about", "/team")):
            return (0, lowered)
        return (1, lowered)

    return sorted(urls, key=priority)[:8]


def build_handlers(
    session,
    *,
    browser,
    gateway: Any | None,
    playbook: Any | None,
    data_root: Path,
):
    handlers = dict(scout_handlers(session, browser))

    async def enrich(payload: dict) -> dict:
        lead_id = _lead_id(payload)
        lead = await session.get(Lead, lead_id)
        if lead is None:
            raise ValueError(f"lead {lead_id} does not exist")
        verification = await verify_website(_lead_homepage(lead))
        await EnrichmentService(session).persist(lead_id, verification, [])
        return verification.model_dump(mode="json")

    async def crawl_evidence(payload: dict) -> dict:
        lead_id = _lead_id(payload)
        lead = await session.get(Lead, lead_id)
        if lead is None:
            raise ValueError(f"lead {lead_id} does not exist")
        website = await session.scalar(select(Website).where(Website.lead_id == lead_id))
        if website is None:
            raise RuntimeError("ENRICH must complete before CRAWL_EVIDENCE")

        verification = _website_verification(website)
        homepage_url = website.final_url or website.url
        if website.state != WebsiteState.LIVE.value or not homepage_url:
            await _persist_non_live_website_evidence(
                session,
                lead_id=lead_id,
                website=website,
            )
            return {
                "status": "SKIPPED_NON_LIVE",
                "website_state": website.state,
                "pages": 0,
            }

        result = await crawl_site(homepage_url, max_pages=20)
        await CrawlPersistenceService(session).persist(lead_id=lead_id, result=result)

        public_pages: list[PublicPage] = []
        for page_url in _research_page_urls(result):
            try:
                rendered = await browser.render(page_url)
            except BrowserWorkerError:
                continue
            public_pages.append(
                PublicPage(
                    url=rendered.final_url,
                    html=rendered.html,
                    verified=True,
                )
            )
        await EnrichmentService(session).persist(lead_id, verification, public_pages)

        bundle = await EvidenceService(
            session,
            data_root=Path(data_root),
            browser_client=browser,
        ).build_bundle(
            campaign_id=lead.campaign_id,
            lead_id=lead_id,
            homepage_url=homepage_url,
        )
        return {
            "status": "COMPLETE",
            "pages": len(result.pages),
            "evidence": len(bundle.evidence),
            "screenshots": len(bundle.screenshots),
        }

    async def research(payload: dict) -> dict:
        if gateway is None:
            raise RuntimeError("LLM gateway is not configured for RESEARCH jobs")
        output = await ResearchService(session, gateway=gateway).research(
            lead_id=_lead_id(payload)
        )
        return output.model_dump(mode="json")

    async def strategy(payload: dict) -> dict:
        if gateway is None:
            raise RuntimeError("LLM gateway is not configured for STRATEGY jobs")
        output = await StrategyService(session, gateway=gateway).strategize(
            lead_id=_lead_id(payload)
        )
        return output.model_dump(mode="json")

    async def writer_critic(payload: dict) -> dict:
        lead_id = _lead_id(payload)
        lead = await session.get(Lead, lead_id)
        if lead is None:
            raise ValueError(f"lead {lead_id} does not exist")
        if lead.state != LeadState.CONTACTABLE.value:
            return {
                "status": "SKIPPED",
                "lead_state": lead.state,
                "reason": "lead is not contactable",
            }
        if gateway is None:
            raise RuntimeError("LLM gateway is not configured for WRITER_CRITIC jobs")
        if playbook is None:
            raise RuntimeError("writing playbook is not configured for WRITER_CRITIC jobs")

        loop = WriterCriticQualityLoop(
            session,
            writer=WriterService(session, gateway=gateway, playbook=playbook),
            critic=CriticService(session, gateway=gateway),
        )
        result = await loop.run(lead_id=lead_id)
        return {
            "status": "COMPLETE",
            "draft_id": result.draft_id,
            "decision": result.final_decision.value,
            "rewrite_count": result.rewrite_count,
            "requires_human_review": result.requires_human_review,
            "issues": list(result.issues),
        }

    handlers.update(
        {
            "ENRICH": enrich,
            "CRAWL_EVIDENCE": crawl_evidence,
            "RESEARCH": research,
            "STRATEGY": strategy,
            "WRITER_CRITIC": writer_critic,
        }
    )
    return handlers


async def run_worker_once(
    session_factory,
    *,
    browser,
    worker_id: str,
    gateway: Any | None,
    playbook: Any | None,
    data_root: Path,
) -> bool:
    async with session_factory() as session:
        handlers = build_handlers(
            session,
            browser=browser,
            gateway=gateway,
            playbook=playbook,
            data_root=data_root,
        )
        return await run_one(
            JobService(session),
            worker_id,
            list(WORKER_JOB_KINDS),
            handlers,
        )


async def run_forever(
    *,
    session_factory=SessionLocal,
    browser=None,
    gateway: Any | None = None,
    playbook: Any | None = None,
    data_root: Path | None = None,
    worker_id: str = "outreach-worker-1",
    poll_interval_seconds: float = 0.5,
    max_iterations: int | None = None,
) -> None:
    """Continuously claim and execute queued backend jobs."""
    if poll_interval_seconds < 0:
        raise ValueError("poll_interval_seconds must not be negative")
    if max_iterations is not None and max_iterations < 1:
        raise ValueError("max_iterations must be positive when provided")

    owns_browser = browser is None
    if browser is None:
        browser = BrowserWorkerClient(settings.browser_worker_url)
    data_root = Path(data_root or settings.data_dir)

    iterations = 0
    try:
        while max_iterations is None or iterations < max_iterations:
            processed = await run_worker_once(
                session_factory,
                browser=browser,
                worker_id=worker_id,
                gateway=gateway,
                playbook=playbook,
                data_root=data_root,
            )
            iterations += 1
            if not processed and poll_interval_seconds:
                await asyncio.sleep(poll_interval_seconds)
    finally:
        if owns_browser:
            await browser.aclose()


def main() -> None:
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
