from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from scout_email.browser.client import BrowserWorkerClient
from scout_email.db.session import SessionLocal
from scout_email.jobs.service import JobService
from scout_email.jobs.worker import run_one
from scout_email.research.service import ResearchService
from scout_email.scout.jobs import scout_handlers
from scout_email.settings import settings


WORKER_JOB_KINDS = (
    "MAPS_SCOUT_SEARCH",
    "ENRICH",
    "CRAWL_EVIDENCE",
    "RESEARCH",
    "STRATEGY",
    "WRITER_CRITIC",
)


def build_handlers(
    session,
    *,
    browser,
    gateway: Any | None,
    playbook: Any | None,
    data_root: Path,
):
    del playbook, data_root
    handlers = dict(scout_handlers(session, browser))

    if gateway is not None:
        async def research(payload: dict):
            lead_id = int(payload["lead_id"])
            output = await ResearchService(session, gateway=gateway).research(
                lead_id=lead_id
            )
            return output.model_dump(mode="json")

        handlers["RESEARCH"] = research

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
