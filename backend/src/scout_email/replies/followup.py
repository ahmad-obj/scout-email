from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scout_email.campaigns.models import CampaignPolicy
from scout_email.common.enums import (
    ApprovalState,
    ClaimClass,
    ContactState,
    DraftReviewDecision,
    FollowupState,
    MessageState,
)
from scout_email.db.models import (
    Bounce,
    Campaign,
    Contact,
    DoNotContact,
    EmailDraft,
    EmailDraftClaim,
    EmailReview,
    EmailThread,
    Evidence,
    Followup,
    Lead,
    OutboundMessage,
    Reply,
    ResearchReport,
    Strategy,
)
from scout_email.llm.gateway import LLMGateway
from scout_email.messaging.eligibility import (
    normalize_business_identity,
    normalize_domain_identity,
    normalize_email_identity,
)
from scout_email.writing.playbook import WritingPlaybook
from scout_email.writing.schemas import DraftClaim


FOLLOWUP_WRITER_PROMPT_VERSION = "followup_writer:v1"
FOLLOWUP_CRITIC_PROMPT_VERSION = "followup_critic:v1"


@dataclass(frozen=True, slots=True)
class FollowupEligibilitySnapshot:
    current_stage: int
    elapsed_seconds: float
    required_delay_seconds: float
    campaign_active: bool
    thread_cancelled: bool
    contact_verified: bool
    dnc_match: bool
    reply_exists: bool
    hard_bounce_exists: bool
    followup_stage_one_exists: bool


@dataclass(frozen=True, slots=True)
class FollowupEligibilityResult:
    allowed: bool
    reasons: list[str]


@dataclass(frozen=True, slots=True)
class PreparedFollowup:
    followup_id: int
    draft_id: int
    stage: int
    state: FollowupState
    critic_decision: DraftReviewDecision


class FollowupPreparationError(RuntimeError):
    """Raised when a follow-up cannot safely be prepared."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FollowupWriterOutput(_StrictModel):
    strategy: Literal[
        "SHORT_BUMP",
        "NEW_OBSERVATION",
        "ADD_CONCRETE_IDEA",
        "NO_FOLLOWUP",
    ]
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=8000)
    claims: list[DraftClaim] = Field(min_length=1)


class FollowupCriticOutput(_StrictModel):
    decision: DraftReviewDecision
    issues: list[str] = Field(default_factory=list)


def evaluate_followup_eligibility(
    snapshot: FollowupEligibilitySnapshot,
) -> FollowupEligibilityResult:
    reasons: list[str] = []
    if snapshot.current_stage >= 1:
        reasons.append("max_stage_reached")
    if snapshot.elapsed_seconds < snapshot.required_delay_seconds:
        reasons.append("followup_not_due")
    if not snapshot.campaign_active:
        reasons.append("campaign_paused")
    if snapshot.thread_cancelled:
        reasons.append("thread_cancelled")
    if not snapshot.contact_verified:
        reasons.append("contact_not_verified")
    if snapshot.dnc_match:
        reasons.append("do_not_contact")
    if snapshot.reply_exists:
        reasons.append("reply_exists")
    if snapshot.hard_bounce_exists:
        reasons.append("hard_bounce_exists")
    if snapshot.followup_stage_one_exists:
        reasons.append("followup_already_exists")
    return FollowupEligibilityResult(allowed=not reasons, reasons=reasons)


class FollowupService:
    """Prepare the single V1 follow-up without ever sending it automatically.

    Safety ordering is deliberate: current database eligibility is checked first,
    then the model output is constrained to persisted evidence, then an independent
    critic must approve it. Only after all of those checks pass are the draft and
    stage-1 follow-up rows persisted in PENDING_APPROVAL state.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        gateway: LLMGateway,
        playbook: WritingPlaybook,
    ) -> None:
        self.session = session
        self.gateway = gateway
        self.playbook = playbook

    async def prepare(self, *, thread_id: int, now: datetime | None = None) -> PreparedFollowup:
        now = self._as_utc(now or datetime.now(UTC))
        thread = await self.session.get(EmailThread, thread_id)
        if thread is None:
            raise FollowupPreparationError("thread_not_found")

        lead = await self.session.get(Lead, thread.lead_id)
        campaign = await self.session.get(Campaign, thread.campaign_id)
        if lead is None or campaign is None:
            raise FollowupPreparationError("thread_context_missing")

        policy_row = await self.session.get(CampaignPolicy, campaign.id)
        if policy_row is None:
            raise FollowupPreparationError("followup_policy_missing")
        try:
            policy = json.loads(policy_row.follow_up_json)
        except (TypeError, json.JSONDecodeError) as error:
            raise FollowupPreparationError("followup_policy_invalid") from error
        if not isinstance(policy, dict):
            raise FollowupPreparationError("followup_policy_invalid")
        if policy.get("enabled") is not True or int(policy.get("max_followups", 0)) < 1:
            raise FollowupPreparationError("followup_disabled")
        try:
            delay_days = int(policy.get("delay_days", 4))
        except (TypeError, ValueError) as error:
            raise FollowupPreparationError("followup_policy_invalid") from error
        if delay_days < 1:
            raise FollowupPreparationError("followup_policy_invalid")

        original = await self.session.scalar(
            select(OutboundMessage)
            .where(
                OutboundMessage.gmail_thread_id == thread.gmail_thread_id,
                OutboundMessage.state == MessageState.SENT.value,
            )
            .order_by(OutboundMessage.sent_at.desc(), OutboundMessage.id.desc())
            .limit(1)
        )
        if original is None or original.sent_at is None:
            raise FollowupPreparationError("sent_message_missing")

        contact = await self.session.scalar(
            select(Contact)
            .where(
                Contact.lead_id == lead.id,
                Contact.normalized_email == normalize_email_identity(original.recipient_email),
                Contact.state == ContactState.VERIFIED.value,
            )
            .limit(1)
        )
        reply_exists = (
            await self.session.scalar(
                select(Reply.id).where(Reply.thread_id == thread.id).limit(1)
            )
            is not None
        )
        hard_bounce_exists = (
            await self.session.scalar(
                select(Bounce.id)
                .where(
                    Bounce.outbound_message_id == original.id,
                    Bounce.bounce_type == "HARD",
                )
                .limit(1)
            )
            is not None
        )
        followup_exists = (
            await self.session.scalar(
                select(Followup.id)
                .where(Followup.thread_id == thread.id, Followup.stage == 1)
                .limit(1)
            )
            is not None
        )
        dnc_match = await self._dnc_match(
            lead=lead,
            recipient_email=original.recipient_email,
        )

        sent_at = self._as_utc(original.sent_at)
        eligibility = evaluate_followup_eligibility(
            FollowupEligibilitySnapshot(
                current_stage=thread.followup_stage,
                elapsed_seconds=max(0.0, (now - sent_at).total_seconds()),
                required_delay_seconds=float(delay_days * 86400),
                campaign_active=campaign.status == "ACTIVE",
                thread_cancelled=thread.followup_cancelled,
                contact_verified=contact is not None,
                dnc_match=dnc_match,
                reply_exists=reply_exists,
                hard_bounce_exists=hard_bounce_exists,
                followup_stage_one_exists=followup_exists,
            )
        )
        if not eligibility.allowed:
            raise FollowupPreparationError(",".join(eligibility.reasons))

        evidence_rows = list(
            (
                await self.session.scalars(
                    select(Evidence)
                    .where(
                        Evidence.lead_id == lead.id,
                        Evidence.claim_class != ClaimClass.UNVERIFIED.value,
                    )
                    .order_by(Evidence.id)
                )
            ).all()
        )
        if not evidence_rows:
            raise FollowupPreparationError("no_safe_evidence")
        evidence_by_id = {row.id: row for row in evidence_rows}

        report = await self.session.scalar(
            select(ResearchReport)
            .where(ResearchReport.lead_id == lead.id, ResearchReport.status == "COMPLETE")
            .order_by(ResearchReport.id.desc())
            .limit(1)
        )
        strategy = await self.session.scalar(
            select(Strategy)
            .where(Strategy.lead_id == lead.id, Strategy.decision == "CONTACT")
            .order_by(Strategy.id.desc())
            .limit(1)
        )
        if report is None or strategy is None:
            raise FollowupPreparationError("research_or_strategy_missing")

        context = {
            "lead": {
                "name": lead.name,
                "category": lead.category,
                "city": lead.city,
            },
            "original_message": {
                "gmail_thread_id": thread.gmail_thread_id,
                "subject": original.subject,
                "body": original.body,
                "recipient_email": original.recipient_email,
                "sent_at": sent_at.isoformat(),
            },
            "research_dossier": json.loads(report.dossier_json),
            "persuasion_brief": json.loads(strategy.persuasion_brief_json),
            "allowed_evidence": [
                {
                    "id": row.id,
                    "claim": row.claim,
                    "claim_class": row.claim_class,
                    "source_type": row.source_type,
                    "source_url": row.source_url,
                    "confidence": row.confidence,
                }
                for row in evidence_rows
            ],
            "weberaise_context": self.playbook.company_context,
            "writing_rules": [self.playbook.writing_rules, self.playbook.cta_rules],
            "followup_rules": {
                "max_stage": 1,
                "keep_same_thread": True,
                "do_not_repeat_initial_email": True,
                "prefer_new_value_or_short_bump": True,
            },
        }
        writer_generation = await self.gateway.generate(
            task="followup_writer",
            context=context,
            response_model=FollowupWriterOutput,
            prompt_version=FOLLOWUP_WRITER_PROMPT_VERSION,
        )
        generated = writer_generation.output
        if generated.strategy == "NO_FOLLOWUP":
            raise FollowupPreparationError("model_recommends_no_followup")
        self._assert_no_banned_phrase(generated.subject, generated.body)

        referenced_ids = {
            evidence_id
            for claim in generated.claims
            for evidence_id in claim.evidence_ids
        }
        if not referenced_ids or not referenced_ids.issubset(evidence_by_id):
            raise FollowupPreparationError("unknown_or_unsafe_evidence")

        critic_generation = await self.gateway.generate(
            task="followup_critic",
            context={
                "lead": context["lead"],
                "original_message": context["original_message"],
                "draft": {
                    "subject": generated.subject,
                    "body": generated.body,
                    "strategy": generated.strategy,
                },
                "claims": [claim.model_dump(mode="json") for claim in generated.claims],
                "evidence": [
                    {
                        "id": evidence_id,
                        "claim": evidence_by_id[evidence_id].claim,
                        "claim_class": evidence_by_id[evidence_id].claim_class,
                        "confidence": evidence_by_id[evidence_id].confidence,
                    }
                    for evidence_id in sorted(referenced_ids)
                ],
                "review_rules": {
                    "reject_unsupported_claims": True,
                    "reject_repetition_of_initial_message": True,
                    "reject_pushy_or_generic_followups": True,
                    "require_new_value_or_legitimate_short_bump": True,
                },
            },
            response_model=FollowupCriticOutput,
            prompt_version=FOLLOWUP_CRITIC_PROMPT_VERSION,
        )
        critic = critic_generation.output
        if critic.decision != DraftReviewDecision.APPROVE:
            raise FollowupPreparationError(
                "critic_" + critic.decision.value.casefold()
            )

        draft = EmailDraft(
            lead_id=lead.id,
            strategy_id=strategy.id,
            subject=generated.subject,
            body=generated.body,
            writer_prompt_version=FOLLOWUP_WRITER_PROMPT_VERSION,
            model_id=writer_generation.metadata.model,
            approval_state=ApprovalState.PENDING.value,
        )
        self.session.add(draft)
        await self.session.flush()
        for claim in generated.claims:
            self.session.add(
                EmailDraftClaim(
                    draft_id=draft.id,
                    claim_text=claim.text,
                    claim_class=claim.claim_class.value,
                    evidence_ids_json=json.dumps(claim.evidence_ids),
                )
            )
        self.session.add(
            EmailReview(
                draft_id=draft.id,
                decision=critic.decision.value,
                scores_json="{}",
                issues_json=json.dumps(critic.issues),
                prompt_version=FOLLOWUP_CRITIC_PROMPT_VERSION,
                model_id=critic_generation.metadata.model,
            )
        )
        followup = Followup(
            thread_id=thread.id,
            draft_id=draft.id,
            stage=1,
            state=FollowupState.PENDING_APPROVAL.value,
            due_at=now,
        )
        self.session.add(followup)
        await self.session.flush()
        await self.session.commit()
        return PreparedFollowup(
            followup_id=followup.id,
            draft_id=draft.id,
            stage=followup.stage,
            state=FollowupState(followup.state),
            critic_decision=critic.decision,
        )

    async def _dnc_match(self, *, lead: Lead, recipient_email: str) -> bool:
        email = normalize_email_identity(recipient_email)
        domain = normalize_domain_identity(lead.canonical_domain)
        if not domain and "@" in email:
            domain = normalize_domain_identity(email.rsplit("@", 1)[-1])
        business = normalize_business_identity(lead.normalized_name or lead.name)
        rows = list((await self.session.scalars(select(DoNotContact))).all())
        return any(
            (email and normalize_email_identity(row.email) == email)
            or (domain and normalize_domain_identity(row.domain) == domain)
            or (
                business
                and normalize_business_identity(row.business_name) == business
            )
            for row in rows
        )

    def _assert_no_banned_phrase(self, subject: str, body: str) -> None:
        rendered = f"{subject}\n{body}".casefold()
        for phrase in self.playbook.banned_phrases:
            normalized = phrase.strip().casefold()
            if normalized and normalized in rendered:
                raise FollowupPreparationError("banned_phrase")

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
