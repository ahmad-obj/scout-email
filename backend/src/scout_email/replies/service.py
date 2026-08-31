from __future__ import annotations

import json

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from scout_email.common.enums import (
    ContactState,
    FollowupState,
    JobState,
    LeadState,
    ReplyClass,
)
from scout_email.common.errors import NotFoundError
from scout_email.db.models import (
    Bounce,
    Contact,
    DoNotContact,
    EmailThread,
    Followup,
    Job,
    Lead,
    OutboundMessage,
    Reply,
)
from scout_email.messaging.eligibility import (
    normalize_business_identity,
    normalize_domain_identity,
    normalize_email_identity,
)
from scout_email.replies.classifier import ReplyClassifier, preclassify_reply
from scout_email.replies.models import ReplyIntelligenceRecord
from scout_email.replies.schemas import ReplyIntelligence, ReplySyncRequest, ReplyView


class ReplyClassifierUnavailable(RuntimeError):
    pass


class ReplyService:
    def __init__(self, session: AsyncSession, *, classifier: ReplyClassifier | None = None) -> None:
        self.session = session
        self.classifier = classifier

    async def sync(self, request: ReplySyncRequest) -> ReplyView:
        existing = await self._existing(request.gmail_message_id)
        if existing is not None:
            return existing

        thread = (
            await self.session.execute(
                select(EmailThread).where(
                    EmailThread.gmail_thread_id == request.gmail_thread_id
                )
            )
        ).scalar_one_or_none()
        if thread is None:
            raise NotFoundError(
                f"Email thread {request.gmail_thread_id!r} was not found"
            )

        intelligence = preclassify_reply(request)
        if intelligence is None:
            if self.classifier is None:
                raise ReplyClassifierUnavailable(
                    "structured reply classifier is not configured"
                )
            intelligence = await self.classifier.classify(request)

        reply = Reply(
            thread_id=thread.id,
            gmail_message_id=request.gmail_message_id,
            classification=intelligence.classification.value,
            summary=intelligence.summary,
            raw_text=request.body,
            received_at=request.received_at,
        )
        self.session.add(reply)
        try:
            await self.session.flush()
        except IntegrityError:
            await self.session.rollback()
            existing = await self._existing(request.gmail_message_id)
            if existing is not None:
                return existing
            raise

        record = ReplyIntelligenceRecord(
            reply_id=reply.id,
            intent_score=intelligence.intent_score,
            questions_json=json.dumps(
                intelligence.questions,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            recommended_action=intelligence.recommended_action,
        )
        self.session.add(record)

        if intelligence.classification == ReplyClass.UNSUBSCRIBE:
            await self._apply_unsubscribe(thread=thread, request=request)
        elif intelligence.classification == ReplyClass.BOUNCE:
            await self._apply_hard_bounce(thread=thread, request=request)

        if intelligence.classification != ReplyClass.AUTO_REPLY:
            await self._cancel_followup_work(
                thread=thread,
                classification=intelligence.classification,
            )

        await self.session.commit()
        return await self._view(reply)

    async def _existing(self, gmail_message_id: str) -> ReplyView | None:
        reply = (
            await self.session.execute(
                select(Reply).where(Reply.gmail_message_id == gmail_message_id)
            )
        ).scalar_one_or_none()
        if reply is None:
            return None
        return await self._view(reply)

    async def _view(self, reply: Reply) -> ReplyView:
        record = (
            await self.session.execute(
                select(ReplyIntelligenceRecord).where(
                    ReplyIntelligenceRecord.reply_id == reply.id
                )
            )
        ).scalar_one_or_none()
        return ReplyView(
            id=reply.id,
            thread_id=reply.thread_id,
            gmail_message_id=reply.gmail_message_id,
            classification=ReplyClass(reply.classification),
            summary=reply.summary,
            intent_score=record.intent_score if record is not None else 0.0,
            questions=record.questions if record is not None else [],
            recommended_action=(
                record.recommended_action if record is not None else "review_manually"
            ),
            received_at=reply.received_at,
        )

    async def _apply_unsubscribe(
        self,
        *,
        thread: EmailThread,
        request: ReplySyncRequest,
    ) -> None:
        lead = await self.session.get(Lead, thread.lead_id)
        if lead is None:
            raise NotFoundError(f"Lead {thread.lead_id} not found")

        email = normalize_email_identity(request.from_email)
        email_domain = (
            normalize_domain_identity(email.rsplit("@", 1)[-1]) if "@" in email else ""
        )
        domain = normalize_domain_identity(lead.canonical_domain) or email_domain
        business = normalize_business_identity(lead.normalized_name or lead.name)

        rows = (await self.session.execute(select(DoNotContact))).scalars().all()
        already_suppressed = any(
            (email and normalize_email_identity(row.email) == email)
            or (domain and normalize_domain_identity(row.domain) == domain)
            or (
                business
                and normalize_business_identity(row.business_name) == business
            )
            for row in rows
        )
        if not already_suppressed:
            self.session.add(
                DoNotContact(
                    email=email or None,
                    domain=domain or None,
                    business_name=business or None,
                    reason="recipient_unsubscribe",
                    source="reply",
                )
            )

    async def _apply_hard_bounce(
        self,
        *,
        thread: EmailThread,
        request: ReplySyncRequest,
    ) -> None:
        message = (
            await self.session.execute(
                select(OutboundMessage)
                .where(OutboundMessage.gmail_thread_id == thread.gmail_thread_id)
                .order_by(OutboundMessage.sent_at.desc(), OutboundMessage.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if message is None:
            return

        target_email = normalize_email_identity(message.recipient_email)
        contacts = (
            await self.session.execute(
                select(Contact).where(Contact.lead_id == thread.lead_id)
            )
        ).scalars().all()
        bounced_contact = next(
            (
                contact
                for contact in contacts
                if normalize_email_identity(contact.normalized_email or contact.email)
                == target_email
            ),
            None,
        )
        if bounced_contact is not None:
            bounced_contact.state = ContactState.INVALID.value

        existing_bounce = await self.session.scalar(
            select(Bounce).where(
                Bounce.outbound_message_id == message.id,
                func.lower(Bounce.email) == target_email,
            )
        )
        if existing_bounce is None:
            self.session.add(
                Bounce(
                    outbound_message_id=message.id,
                    email=target_email,
                    bounce_type="HARD",
                    diagnostic=request.body[:4000] or None,
                )
            )

        lead = await self.session.get(Lead, thread.lead_id)
        if lead is None:
            raise NotFoundError(f"Lead {thread.lead_id} not found")
        if not any(contact.state == ContactState.VERIFIED.value for contact in contacts):
            lead.state = LeadState.NO_CONTACT.value

    async def _cancel_followup_work(
        self,
        *,
        thread: EmailThread,
        classification: ReplyClass,
    ) -> None:
        if classification == ReplyClass.BOUNCE:
            reason = "inbound_bounce"
        elif classification == ReplyClass.UNSUBSCRIBE:
            reason = "inbound_unsubscribe"
        else:
            reason = "inbound_human_reply"

        thread.followup_cancelled = True
        await self.session.execute(
            update(Followup)
            .where(
                Followup.thread_id == thread.id,
                Followup.state.not_in(
                    [FollowupState.SENT.value, FollowupState.CANCELLED.value]
                ),
            )
            .values(
                state=FollowupState.CANCELLED.value,
                cancelled_reason=reason,
            )
        )
        await self.session.execute(
            update(Job)
            .where(
                Job.job_type == "followup",
                Job.entity_type == "email_thread",
                Job.entity_id == thread.id,
                Job.state.in_([JobState.PENDING.value, JobState.RETRY.value]),
            )
            .values(
                state=JobState.SKIPPED.value,
                result_json=json.dumps(
                    {"reason": reason},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                run_after=None,
            )
        )
