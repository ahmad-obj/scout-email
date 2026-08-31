from __future__ import annotations

import json
import re
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scout_email.common.enums import ClaimClass, DraftReviewDecision, MessageState
from scout_email.db.models import (
    Contact,
    DoNotContact,
    EmailDraft,
    EmailDraftClaim,
    EmailReview,
    Evidence,
    Lead,
    OutboundMessage,
)
from scout_email.llm.gateway import LLMGateway
from scout_email.writing.schemas import DraftClaim


_PROMPT_VERSION = "critic:v1"
_QUANTIFIED_LOSS = re.compile(
    r"\b(?:los(?:e|ing)|cost(?:s|ing)?|miss(?:ing)?|leav(?:e|ing))\b[^.!?\n]{0,80}\b\d+(?:\.\d+)?\s*%",
    re.IGNORECASE,
)
_FAKE_FAMILIARITY = re.compile(
    r"\b(?:i(?:'ve| have)\s+been\s+(?:following|watching|tracking)|"
    r"i(?:'ve| have)\s+(?:followed|admired))\b[^.!?\n]{0,100}\b(?:months?|years?)\b",
    re.IGNORECASE,
)


class CriticScores(BaseModel):
    model_config = ConfigDict(extra="forbid")

    specificity: int = Field(ge=0, le=100)
    naturalness: int = Field(ge=0, le=100)
    persuasiveness: int = Field(ge=0, le=100)
    evidence_integrity: int = Field(ge=0, le=100)
    genericness: int = Field(ge=0, le=100)
    spamminess: int = Field(ge=0, le=100)


class CriticModelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: DraftReviewDecision
    scores: CriticScores
    issues: list[str] = Field(default_factory=list)


class CriticReviewResult(CriticModelOutput):
    prompt_version: str
    model_id: str | None = None


def scan_hard_rejection_issues(
    *,
    body: str,
    claims: Sequence[DraftClaim],
) -> list[str]:
    del claims  # Claim/evidence integrity is checked against persisted rows by CriticService.
    issues: list[str] = []
    if _QUANTIFIED_LOSS.search(body):
        issues.append("unsupported_quantified_loss")
    if _FAKE_FAMILIARITY.search(body):
        issues.append("fake_familiarity")
    return issues


class CriticService:
    def __init__(self, session: AsyncSession, *, gateway: LLMGateway) -> None:
        self.session = session
        self.gateway = gateway

    async def review(self, *, draft_id: int) -> CriticReviewResult:
        draft = await self.session.get(EmailDraft, draft_id)
        if draft is None:
            raise ValueError(f"draft {draft_id} does not exist")

        lead = await self.session.get(Lead, draft.lead_id)
        if lead is None:
            raise ValueError(f"lead {draft.lead_id} does not exist")

        claim_rows = list(
            (
                await self.session.scalars(
                    select(EmailDraftClaim)
                    .where(EmailDraftClaim.draft_id == draft.id)
                    .order_by(EmailDraftClaim.id)
                )
            ).all()
        )

        hard_issues = scan_hard_rejection_issues(body=draft.body, claims=[])
        hard_issues.extend(await self._evidence_issues(lead_id=lead.id, claims=claim_rows))
        hard_issues.extend(await self._recipient_safety_issues(lead=lead))
        hard_issues = list(dict.fromkeys(hard_issues))

        if hard_issues:
            result = CriticReviewResult(
                decision=DraftReviewDecision.REJECT,
                scores=CriticScores(
                    specificity=0,
                    naturalness=0,
                    persuasiveness=0,
                    evidence_integrity=0,
                    genericness=100,
                    spamminess=100,
                ),
                issues=hard_issues,
                prompt_version=_PROMPT_VERSION,
                model_id=None,
            )
            await self._persist(draft_id=draft.id, result=result)
            return result

        evidence_context = await self._evidence_context(lead_id=lead.id, claims=claim_rows)
        generation = await self.gateway.generate(
            task="critic",
            context={
                "lead": {
                    "name": lead.name,
                    "category": lead.category,
                    "city": lead.city,
                },
                "draft": {
                    "subject": draft.subject,
                    "body": draft.body,
                },
                "claims": [
                    {
                        "text": claim.claim_text,
                        "claim_class": claim.claim_class,
                        "evidence_ids": self._parse_evidence_ids(claim.evidence_ids_json),
                    }
                    for claim in claim_rows
                ],
                "evidence": evidence_context,
                "review_rules": {
                    "reject_unsupported_claims": True,
                    "rewrite_generic_or_mass_produced_copy": True,
                    "prefer_specific_natural_concise_copy": True,
                },
            },
            response_model=CriticModelOutput,
            prompt_version=_PROMPT_VERSION,
        )

        result = CriticReviewResult(
            **generation.output.model_dump(),
            prompt_version=_PROMPT_VERSION,
            model_id=generation.metadata.model,
        )
        await self._persist(draft_id=draft.id, result=result)
        return result

    async def _evidence_issues(
        self,
        *,
        lead_id: int,
        claims: Sequence[EmailDraftClaim],
    ) -> list[str]:
        referenced_ids: set[int] = set()
        for claim in claims:
            try:
                referenced_ids.update(self._parse_evidence_ids(claim.evidence_ids_json))
            except (TypeError, ValueError, json.JSONDecodeError):
                return ["unknown_evidence"]

        if not referenced_ids:
            return ["unknown_evidence"] if claims else []

        rows = list(
            (
                await self.session.scalars(
                    select(Evidence).where(
                        Evidence.lead_id == lead_id,
                        Evidence.id.in_(referenced_ids),
                    )
                )
            ).all()
        )
        by_id = {row.id: row for row in rows}
        issues: list[str] = []
        if set(by_id) != referenced_ids:
            issues.append("unknown_evidence")
        if any(row.claim_class == ClaimClass.UNVERIFIED.value for row in rows):
            issues.append("unverified_evidence")
        return issues

    async def _recipient_safety_issues(self, *, lead: Lead) -> list[str]:
        contacts = list(
            (
                await self.session.scalars(
                    select(Contact).where(Contact.lead_id == lead.id)
                )
            ).all()
        )
        emails = {contact.normalized_email.casefold() for contact in contacts}

        dnc_rows = list((await self.session.scalars(select(DoNotContact))).all())
        dnc_match = any(
            (row.email is not None and row.email.casefold() in emails)
            or (
                row.domain is not None
                and lead.canonical_domain is not None
                and row.domain.casefold() == lead.canonical_domain.casefold()
            )
            or (
                row.business_name is not None
                and row.business_name.casefold() in {lead.name.casefold(), lead.normalized_name.casefold()}
            )
            for row in dnc_rows
        )

        duplicate = (
            await self.session.scalar(
                select(OutboundMessage.id)
                .where(
                    OutboundMessage.lead_id == lead.id,
                    OutboundMessage.state == MessageState.SENT.value,
                )
                .limit(1)
            )
            is not None
        )

        issues: list[str] = []
        if dnc_match:
            issues.append("do_not_contact")
        if duplicate:
            issues.append("duplicate_outreach")
        return issues

    async def _evidence_context(
        self,
        *,
        lead_id: int,
        claims: Sequence[EmailDraftClaim],
    ) -> list[dict[str, object]]:
        ids = {
            evidence_id
            for claim in claims
            for evidence_id in self._parse_evidence_ids(claim.evidence_ids_json)
        }
        if not ids:
            return []
        rows = list(
            (
                await self.session.scalars(
                    select(Evidence)
                    .where(Evidence.lead_id == lead_id, Evidence.id.in_(ids))
                    .order_by(Evidence.id)
                )
            ).all()
        )
        return [
            {
                "id": row.id,
                "claim": row.claim,
                "claim_class": row.claim_class,
                "confidence": row.confidence,
                "source_type": row.source_type,
                "source_url": row.source_url,
            }
            for row in rows
        ]

    async def _persist(self, *, draft_id: int, result: CriticReviewResult) -> None:
        self.session.add(
            EmailReview(
                draft_id=draft_id,
                decision=result.decision.value,
                scores_json=result.scores.model_dump_json(),
                issues_json=json.dumps(result.issues),
                prompt_version=result.prompt_version,
                model_id=result.model_id,
            )
        )
        await self.session.commit()

    @staticmethod
    def _parse_evidence_ids(raw: str) -> list[int]:
        value = json.loads(raw)
        if not isinstance(value, list) or any(
            not isinstance(item, int) or isinstance(item, bool) or item <= 0
            for item in value
        ):
            raise ValueError("evidence_ids_json must be a list of positive integers")
        return value
