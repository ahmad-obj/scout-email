from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scout_email.common.enums import ClaimClass, LeadState
from scout_email.db.models import (
    AuditFinding,
    Contact,
    Evidence,
    Lead,
    ResearchReport,
    Strategy,
)
from scout_email.llm.gateway import LLMGateway
from scout_email.strategy.schemas import StrategyOutput


class StrategyEvidenceError(ValueError):
    """Raised when a strategy references evidence/contact data it cannot safely use."""


class StrategyService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        gateway: LLMGateway,
        prompt_version: str = "strategist:v2",
    ) -> None:
        self.session = session
        self.gateway = gateway
        self.prompt_version = prompt_version

    async def strategize(self, *, lead_id: int) -> StrategyOutput:
        lead = await self.session.get(Lead, lead_id)
        if lead is None:
            raise ValueError(f"lead {lead_id} does not exist")

        report = await self.session.scalar(
            select(ResearchReport)
            .where(ResearchReport.lead_id == lead_id)
            .order_by(ResearchReport.id.desc())
        )
        if report is None or report.status not in {"COMPLETE", "NO_CLEAR_OPPORTUNITY"}:
            output = StrategyOutput(
                decision="RESEARCH_MORE",
                candidates=[],
                persuasion_brief=None,
                supporting_evidence_ids=[],
                score_components=None,
                confidence=0.0,
                rationale="Research evidence is not sufficient for a safe outreach decision.",
            )
            await self._persist_strategy(
                lead=lead,
                output=output,
                model_id=None,
                target_state=LeadState.RESEARCH_PENDING,
            )
            return output

        evidence = list(
            (
                await self.session.scalars(
                    select(Evidence)
                    .where(
                        Evidence.lead_id == lead_id,
                        Evidence.claim_class != ClaimClass.UNVERIFIED.value,
                    )
                    .order_by(Evidence.id)
                )
            ).all()
        )
        if not evidence:
            output = StrategyOutput(
                decision="RESEARCH_MORE",
                candidates=[],
                persuasion_brief=None,
                supporting_evidence_ids=[],
                score_components=None,
                confidence=0.0,
                rationale="No safe persisted evidence is available for strategy selection.",
            )
            await self._persist_strategy(
                lead=lead,
                output=output,
                model_id=None,
                target_state=LeadState.RESEARCH_PENDING,
            )
            return output

        contacts = list(
            (
                await self.session.scalars(
                    select(Contact)
                    .where(Contact.lead_id == lead_id, Contact.state == "VERIFIED")
                    .order_by(Contact.id)
                )
            ).all()
        )

        context = {
            "research_dossier": json.loads(report.dossier_json),
            "evidence": [
                {
                    "id": row.id,
                    "kind": row.kind,
                    "claim_class": row.claim_class,
                    "claim": row.claim,
                    "source_type": row.source_type,
                    "source_url": row.source_url,
                    "confidence": row.confidence,
                }
                for row in evidence
            ],
            "verified_contacts": [
                {
                    "contact_id": row.id,
                    "contact_type": row.contact_type,
                    "source_url": row.source_url,
                    "confidence": row.confidence,
                }
                for row in contacts
            ],
        }

        generated = await self.gateway.generate(
            task="strategist",
            context=context,
            response_model=StrategyOutput,
            prompt_version=self.prompt_version,
        )
        output = generated.output

        try:
            self._validate_references(
                output,
                evidence_ids={row.id for row in evidence},
                has_verified_contact=bool(contacts),
            )
        except StrategyEvidenceError:
            lead.state = LeadState.RESEARCHED.value
            await self.session.commit()
            raise

        for candidate in output.candidates:
            self.session.add(
                AuditFinding(
                    lead_id=lead.id,
                    problem=candidate.problem,
                    severity=candidate.score.severity,
                    business_impact=candidate.score.business_impact,
                    confidence=candidate.score.evidence_confidence,
                    evidence_ids_json=json.dumps(candidate.evidence_ids),
                    safe_to_reference=candidate.safe_to_reference,
                )
            )

        target_state = {
            "CONTACT": LeadState.CONTACTABLE,
            "RESEARCH_MORE": LeadState.RESEARCH_PENDING,
            "LOW_PRIORITY": LeadState.LOW_PRIORITY,
            "SKIP": LeadState.SKIPPED,
        }[output.decision]
        await self._persist_strategy(
            lead=lead,
            output=output,
            model_id=generated.metadata.model,
            target_state=target_state,
        )
        return output

    @staticmethod
    def _validate_references(
        output: StrategyOutput,
        *,
        evidence_ids: set[int],
        has_verified_contact: bool,
    ) -> None:
        referenced = set(output.supporting_evidence_ids)
        for candidate in output.candidates:
            referenced.update(candidate.evidence_ids)
        unknown = referenced - evidence_ids
        if unknown:
            raise StrategyEvidenceError(
                f"strategy referenced unknown evidence IDs: {sorted(unknown)}"
            )

        if output.decision != "CONTACT":
            return
        if not has_verified_contact:
            raise StrategyEvidenceError("CONTACT requires a verified persisted contact")

        safe_candidate_evidence = {
            evidence_id
            for candidate in output.candidates
            if candidate.safe_to_reference
            for evidence_id in candidate.evidence_ids
        }
        if not set(output.supporting_evidence_ids) <= safe_candidate_evidence:
            raise StrategyEvidenceError(
                "CONTACT supporting evidence must come from safe-to-reference candidates"
            )

    async def _persist_strategy(
        self,
        *,
        lead: Lead,
        output: StrategyOutput,
        model_id: str | None,
        target_state: LeadState,
    ) -> None:
        score_payload = (
            output.score_components.model_dump(mode="json")
            if output.score_components is not None
            else {}
        )
        self.session.add(
            Strategy(
                lead_id=lead.id,
                decision=output.decision,
                primary_angle=(
                    output.persuasion_brief.primary_angle
                    if output.persuasion_brief is not None
                    else None
                ),
                persuasion_brief_json=json.dumps(
                    output.persuasion_brief.model_dump(mode="json")
                    if output.persuasion_brief is not None
                    else None,
                    separators=(",", ":"),
                ),
                score_components_json=json.dumps(score_payload, separators=(",", ":")),
                confidence=output.confidence,
                prompt_version=self.prompt_version,
                model_id=model_id,
            )
        )
        lead.state = target_state.value
        await self.session.commit()
