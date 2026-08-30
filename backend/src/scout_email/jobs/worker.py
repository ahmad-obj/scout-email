from __future__ import annotations

from collections.abc import Awaitable, Callable

from scout_email.jobs.service import JobService

Handler = Callable[[dict], Awaitable[dict | None]]


async def run_one(
    service: JobService,
    worker_id: str,
    kinds: list[str],
    handlers: dict[str, Handler],
) -> bool:
    job = await service.claim_next_job(worker_id, kinds)
    if job is None:
        return False

    handler = handlers.get(job.kind)
    if handler is None:
        await service.fail_job(
            job.id,
            worker_id,
            "NO_HANDLER",
            f"No handler registered for {job.kind}",
        )
        return True

    try:
        result = await handler(job.payload)
    except Exception as error:
        await service.retry_job(
            job.id,
            worker_id,
            type(error).__name__,
            str(error),
        )
        return True

    await service.complete_job(job.id, worker_id, result)
    return True
