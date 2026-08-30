from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from scout_email.common.errors import DuplicateOperationError
from scout_email.db.session import get_session
from scout_email.leads.schemas import LeadIngestResult, LeadSourceInput, RawLead
from scout_email.leads.service import LeadIngestService

router = APIRouter(prefix="/campaigns/{campaign_id}/leads", tags=["leads"])


@router.post("/ingest", response_model=LeadIngestResult, status_code=status.HTTP_200_OK)
async def ingest_lead(
    campaign_id: int,
    raw: RawLead,
    source: LeadSourceInput,
    session: AsyncSession = Depends(get_session),
) -> LeadIngestResult:
    try:
        result = await LeadIngestService(session).ingest(campaign_id, raw, source)
        await session.commit()
        return result
    except DuplicateOperationError as error:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
