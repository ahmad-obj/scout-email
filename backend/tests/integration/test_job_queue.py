import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from scout_email.common.errors import DuplicateOperationError
from scout_email.db.base import Base
from scout_email.jobs.service import JobService


@pytest_asyncio.fixture
async def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'jobs.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.asyncio
async def test_duplicate_enqueue_returns_existing_but_payload_mismatch_fails(factory):
    async with factory() as session:
        service = JobService(session)
        first = await service.enqueue_job("research", {"lead_id": 1}, "research:1")
        second = await service.enqueue_job("research", {"lead_id": 1}, "research:1")
        assert first.id == second.id
        with pytest.raises(DuplicateOperationError):
            await service.enqueue_job("research", {"lead_id": 2}, "research:1")


@pytest.mark.asyncio
async def test_two_workers_have_exactly_one_claim_winner(factory):
    async with factory() as session:
        await JobService(session).enqueue_job("research", {"lead_id": 1}, "research:1")

    async def claim(worker):
        async with factory() as session:
            return await JobService(session).claim_next_job(worker, ["research"])

    results = await asyncio.gather(claim("a"), claim("b"))
    assert sum(result is not None for result in results) == 1


@pytest.mark.asyncio
async def test_expired_lease_is_reclaimable(factory):
    t0 = datetime(2026, 8, 30, tzinfo=UTC)
    async with factory() as session:
        service = JobService(session, lease_seconds=10)
        job = await service.enqueue_job("research", {}, "r:1")
        first = await service.claim_next_job("worker-a", ["research"], now=t0)
        assert first.id == job.id
    async with factory() as session:
        reclaimed = await JobService(session, lease_seconds=10).claim_next_job(
            "worker-b", ["research"], now=t0 + timedelta(seconds=11)
        )
        assert reclaimed is not None
        assert reclaimed.locked_by == "worker-b"
        assert reclaimed.attempt_count == 2


@pytest.mark.asyncio
async def test_stale_worker_cannot_complete_after_reclaim(factory):
    t0 = datetime(2026, 8, 30, tzinfo=UTC)
    async with factory() as session:
        service = JobService(session, lease_seconds=5)
        job = await service.enqueue_job("research", {}, "r:stale")
        await service.claim_next_job("worker-a", ["research"], now=t0)
    async with factory() as session:
        service = JobService(session, lease_seconds=5)
        await service.claim_next_job(
            "worker-b", ["research"], now=t0 + timedelta(seconds=6)
        )
        with pytest.raises(DuplicateOperationError):
            await service.complete_job(job.id, "worker-a", {})


@pytest.mark.asyncio
async def test_retry_metadata_is_bounded_and_terminal_at_max_attempts(factory):
    t0 = datetime(2026, 8, 30, tzinfo=UTC)
    async with factory() as session:
        service = JobService(session)
        job = await service.enqueue_job("research", {}, "r:retry", max_attempts=2)
        first = await service.claim_next_job("worker-a", ["research"], now=t0)
        retried = await service.retry_job(
            first.id,
            "worker-a",
            "HTTP_TIMEOUT",
            "timed out\nwhile crawling",
            now=t0,
        )
        assert retried.state == "RETRY"
        assert retried.next_attempt_at == t0 + timedelta(seconds=30)
        assert retried.last_error_code == "HTTP_TIMEOUT"
        assert retried.last_error_message == "timed out while crawling"

    async with factory() as session:
        service = JobService(session)
        second = await service.claim_next_job(
            "worker-b", ["research"], now=t0 + timedelta(seconds=31)
        )
        failed = await service.retry_job(
            second.id,
            "worker-b",
            "HTTP_TIMEOUT",
            "again",
            now=t0 + timedelta(seconds=31),
        )
        assert failed.state == "FAILED"
        assert failed.next_attempt_at is None
        assert failed.attempt_count == 2


@pytest.mark.asyncio
async def test_expired_owner_cannot_complete_even_before_reclaim(factory):
    t0 = datetime(2026, 8, 30, tzinfo=UTC)
    async with factory() as session:
        service = JobService(session, lease_seconds=5)
        job = await service.enqueue_job("research", {}, "r:expired-owner")
        await service.claim_next_job("worker-a", ["research"], now=t0)
        with pytest.raises(DuplicateOperationError):
            await service.complete_job(
                job.id,
                "worker-a",
                {},
                now=t0 + timedelta(seconds=6),
            )
