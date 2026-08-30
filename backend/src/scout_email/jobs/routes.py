from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from scout_email.common.errors import DuplicateOperationError, NotFoundError
from scout_email.db.session import get_session
from scout_email.jobs.schemas import JobClaimRequest, JobEnqueueRequest, JobView
from scout_email.jobs.service import JobService

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=JobView, status_code=status.HTTP_201_CREATED)
async def enqueue(
    payload: JobEnqueueRequest,
    session: AsyncSession = Depends(get_session),
) -> JobView:
    try:
        return await JobService(session).enqueue_job(
            payload.kind,
            payload.payload,
            payload.idempotency_key,
            max_attempts=payload.max_attempts,
        )
    except DuplicateOperationError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/claim", response_model=JobView | None)
async def claim(
    payload: JobClaimRequest,
    session: AsyncSession = Depends(get_session),
) -> JobView | None:
    return await JobService(session).claim_next_job(payload.worker_id, payload.kinds)


@router.get("/{job_id}", response_model=JobView)
async def get_job(
    job_id: int,
    session: AsyncSession = Depends(get_session),
) -> JobView:
    try:
        return await JobService(session).get_job(job_id)
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
