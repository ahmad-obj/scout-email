from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from scout_email.common.errors import NotFoundError
from scout_email.db.session import get_session
from scout_email.messaging.schemas import (
    MessageView,
    ProviderCompletionRequest,
    QueueMessageRequest,
)
from scout_email.messaging.service import (
    MessagingConfigurationError,
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
    except (MessagingConfigurationError, MessagingError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from error


@router.post("/{message_id}/provider-result", response_model=MessageView)
async def provider_result(
    message_id: int,
    payload: ProviderCompletionRequest,
    x_scout_email_secret: str | None = Header(default=None, alias="X-Scout-Email-Secret"),
    session: AsyncSession = Depends(get_session),
) -> MessageView:
    expected = os.getenv("SCOUT_EMAIL_N8N_WEBHOOK_SECRET", "")
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="n8n callback secret is not configured",
        )
    if not x_scout_email_secret or not hmac.compare_digest(
        x_scout_email_secret, expected
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid n8n callback secret",
        )
    try:
        return await MessagingService(session).complete_provider_result(
            message_id=message_id,
            completion=payload,
        )
    except NotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except MessagingError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
