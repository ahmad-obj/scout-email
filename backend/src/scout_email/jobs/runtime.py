from __future__ import annotations

import asyncio


WORKER_JOB_KINDS = (
    "MAPS_SCOUT_SEARCH",
    "ENRICH",
    "CRAWL_EVIDENCE",
    "RESEARCH",
    "STRATEGY",
    "WRITER_CRITIC",
)


async def run_forever() -> None:
    """Keep the background worker process alive.

    Job claiming and handler composition are added behind this stable process
    entrypoint so Docker/n8n can depend on one long-running backend worker.
    """
    while True:
        await asyncio.sleep(3600)


def main() -> None:
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
