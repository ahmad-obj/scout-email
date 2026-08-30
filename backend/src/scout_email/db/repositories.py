from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from scout_email.common.enums import JobState, LeadState
from scout_email.common.errors import (
    DuplicateOperationError,
    InvalidStateTransitionError,
    NotFoundError,
)
from scout_email.db.models import Job, Lead


_ALLOWED_LEAD_TRANSITIONS: dict[LeadState, frozenset[LeadState]] = {
    LeadState.DISCOVERED: frozenset(
        {LeadState.QUALIFIED, LeadState.LOW_PRIORITY, LeadState.REJECTED}
    ),
    LeadState.QUALIFIED: frozenset(
        {LeadState.RESEARCH_PENDING, LeadState.NO_CONTACT, LeadState.SKIPPED}
    ),
    LeadState.LOW_PRIORITY: frozenset(
        {LeadState.QUALIFIED, LeadState.REJECTED, LeadState.SKIPPED}
    ),
    LeadState.REJECTED: frozenset(),
    LeadState.RESEARCH_PENDING: frozenset({LeadState.RESEARCHING, LeadState.SKIPPED}),
    LeadState.RESEARCHING: frozenset(
        {LeadState.RESEARCHED, LeadState.RESEARCH_PENDING, LeadState.SKIPPED}
    ),
    LeadState.RESEARCHED: frozenset(
        {LeadState.CONTACTABLE, LeadState.NO_CONTACT, LeadState.SKIPPED}
    ),
    LeadState.CONTACTABLE: frozenset({LeadState.SKIPPED}),
    LeadState.NO_CONTACT: frozenset({LeadState.RESEARCH_PENDING, LeadState.SKIPPED}),
    LeadState.SKIPPED: frozenset(),
}


def validate_lead_transition(current: LeadState, new: LeadState) -> None:
    allowed = _ALLOWED_LEAD_TRANSITIONS[current]
    if new not in allowed:
        raise InvalidStateTransitionError(
            f"Lead transition {current.value} -> {new.value} is not allowed"
        )


class LeadRepository:
    """Lead persistence helpers. Caller owns transaction boundaries."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, lead_id: int) -> Lead:
        lead = await self.session.get(Lead, lead_id)
        if lead is None:
            raise NotFoundError(f"Lead {lead_id} not found")
        return lead

    async def transition(
        self,
        lead_id: int,
        new_state: LeadState,
        *,
        expected_state: LeadState | None = None,
    ) -> LeadState:
        if expected_state is None:
            current_value = await self.session.scalar(
                select(Lead.state).where(Lead.id == lead_id)
            )
            if current_value is None:
                raise NotFoundError(f"Lead {lead_id} not found")
            current = LeadState(current_value)
        else:
            current = expected_state

        validate_lead_transition(current, new_state)

        result = await self.session.execute(
            update(Lead)
            .where(Lead.id == lead_id, Lead.state == current.value)
            .values(state=new_state.value)
        )
        if result.rowcount == 1:
            return new_state

        exists = await self.session.scalar(select(Lead.id).where(Lead.id == lead_id))
        if exists is None:
            raise NotFoundError(f"Lead {lead_id} not found")
        raise DuplicateOperationError(
            f"Lead {lead_id} is no longer in expected state {current.value}"
        )


class JobRepository:
    """Job queue persistence helpers using compare-and-set claims."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, job_id: int) -> Job:
        job = await self.session.get(Job, job_id)
        if job is None:
            raise NotFoundError(f"Job {job_id} not found")
        return job

    async def claim(self, job_id: int, *, now: datetime | None = None) -> bool:
        claim_time = now or datetime.now(UTC)
        result = await self.session.execute(
            update(Job)
            .where(
                Job.id == job_id,
                Job.state.in_([JobState.PENDING.value, JobState.RETRY.value]),
                (Job.run_after.is_(None) | (Job.run_after <= claim_time)),
                Job.attempts < Job.max_attempts,
            )
            .values(
                state=JobState.RUNNING.value,
                attempts=Job.attempts + 1,
                locked_at=claim_time,
                last_error=None,
            )
        )
        return result.rowcount == 1
