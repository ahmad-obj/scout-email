from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from scout_email.campaigns.schemas import CampaignCreate, CampaignResponse
from scout_email.campaigns.service import CampaignService
from scout_email.common.errors import InvalidStateTransitionError, NotFoundError
from scout_email.db.session import get_session
from scout_email.scout.schemas import ScoutEnqueueResponse
from scout_email.scout.service import ScoutService

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


def _not_found(error: NotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))


@router.post("", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(payload: CampaignCreate, session: AsyncSession = Depends(get_session)) -> CampaignResponse:
    return await CampaignService(session).create(payload)


@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(campaign_id: int, session: AsyncSession = Depends(get_session)) -> CampaignResponse:
    try:
        return await CampaignService(session).get(campaign_id)
    except NotFoundError as error:
        raise _not_found(error) from error


@router.post("/{campaign_id}/pause", response_model=CampaignResponse)
async def pause_campaign(campaign_id: int, session: AsyncSession = Depends(get_session)) -> CampaignResponse:
    try:
        return await CampaignService(session).pause(campaign_id)
    except NotFoundError as error:
        raise _not_found(error) from error


@router.post("/{campaign_id}/resume", response_model=CampaignResponse)
async def resume_campaign(campaign_id: int, session: AsyncSession = Depends(get_session)) -> CampaignResponse:
    try:
        return await CampaignService(session).resume(campaign_id)
    except NotFoundError as error:
        raise _not_found(error) from error


@router.post("/{campaign_id}/scout", response_model=ScoutEnqueueResponse, status_code=status.HTTP_202_ACCEPTED)
async def scout_campaign(campaign_id: int, session: AsyncSession = Depends(get_session)) -> ScoutEnqueueResponse:
    try:
        return await ScoutService(session).enqueue_campaign(campaign_id)
    except NotFoundError as error:
        raise _not_found(error) from error
    except InvalidStateTransitionError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
