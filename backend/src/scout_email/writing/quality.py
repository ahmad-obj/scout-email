from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scout_email.common.enums import DraftReviewDecision
from scout_email.db.models import EmailDraft
from scout_email.writing.critic import CriticService
from scout_email.writing.writer import WriterService


@dataclass(frozen=True, slots=True)
class QualityLoopResult:
    final_decision: DraftReviewDecision
    draft_id: int
    rewrite_count: int
    requires_human_review: bool
    issues: tuple[str, ...]


class WriterCriticQualityLoop:
    def __init__(
        self,
        session: AsyncSession,
        *,
        writer: WriterService,
        critic: CriticService,
        max_rewrites: int = 2,
    ) -> None:
        if max_rewrites < 0:
            raise ValueError("max_rewrites must not be negative")
        self.session = session
        self.writer = writer
        self.critic = critic
        self.max_rewrites = max_rewrites

    async def run(self, *, lead_id: int) -> QualityLoopResult:
        rewrite_count = 0
        critic_feedback: list[str] | None = None

        while True:
            await self.writer.write(
                lead_id=lead_id,
                critic_feedback=critic_feedback,
            )
            draft = await self.session.scalar(
                select(EmailDraft)
                .where(EmailDraft.lead_id == lead_id)
                .order_by(EmailDraft.id.desc())
                .limit(1)
            )
            if draft is None:
                raise RuntimeError("Writer completed without persisting a draft")

            review = await self.critic.review(draft_id=draft.id)
            if review.decision == DraftReviewDecision.APPROVE:
                return QualityLoopResult(
                    final_decision=review.decision,
                    draft_id=draft.id,
                    rewrite_count=rewrite_count,
                    requires_human_review=False,
                    issues=tuple(review.issues),
                )
            if review.decision == DraftReviewDecision.REJECT:
                return QualityLoopResult(
                    final_decision=review.decision,
                    draft_id=draft.id,
                    rewrite_count=rewrite_count,
                    requires_human_review=False,
                    issues=tuple(review.issues),
                )
            if rewrite_count >= self.max_rewrites:
                return QualityLoopResult(
                    final_decision=review.decision,
                    draft_id=draft.id,
                    rewrite_count=rewrite_count,
                    requires_human_review=True,
                    issues=tuple(review.issues),
                )

            rewrite_count += 1
            critic_feedback = list(review.issues)
