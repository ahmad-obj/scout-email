from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from scout_email.common.enums import JobState
from scout_email.common.errors import DuplicateOperationError, NotFoundError
from scout_email.db.models import Job
from scout_email.jobs.models import JobRuntime
from scout_email.jobs.schemas import JobView

_CONTROL_CHARACTERS = re.compile(r"[\r\n\t]+")


def retry_delay_seconds(
    attempt_count: int,
    base_seconds: int = 30,
    cap_seconds: int = 3600,
) -> int:
    return min(cap_seconds, base_seconds * (2 ** max(0, attempt_count - 1)))


def sanitize_error_message(value: str) -> str:
    return _CONTROL_CHARACTERS.sub(" ", value).strip()[:1000]


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load_json(value: str | None) -> Any:
    return json.loads(value) if value else None


def _utc_compatible(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class JobService:
    def __init__(self, session: AsyncSession, *, lease_seconds: int = 300) -> None:
        self.session = session
        self.lease_seconds = lease_seconds

    async def _view(self, job: Job) -> JobView:
        runtime = await self.session.get(JobRuntime, job.id)
        return JobView(
            id=job.id,
            kind=job.job_type,
            state=job.state,
            payload=_load_json(job.payload_json) or {},
            result=_load_json(job.result_json),
            attempt_count=job.attempts,
            max_attempts=job.max_attempts,
            next_attempt_at=job.run_after,
            locked_by=runtime.locked_by if runtime else None,
            lease_expires_at=runtime.lease_expires_at if runtime else None,
            last_error_code=runtime.last_error_code if runtime else None,
            last_error_message=runtime.last_error_message if runtime else None,
        )

    async def get_job(self, job_id: int) -> JobView:
        job = await self.session.get(Job, job_id)
        if job is None:
            raise NotFoundError(f"Job {job_id} not found")
        return await self._view(job)

    async def enqueue_job(
        self,
        kind: str,
        payload: dict[str, Any],
        idempotency_key: str,
        *,
        max_attempts: int = 3,
    ) -> JobView:
        if not idempotency_key.strip():
            raise ValueError("idempotency_key is required")

        payload_json = _dump_json(payload)
        statement = (
            sqlite_insert(Job)
            .values(
                job_type=kind,
                state=JobState.PENDING.value,
                payload_json=payload_json,
                max_attempts=max_attempts,
                idempotency_key=idempotency_key,
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
        )
        await self.session.execute(statement)
        await self.session.commit()

        job = (
            await self.session.execute(
                select(Job).where(Job.idempotency_key == idempotency_key)
            )
        ).scalar_one()
        if job.job_type != kind or job.payload_json != payload_json:
            raise DuplicateOperationError(
                "idempotency key already belongs to a different job payload"
            )
        return await self._view(job)

    async def _recover_expired(self, now: datetime) -> None:
        rows = (
            await self.session.execute(
                select(JobRuntime, Job)
                .join(Job, Job.id == JobRuntime.job_id)
                .where(
                    JobRuntime.lease_expires_at.is_not(None),
                    JobRuntime.lease_expires_at <= now,
                    Job.state == JobState.RUNNING.value,
                )
            )
        ).all()

        for runtime, job in rows:
            runtime.locked_by = None
            runtime.lease_expires_at = None
            runtime.last_error_code = "LEASE_EXPIRED"
            runtime.last_error_message = "job lease expired before completion"
            job.locked_at = None
            job.last_error = _dump_json(
                {
                    "code": runtime.last_error_code,
                    "message": runtime.last_error_message,
                }
            )
            if job.attempts >= job.max_attempts:
                job.state = JobState.FAILED.value
                job.run_after = None
            else:
                job.state = JobState.RETRY.value
                job.run_after = now

        if rows:
            await self.session.commit()

    async def claim_next_job(
        self,
        worker_id: str,
        kinds: list[str],
        *,
        now: datetime | None = None,
    ) -> JobView | None:
        if not worker_id.strip() or not kinds:
            raise ValueError("worker_id and kinds are required")

        claim_time = now or datetime.now(UTC)
        await self._recover_expired(claim_time)

        candidate_ids = (
            await self.session.execute(
                select(Job.id)
                .where(
                    Job.job_type.in_(kinds),
                    Job.state.in_([JobState.PENDING.value, JobState.RETRY.value]),
                    (Job.run_after.is_(None) | (Job.run_after <= claim_time)),
                    Job.attempts < Job.max_attempts,
                )
                .order_by(Job.run_after, Job.id)
                .limit(20)
            )
        ).scalars().all()

        for job_id in candidate_ids:
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
                    run_after=None,
                    last_error=None,
                )
            )
            if result.rowcount != 1:
                await self.session.rollback()
                continue

            runtime = await self.session.get(JobRuntime, job_id)
            if runtime is None:
                runtime = JobRuntime(job_id=job_id)
                self.session.add(runtime)
            runtime.locked_by = worker_id
            runtime.lease_expires_at = claim_time + timedelta(seconds=self.lease_seconds)
            await self.session.commit()
            return await self.get_job(job_id)

        return None

    async def _owned(
        self,
        job_id: int,
        worker_id: str,
        *,
        now: datetime | None = None,
    ) -> tuple[Job, JobRuntime]:
        job = await self.session.get(Job, job_id)
        runtime = await self.session.get(JobRuntime, job_id)
        if job is None:
            raise NotFoundError(f"Job {job_id} not found")

        check_time = now or datetime.now(UTC)
        lease_is_active = (
            runtime is not None
            and runtime.lease_expires_at is not None
            and _utc_compatible(runtime.lease_expires_at) > _utc_compatible(check_time)
        )
        if (
            job.state != JobState.RUNNING.value
            or runtime is None
            or runtime.locked_by != worker_id
            or not lease_is_active
        ):
            raise DuplicateOperationError(
                f"Worker {worker_id} does not own an active lease for job {job_id}"
            )
        return job, runtime

    async def complete_job(
        self,
        job_id: int,
        worker_id: str,
        result: dict[str, Any] | None = None,
        *,
        now: datetime | None = None,
    ) -> JobView:
        job, runtime = await self._owned(job_id, worker_id, now=now)
        job.state = JobState.COMPLETE.value
        job.result_json = _dump_json(result or {})
        job.locked_at = None
        runtime.locked_by = None
        runtime.lease_expires_at = None
        await self.session.commit()
        return await self.get_job(job_id)

    async def retry_job(
        self,
        job_id: int,
        worker_id: str,
        error_code: str,
        message: str,
        *,
        now: datetime | None = None,
    ) -> JobView:
        retry_time = now or datetime.now(UTC)
        job, runtime = await self._owned(job_id, worker_id, now=retry_time)
        sanitized_message = sanitize_error_message(message)
        runtime.last_error_code = error_code[:120]
        runtime.last_error_message = sanitized_message
        job.last_error = _dump_json(
            {"code": runtime.last_error_code, "message": sanitized_message}
        )
        job.locked_at = None
        runtime.locked_by = None
        runtime.lease_expires_at = None

        if job.attempts >= job.max_attempts:
            job.state = JobState.FAILED.value
            job.run_after = None
        else:
            job.state = JobState.RETRY.value
            job.run_after = retry_time + timedelta(
                seconds=retry_delay_seconds(job.attempts)
            )

        await self.session.commit()
        return await self.get_job(job_id)

    async def fail_job(
        self,
        job_id: int,
        worker_id: str,
        error_code: str,
        message: str,
        *,
        now: datetime | None = None,
    ) -> JobView:
        job, runtime = await self._owned(job_id, worker_id, now=now)
        sanitized_message = sanitize_error_message(message)
        runtime.last_error_code = error_code[:120]
        runtime.last_error_message = sanitized_message
        job.state = JobState.FAILED.value
        job.last_error = _dump_json(
            {"code": runtime.last_error_code, "message": sanitized_message}
        )
        job.locked_at = None
        runtime.locked_by = None
        runtime.lease_expires_at = None
        await self.session.commit()
        return await self.get_job(job_id)
