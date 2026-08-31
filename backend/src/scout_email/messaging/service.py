from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from scout_email.approval.service import content_hash
from scout_email.common.enums import MessageState
from scout_email.common.errors import NotFoundError, ScoutEmailError
from scout_email.db.models import (
    Campaign,
    Contact,
    DoNotContact,
    EmailDraft,
    EmailThread,
    Lead,
    OutboundMessage,
    Reply,
    Sender,
)
from scout_email.messaging.eligibility import (
    EligibilityResult,
    EligibilitySnapshot,
    evaluate_send_eligibility,
    normalize_business_identity,
    normalize_domain_identity,
    normalize_email_identity,
)
from scout_email.messaging.schemas import MessageView, ProviderCompletionRequest


class MessagingError(ScoutEmailError):
    pass


class MessagingConfigurationError(MessagingError):
    pass


class MessagingEligibilityError(MessagingError):
    def __init__(self, reasons: list[str]) -> None:
        self.reasons = list(reasons)
        super().__init__(", ".join(self.reasons))


def _message_view(row: OutboundMessage) -> MessageView:
    return MessageView(
        id=row.id,
        state=row.state,
        recipient_email=row.recipient_email,
        subject=row.subject,
        body=row.body,
        provider_message_id=row.gmail_message_id,
        provider_thread_id=row.gmail_thread_id,
    )


def _idempotency_key(
    *,
    campaign_id: int,
    lead_id: int,
    recipient_email: str,
    approved_hash: str,
    sequence_stage: str = "initial",
) -> str:
    raw = (
        f"{campaign_id}|{lead_id}|{recipient_email.casefold()}|"
        f"{approved_hash}|{sequence_stage}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class MessagingService:
    """Fail-closed message dispatcher with mock and guarded n8n Gmail transports."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        send_mode: str | None = None,
        n8n_webhook_url: str | None = None,
        n8n_secret: str | None = None,
        http_client: Any | None = None,
    ) -> None:
        self.session = session
        self.send_mode = (
            send_mode or os.getenv("SCOUT_EMAIL_SEND_MODE", "mock")
        ).strip().casefold()
        self.n8n_webhook_url = (
            n8n_webhook_url
            if n8n_webhook_url is not None
            else os.getenv("SCOUT_EMAIL_N8N_SEND_WEBHOOK_URL")
        )
        self.n8n_secret = (
            n8n_secret
            if n8n_secret is not None
            else os.getenv("SCOUT_EMAIL_N8N_WEBHOOK_SECRET")
        )
        self.http_client = http_client

    def _assert_transport_configuration(self) -> None:
        if self.send_mode not in {"mock", "gmail"}:
            raise MessagingConfigurationError(
                f"unsupported send mode: {self.send_mode or '<empty>'}"
            )
        if self.send_mode == "gmail" and (
            not self.n8n_webhook_url or not self.n8n_secret
        ):
            raise MessagingConfigurationError(
                "gmail mode requires n8n send webhook URL and shared secret"
            )

    async def evaluate_send_eligibility(
        self,
        *,
        draft_id: int,
        recipient_id: int,
        sender_id: int,
        ignore_idempotency_key: str | None = None,
    ) -> EligibilityResult:
        draft = await self.session.get(EmailDraft, draft_id)
        if draft is None:
            raise NotFoundError(f"Draft {draft_id} not found")
        lead = await self.session.get(Lead, draft.lead_id)
        if lead is None:
            raise NotFoundError(f"Lead {draft.lead_id} not found")
        campaign = await self.session.get(Campaign, lead.campaign_id)
        if campaign is None:
            raise NotFoundError(f"Campaign {lead.campaign_id} not found")
        contact = await self.session.get(Contact, recipient_id)
        if contact is None or contact.lead_id != lead.id:
            raise NotFoundError("recipient contact not found for lead")
        sender = await self.session.get(Sender, sender_id)
        if sender is None:
            raise NotFoundError(f"Sender {sender_id} not found")

        normalized_email = normalize_email_identity(contact.normalized_email)
        email_domain = (
            normalize_domain_identity(normalized_email.rsplit("@", 1)[-1])
            if "@" in normalized_email
            else ""
        )
        canonical_domain = normalize_domain_identity(lead.canonical_domain)
        domains = {item for item in (email_domain, canonical_domain) if item}
        business_identity = normalize_business_identity(
            lead.normalized_name or lead.name
        )

        dnc_rows = (await self.session.execute(select(DoNotContact))).scalars().all()
        dnc_match = any(
            (
                bool(row.email)
                and normalize_email_identity(row.email) == normalized_email
            )
            or (
                bool(row.domain)
                and normalize_domain_identity(row.domain) in domains
            )
            or (
                bool(row.business_name)
                and normalize_business_identity(row.business_name) == business_identity
            )
            for row in dnc_rows
        )

        duplicate_query = select(func.count()).select_from(OutboundMessage).where(
            OutboundMessage.campaign_id == campaign.id,
            OutboundMessage.lead_id == lead.id,
            func.lower(OutboundMessage.recipient_email) == normalized_email,
            OutboundMessage.state.in_(
                [
                    MessageState.QUEUED.value,
                    MessageState.SENDING.value,
                    MessageState.SENT.value,
                ]
            ),
        )
        if ignore_idempotency_key:
            duplicate_query = duplicate_query.where(
                OutboundMessage.idempotency_key != ignore_idempotency_key
            )
        duplicate_outreach = bool(await self.session.scalar(duplicate_query))

        human_reply_exists = bool(
            await self.session.scalar(
                select(func.count())
                .select_from(Reply)
                .join(EmailThread, EmailThread.id == Reply.thread_id)
                .where(
                    EmailThread.lead_id == lead.id,
                    EmailThread.campaign_id == campaign.id,
                )
            )
        )

        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        daily_sent_count = int(
            await self.session.scalar(
                select(func.count()).select_from(OutboundMessage).where(
                    OutboundMessage.campaign_id == campaign.id,
                    OutboundMessage.state == MessageState.SENT.value,
                    OutboundMessage.sent_at >= today_start,
                )
            )
            or 0
        )

        approved_hash_matches = bool(
            draft.approved_content_hash
            and draft.approved_content_hash == content_hash(draft.subject, draft.body)
            and draft.approved_at is not None
        )
        return evaluate_send_eligibility(
            EligibilitySnapshot(
                approval_state=draft.approval_state,
                approval_hash_matches=approved_hash_matches,
                contact_verified=contact.state == "VERIFIED",
                dnc_match=dnc_match,
                duplicate_outreach=duplicate_outreach,
                human_reply_exists=human_reply_exists,
                campaign_active=campaign.status == "ACTIVE",
                daily_sent_count=daily_sent_count,
                max_per_day=campaign.max_per_day,
                sender_enabled=sender.enabled,
                sender_healthy=sender.health_state == "HEALTHY",
            )
        )

    async def queue_and_dispatch(
        self,
        *,
        draft_id: int,
        recipient_id: int,
        sender_id: int,
    ) -> MessageView:
        self._assert_transport_configuration()
        draft = await self.session.get(EmailDraft, draft_id)
        if draft is None:
            raise NotFoundError(f"Draft {draft_id} not found")
        lead = await self.session.get(Lead, draft.lead_id)
        if lead is None:
            raise NotFoundError(f"Lead {draft.lead_id} not found")
        contact = await self.session.get(Contact, recipient_id)
        if contact is None or contact.lead_id != lead.id:
            raise NotFoundError("recipient contact not found for lead")
        sender = await self.session.get(Sender, sender_id)
        if sender is None:
            raise NotFoundError(f"Sender {sender_id} not found")

        if not draft.approved_content_hash:
            eligibility = await self.evaluate_send_eligibility(
                draft_id=draft_id, recipient_id=recipient_id, sender_id=sender_id
            )
            raise MessagingEligibilityError(eligibility.reasons)

        key = _idempotency_key(
            campaign_id=lead.campaign_id,
            lead_id=lead.id,
            recipient_email=contact.normalized_email,
            approved_hash=draft.approved_content_hash,
        )
        existing = await self.session.scalar(
            select(OutboundMessage).where(OutboundMessage.idempotency_key == key)
        )
        if existing is not None:
            return _message_view(existing)

        # This is the last state read before immutable message creation/provider handoff.
        eligibility = await self.evaluate_send_eligibility(
            draft_id=draft_id,
            recipient_id=recipient_id,
            sender_id=sender_id,
            ignore_idempotency_key=key,
        )
        if not eligibility.allowed:
            raise MessagingEligibilityError(eligibility.reasons)

        now = datetime.now(UTC)
        initial_state = (
            MessageState.QUEUED.value
            if self.send_mode == "mock"
            else MessageState.SENDING.value
        )
        message = OutboundMessage(
            campaign_id=lead.campaign_id,
            lead_id=lead.id,
            draft_id=draft.id,
            sender_id=sender_id,
            recipient_email=contact.normalized_email,
            subject=draft.subject,
            body=draft.body,
            state=initial_state,
            idempotency_key=key,
            queued_at=now,
        )
        self.session.add(message)
        await self.session.flush()

        if self.send_mode == "mock":
            mock_message_id = f"mock-message-{message.id}"
            mock_thread_id = f"mock-thread-{message.id}"
            message.state = MessageState.SENT.value
            message.gmail_message_id = mock_message_id
            message.gmail_thread_id = mock_thread_id
            message.sent_at = now
            self.session.add(
                EmailThread(
                    lead_id=lead.id,
                    campaign_id=lead.campaign_id,
                    gmail_thread_id=mock_thread_id,
                    followup_stage=0,
                    followup_cancelled=False,
                )
            )
            await self.session.commit()
            return _message_view(message)

        # Commit first so an immediate n8n callback can resolve the backend message ID.
        await self.session.commit()
        payload = {
            "message_id": message.id,
            "recipient": message.recipient_email,
            "sender": sender.email,
            "subject": message.subject,
            "body": message.body,
        }
        headers = {"X-Scout-Email-Secret": self.n8n_secret or ""}
        try:
            response = await self._post_n8n(payload=payload, headers=headers)
        except Exception as error:
            message.state = MessageState.FAILED.value
            await self.session.commit()
            raise MessagingError("n8n Gmail handoff failed") from error
        if response.status_code >= 400:
            message.state = MessageState.FAILED.value
            await self.session.commit()
            raise MessagingError(
                f"n8n Gmail handoff returned HTTP {response.status_code}"
            )
        return _message_view(message)

    async def _post_n8n(self, *, payload: dict[str, Any], headers: dict[str, str]):
        assert self.n8n_webhook_url is not None
        if self.http_client is not None:
            return await self.http_client.post(
                self.n8n_webhook_url,
                json=payload,
                headers=headers,
                timeout=20.0,
            )
        async with httpx.AsyncClient() as client:
            return await client.post(
                self.n8n_webhook_url,
                json=payload,
                headers=headers,
                timeout=20.0,
            )

    async def complete_provider_result(
        self,
        *,
        message_id: int,
        completion: ProviderCompletionRequest,
    ) -> MessageView:
        message = await self.session.get(OutboundMessage, message_id)
        if message is None:
            raise NotFoundError(f"Message {message_id} not found")

        if completion.status == "FAILED":
            if message.state != MessageState.SENT.value:
                message.state = MessageState.FAILED.value
                await self.session.commit()
            return _message_view(message)

        assert completion.provider_message_id is not None
        assert completion.provider_thread_id is not None
        if message.state == MessageState.SENT.value:
            if (
                message.gmail_message_id != completion.provider_message_id
                or message.gmail_thread_id != completion.provider_thread_id
            ):
                raise MessagingError("provider completion conflicts with sent message")
            return _message_view(message)

        existing_thread = await self.session.scalar(
            select(EmailThread).where(
                EmailThread.gmail_thread_id == completion.provider_thread_id
            )
        )
        if existing_thread is not None and (
            existing_thread.lead_id != message.lead_id
            or existing_thread.campaign_id != message.campaign_id
        ):
            raise MessagingError("provider thread already belongs to another lead")

        message.state = MessageState.SENT.value
        message.gmail_message_id = completion.provider_message_id
        message.gmail_thread_id = completion.provider_thread_id
        message.sent_at = datetime.now(UTC)
        if existing_thread is None:
            self.session.add(
                EmailThread(
                    lead_id=message.lead_id,
                    campaign_id=message.campaign_id,
                    gmail_thread_id=completion.provider_thread_id,
                    followup_stage=0,
                    followup_cancelled=False,
                )
            )
        await self.session.commit()
        return _message_view(message)
