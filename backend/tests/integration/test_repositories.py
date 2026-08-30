import asyncio

import pytest
from sqlalchemy import select

from scout_email.common.enums import JobState, LeadState
from scout_email.common.errors import DuplicateOperationError, InvalidStateTransitionError
from scout_email.db.base import Base
from scout_email.db.models import Campaign, Job, Lead
from scout_email.db.repositories import JobRepository, LeadRepository
from scout_email.db.session import create_engine_and_sessionmaker


async def _database(tmp_path):
    engine, factory = create_engine_and_sessionmaker(
        f"sqlite+aiosqlite:///{tmp_path / 'repos.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, factory


@pytest.mark.asyncio
async def test_lead_repository_rejects_illegal_jump(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        campaign = Campaign(name="Test", target_leads=1)
        session.add(campaign)
        await session.flush()
        lead = Lead(
            campaign_id=campaign.id,
            name="ABC Dental",
            normalized_name="abc dental",
            state=LeadState.DISCOVERED.value,
        )
        session.add(lead)
        await session.commit()
        lead_id = lead.id

    async with factory() as session:
        repo = LeadRepository(session)
        with pytest.raises(InvalidStateTransitionError):
            await repo.transition(lead_id, LeadState.RESEARCHED)
        await session.rollback()

    await engine.dispose()


@pytest.mark.asyncio
async def test_lead_compare_and_set_rejects_stale_expected_state(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        campaign = Campaign(name="Test", target_leads=1)
        session.add(campaign)
        await session.flush()
        lead = Lead(
            campaign_id=campaign.id,
            name="ABC Dental",
            normalized_name="abc dental",
            state=LeadState.DISCOVERED.value,
        )
        session.add(lead)
        await session.commit()
        lead_id = lead.id

    async with factory() as session:
        repo = LeadRepository(session)
        await repo.transition(
            lead_id,
            LeadState.QUALIFIED,
            expected_state=LeadState.DISCOVERED,
        )
        await session.commit()

    async with factory() as session:
        repo = LeadRepository(session)
        with pytest.raises(DuplicateOperationError):
            await repo.transition(
                lead_id,
                LeadState.LOW_PRIORITY,
                expected_state=LeadState.DISCOVERED,
            )
        await session.rollback()

    await engine.dispose()


@pytest.mark.asyncio
async def test_two_workers_claiming_same_job_have_exactly_one_winner(tmp_path):
    engine, factory = await _database(tmp_path)
    async with factory() as session:
        job = Job(job_type="research", state=JobState.PENDING.value, payload_json="{}")
        session.add(job)
        await session.commit()
        job_id = job.id

    async def claim_once() -> bool:
        async with factory() as session:
            repo = JobRepository(session)
            won = await repo.claim(job_id)
            if won:
                await session.commit()
            else:
                await session.rollback()
            return won

    results = await asyncio.gather(claim_once(), claim_once())
    assert sorted(results) == [False, True]

    async with factory() as session:
        state = await session.scalar(select(Job.state).where(Job.id == job_id))
        assert state == JobState.RUNNING.value

    await engine.dispose()
