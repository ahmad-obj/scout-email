from __future__ import annotations

import hmac
import os
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from scout_email.common.errors import NotFoundError
from scout_email.db.session import get_session
from scout_email.llm.gateway import LLMGateway
from scout_email.llm.providers.gemini import GeminiProvider
from scout_email.llm.providers.ollama import OllamaProvider
from scout_email.replies.classifier import GatewayReplyClassifier, ReplyClassifier
from scout_email.replies.schemas import ReplySyncRequest, ReplyView
from scout_email.replies.service import ReplyClassifierUnavailable, ReplyService
from scout_email.settings import settings

router = APIRouter(prefix="/replies", tags=["replies"])


async def get_reply_classifier() -> AsyncIterator[ReplyClassifier | None]:
    provider_name = os.getenv("SCOUT_EMAIL_REPLY_CLASSIFIER_PROVIDER", "").strip().lower()
    model = os.getenv("SCOUT_EMAIL_REPLY_CLASSIFIER_MODEL", "").strip()
    if not provider_name and not model:
        yield None
        return
    if not provider_name or not model:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="reply classifier provider and model must both be configured",
        )

    if provider_name == "gemini":
        if not settings.gemini_api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Gemini API key is not configured",
            )
        provider = GeminiProvider(api_key=settings.gemini_api_key, model=model)
    elif provider_name == "ollama":
        provider = OllamaProvider(model=model, base_url=settings.ollama_base_url)
    else:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="unsupported reply classifier provider",
        )

    gateway = LLMGateway(
        providers={provider.name: provider},
        task_routes={"reply_classifier": provider.name},
    )
    try:
        yield GatewayReplyClassifier(gateway)
    finally:
        await provider.aclose()


def _require_n8n_secret(provided: str | None) -> None:
    expected = os.getenv("SCOUT_EMAIL_N8N_WEBHOOK_SECRET", "")
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="n8n webhook secret is not configured",
        )
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid n8n webhook secret",
        )


@router.post("/sync", response_model=ReplyView)
async def sync_reply(
    payload: ReplySyncRequest,
    x_scout_email_secret: str | None = Header(default=None, alias="X-Scout-Email-Secret"),
    session: AsyncSession = Depends(get_session),
    classifier: ReplyClassifier | None = Depends(get_reply_classifier),
) -> ReplyView:
    _require_n8n_secret(x_scout_email_secret)
    try:
        return await ReplyService(session, classifier=classifier).sync(payload)
    except NotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ReplyClassifierUnavailable as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
