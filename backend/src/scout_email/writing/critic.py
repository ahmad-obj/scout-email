from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Literal

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
from scout_email.writing.models import EmailReviewAudit
from scout_email.writing.playbook import WritingPlaybook
from scout_email.writing.schemas import DraftClaim


_PROMPT_VERSION = "critic:v4"
_QUANTIFIED_LOSS = re.compile(
    r"\b(?:los(?:e|ing)|cost(?:s|ing)?|miss(?:ing)?|leav(?:e|ing))\b[^.!?\n]{0,80}\b\d+(?:\.\d+)?\s*%",
    re.IGNORECASE,
)
_FAKE_FAMILIARITY = re.compile(
    r"\b(?:i(?:'ve| have)\s+been\s+(?:following|watching|tracking)|"
    r"i(?:'ve| have)\s+(?:followed|admired))\b[^.!?\n]{0,100}\b(?:months?|years?)\b",
    re.IGNORECASE,
)
_GRATUITOUS_PRAISE = re.compile(
    r"\b(?:impressed\s+by|great\s+foundation|vital\s+resource|"
    r"(?:depth|information)[^.!?\n]{0,60}\b(?:excellent|outstanding|amazing|fantastic))\b",
    re.IGNORECASE,
)
_UNSUPPORTED_AUDIENCE_PERSONA = re.compile(
    r"\b(?:security[- ]conscious\s+(?:customers?|users?|visitors?)|"
    r"busy\s+(?:professionals?|customers?|users?)|"
    r"mobile\s+shoppers?|"
    r"(?:customers?|users?|professionals?)\s+on\s+the\s+go)\b",
    re.IGNORECASE,
)

AssertionType = Literal[
    "PROSPECT_FACT",
    "PROSPECT_INFERENCE",
    "WEBERAISE_SELF_CLAIM",
]
AssertionVerdict = Literal[
    "ENTAILED",
    "REASONABLE_INFERENCE",
    "SEMANTIC_EXPANSION",
    "UNSUPPORTED",
]


class CriticScores(BaseModel):
    model_config = ConfigDict(extra="forbid")

    specificity: int = Field(ge=0, le=100)
    naturalness: int = Field(ge=0, le=100)
    persuasiveness: int = Field(ge=0, le=100)
    evidence_integrity: int = Field(ge=0, le=100)
    genericness: int = Field(ge=0, le=100)
    spamminess: int = Field(ge=0, le=100)


class AssertionAudit(BaseModel):
    """One model-audited material assertion from the rendered email."""

    model_config = ConfigDict(extra="forbid")

    body_assertion: str = Field(min_length=1)
    assertion_type: AssertionType
    ledger_claim: str | None
    evidence_ids: list[int]
    company_context_quote: str | None
    verdict: AssertionVerdict
    explanation: str = Field(min_length=1)


class CriticModelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: DraftReviewDecision
    scores: CriticScores
    issues: list[str] = Field(default_factory=list)
    assertion_audits: list[AssertionAudit]
    coverage_complete: bool
    copy_abstractions: list[str]


class CriticReviewResult(CriticModelOutput):
    prompt_version: str
    model_id: str | None = None
    model_decision: DraftReviewDecision | None = None


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
    if _GRATUITOUS_PRAISE.search(body):
        issues.append("gratuitous_praise")
    return issues


def scan_quality_issues(
    *,
    subject: str,
    body: str,
    rejected_patterns: Sequence[Mapping[str, object]] = (),
) -> list[str]:
    """Return rewrite-level copy issues that should prevent automatic approval."""
    rendered = f"{subject}\n{body}"
    folded = rendered.casefold()
    issues: list[str] = []

    if _UNSUPPORTED_AUDIENCE_PERSONA.search(rendered):
        issues.append("unsupported_audience_persona")

    for item in rejected_patterns:
        pattern = item.get("pattern")
        if not isinstance(pattern, str):
            continue
        normalized = pattern.strip().casefold()
        if normalized and normalized in folded:
            issues.append(f"rejected_pattern:{pattern.strip()}")

    return list(dict.fromkeys(issues))


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


class CriticService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        gateway: LLMGateway,
        playbook: WritingPlaybook | None = None,
    ) -> None:
        self.session = session
        self.gateway = gateway
        self.playbook = playbook

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
                assertion_audits=[],
                coverage_complete=False,
                copy_abstractions=[],
                prompt_version=_PROMPT_VERSION,
                model_id=None,
                model_decision=None,
            )
            await self._persist(draft_id=draft.id, result=result)
            return result

        rejected_patterns = list(self.playbook.rejected_patterns) if self.playbook else []
        quality_issues = scan_quality_issues(
            subject=draft.subject,
            body=draft.body,
            rejected_patterns=rejected_patterns,
        )
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
                "deterministic_quality_issues": quality_issues,
                "review_rules": {
                    "reject_unsupported_claims": True,
                    "rewrite_generic_or_mass_produced_copy": True,
                    "prefer_specific_natural_concise_copy": True,
                    "audit_complete_body_against_claim_ledger": True,
                    "require_claim_evidence_entailment": True,
                    "forbid_unsupported_audience_personas": True,
                    "require_weberaise_claims_from_company_context": True,
                    "prefer_plain_language_over_agency_abstractions": True,
                    "require_structured_assertion_audit": True,
                    "writing_rules": self.playbook.writing_rules if self.playbook else "",
                    "company_context": self.playbook.company_context if self.playbook else "",
                    "cta_rules": self.playbook.cta_rules if self.playbook else "",
                    "rejected_patterns": rejected_patterns,
                },
            },
            response_model=CriticModelOutput,
            prompt_version=_PROMPT_VERSION,
        )

        structured_issues = self._structured_audit_issues(
            output=generation.output,
            claim_rows=claim_rows,
            evidence_context=evidence_context,
            company_context=self.playbook.company_context if self.playbook else "",
        )
        all_quality_issues = list(
            dict.fromkeys([*quality_issues, *structured_issues])
        )

        decision = generation.output.decision
        if all_quality_issues and decision == DraftReviewDecision.APPROVE:
            decision = DraftReviewDecision.REWRITE
        issues = list(
            dict.fromkeys([*generation.output.issues, *all_quality_issues])
        )
        result = CriticReviewResult(
            decision=decision,
            scores=generation.output.scores,
            issues=issues,
            assertion_audits=generation.output.assertion_audits,
            coverage_complete=generation.output.coverage_complete,
            copy_abstractions=generation.output.copy_abstractions,
            prompt_version=_PROMPT_VERSION,
            model_id=generation.metadata.model,
            model_decision=generation.output.decision,
        )
        await self._persist(draft_id=draft.id, result=result)
        return result

    def _structured_audit_issues(
        self,
        *,
        output: CriticModelOutput,
        claim_rows: Sequence[EmailDraftClaim],
        evidence_context: Sequence[Mapping[str, object]],
        company_context: str,
    ) -> list[str]:
        issues: list[str] = []
        if not output.coverage_complete:
            issues.append("incomplete_body_assertion_audit")

        ledger_evidence: dict[str, set[int]] = {}
        for claim in claim_rows:
            ledger_evidence[_normalize_text(claim.claim_text)] = set(
                self._parse_evidence_ids(claim.evidence_ids_json)
            )
        known_evidence_ids = {
            int(item["id"])
            for item in evidence_context
            if isinstance(item.get("id"), int)
        }
        audited_ledger_claims: set[str] = set()
        normalized_company_context = _normalize_text(company_context)

        for audit in output.assertion_audits:
            preview = _normalize_text(audit.body_assertion)[:120]
            if audit.verdict == "SEMANTIC_EXPANSION":
                issues.append(f"semantic_expansion:{preview}")
            elif audit.verdict == "UNSUPPORTED":
                issues.append(f"unsupported_assertion:{preview}")

            if audit.assertion_type in {"PROSPECT_FACT", "PROSPECT_INFERENCE"}:
                if audit.ledger_claim is None:
                    issues.append("uncatalogued_material_assertion")
                    continue

                ledger_key = _normalize_text(audit.ledger_claim)
                expected_evidence = ledger_evidence.get(ledger_key)
                if expected_evidence is None:
                    issues.append("unknown_claim_ledger_reference")
                    continue

                audited_ledger_claims.add(ledger_key)
                audit_evidence = set(audit.evidence_ids)
                if not audit_evidence or not audit_evidence.issubset(expected_evidence):
                    issues.append("audit_evidence_not_in_claim_ledger")
                if not audit_evidence.issubset(known_evidence_ids):
                    issues.append("unknown_evidence")

            elif audit.assertion_type == "WEBERAISE_SELF_CLAIM":
                quote = audit.company_context_quote
                if (
                    quote is None
                    or not quote.strip()
                    or _normalize_text(quote) not in normalized_company_context
                ):
                    issues.append("unsupported_weberaise_claim")

        missing_ledger_audits = set(ledger_evidence) - audited_ledger_claims
        if missing_ledger_audits:
            issues.append("incomplete_claim_audit")

        for abstraction in output.copy_abstractions:
            normalized = abstraction.strip()
            if normalized:
                issues.append(f"agency_abstraction:{normalized}")

        return list(dict.fromkeys(issues))

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
                await self.session.scalars(select(Contact).where(Contact.lead_id == lead.id))
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
        review = EmailReview(
            draft_id=draft_id,
            decision=result.decision.value,
            scores_json=result.scores.model_dump_json(),
            issues_json=json.dumps(result.issues),
            prompt_version=result.prompt_version,
            model_id=result.model_id,
        )
        self.session.add(review)
        await self.session.flush()

        audit_payload = {
            "model_decision": (
                result.model_decision.value if result.model_decision is not None else None
            ),
            "effective_decision": result.decision.value,
            "coverage_complete": result.coverage_complete,
            "assertion_audits": [
                audit.model_dump(mode="json") for audit in result.assertion_audits
            ],
            "copy_abstractions": result.copy_abstractions,
        }
        self.session.add(
            EmailReviewAudit(
                review_id=review.id,
                draft_id=draft_id,
                audit_json=json.dumps(audit_payload, ensure_ascii=False),
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
