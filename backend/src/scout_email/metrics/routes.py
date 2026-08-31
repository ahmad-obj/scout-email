from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from scout_email.common.errors import NotFoundError
from scout_email.db.session import get_session
from scout_email.logging import log_operational_event
from scout_email.metrics.service import CampaignMetricsService

router = APIRouter(prefix="/campaigns", tags=["metrics"])


@router.get("/{campaign_id}/metrics")
async def campaign_metrics(
    campaign_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    try:
        result = await CampaignMetricsService(session).get_metrics(campaign_id)
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    log_operational_event(
        "campaign.metrics.read",
        campaign_id=campaign_id,
        outcome="COMPLETE",
    )
    return result
