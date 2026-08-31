from __future__ import annotations

import json

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from scout_email.common.enums import FollowupState, JobState, ReplyClass
from scout_email.common.errors import NotFoundError
from scout_email.db.models import EmailThread, Followup, Job, Reply
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
