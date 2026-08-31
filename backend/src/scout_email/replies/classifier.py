from __future__ import annotations

from typing import Protocol

from scout_email.common.enums import ReplyClass
from scout_email.llm.gateway import LLMGateway
from scout_email.replies.schemas import ReplyIntelligence, ReplySyncRequest


class ReplyClassifier(Protocol):
    async def classify(self, request: ReplySyncRequest) -> ReplyIntelligence: ...


class GatewayReplyClassifier:
    def __init__(self, gateway: LLMGateway) -> None:
        self.gateway = gateway

    async def classify(self, request: ReplySyncRequest) -> ReplyIntelligence:
        result = await self.gateway.generate(
            task="reply_classifier",
            context={
                "from_email": request.from_email,
                "subject": request.subject,
                "body": request.body,
            },
            response_model=ReplyIntelligence,
            prompt_version="reply_classifier:v1",
        )
        return result.output


def _header(request: ReplySyncRequest, name: str) -> str:
    target = name.casefold()
    for key, value in request.headers.items():
        if key.casefold() == target:
            return value.strip()
    return ""


def preclassify_reply(request: ReplySyncRequest) -> ReplyIntelligence | None:
    sender = request.from_email.casefold()
    subject = request.subject.casefold()
    body = request.body.casefold()
    auto_submitted = _header(request, "Auto-Submitted").casefold()

    if (
        sender.startswith("mailer-daemon@")
        or sender.startswith("postmaster@")
        or "delivery status notification" in subject
        or "undeliverable" in subject
        or "mail delivery failed" in subject
    ):
        return ReplyIntelligence(
            classification=ReplyClass.BOUNCE,
            summary="The message appears to be a delivery failure notification.",
            intent_score=0.0,
            questions=[],
            recommended_action="inspect_bounce",
        )

    if (
        (auto_submitted and auto_submitted != "no")
        or "automatic reply" in subject
        or "auto reply" in subject
        or "out of office" in subject
        or "out of the office" in body
    ):
        return ReplyIntelligence(
            classification=ReplyClass.AUTO_REPLY,
            summary="The message appears to be an automatic reply.",
            intent_score=0.0,
            questions=[],
            recommended_action="wait_for_human_reply",
        )

    unsubscribe_phrases = (
        "unsubscribe",
        "remove me from your list",
        "do not contact me",
        "don't contact me",
        "stop emailing me",
        "stop contacting me",
    )
    if any(phrase in body for phrase in unsubscribe_phrases):
        return ReplyIntelligence(
            classification=ReplyClass.UNSUBSCRIBE,
            summary="The recipient explicitly requested no further outreach.",
            intent_score=0.0,
            questions=[],
            recommended_action="suppress_contact",
        )

    return None
