from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from scout_email.common.errors import NotFoundError
from scout_email.db.session import get_session
from scout_email.messaging.schemas import MessageView, QueueMessageRequest
from scout_email.messaging.service import (
    MessagingEligibilityError,
    MessagingError,
    MessagingService,
)

router = APIRouter(prefix="/messages", tags=["messages"])


@router.post(
    "/{draft_id}/queue",
    response_model=MessageView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def queue_message(
    draft_id: int,
    payload: QueueMessageRequest,
    session: AsyncSession = Depends(get_session),
) -> MessageView:
    try:
        return await MessagingService(session).queue_and_dispatch(
            draft_id=draft_id,
            recipient_id=payload.recipient_id,
            sender_id=payload.sender_id,
        )
    except NotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except MessagingEligibilityError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reason": "send_ineligible", "blocks": error.reasons},
        ) from error
    except MessagingError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from error
