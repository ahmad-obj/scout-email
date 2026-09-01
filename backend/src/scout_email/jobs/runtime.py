from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from scout_email.jobs.service import JobService
from scout_email.jobs.worker import run_one
from scout_email.scout.jobs import scout_handlers


WORKER_JOB_KINDS = (
    "MAPS_SCOUT_SEARCH",
    "ENRICH",
    "CRAWL_EVIDENCE",
    "RESEARCH",
    "STRATEGY",
    "WRITER_CRITIC",
)


async def run_worker_once(
    session_factory,
    *,
    browser,
    worker_id: str,
    gateway: Any | None,
    playbook: Any | None,
    data_root: Path,
) -> bool:
    del gateway, playbook, data_root
    async with session_factory() as session:
        handlers = scout_handlers(session, browser)
        return await run_one(
            JobService(session),
            worker_id,
            list(WORKER_JOB_KINDS),
            handlers,
        )


async def run_forever() -> None:
    """Keep the background worker process alive.

    Full domain-handler composition is built incrementally behind this stable
    process entrypoint. Queue execution itself uses the SQLite lease/retry
    engine shared by every backend job.
    """
    while True:
        await asyncio.sleep(3600)


def main() -> None:
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
