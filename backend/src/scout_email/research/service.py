from __future__ import annotations

from typing import Literal

from pydantic import create_model
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scout_email.common.enums import ClaimClass, LeadState
from scout_email.db.models import Contact, Evidence, Lead, ResearchReport
from scout_email.db.repositories import LeadRepository
from scout_email.llm.gateway import LLMGateway
from scout_email.research.schemas import (
    BusinessModelSummary,
    BusinessSummary,
    ContactReference,
    PresenceSummary,
    ResearchOutput,
)


class ResearchEvidenceError(ValueError):
    """Raised when generated research references data that was not persisted for the lead."""


def _response_model_for_contacts(contact_ids: list[int]) -> type[ResearchOutput]:
    """Constrain structured Research output to persisted verified contact IDs."""
    if not contact_ids:
        return ResearchOutput

    allowed_ids = tuple(contact_ids)
    allowed_contact_id = Literal[allowed_ids]
    constrained_contact = create_model(
        "VerifiedContactReference",
        __base__=ContactReference,
        contact_id=(allowed_contact_id, ...),
    )
    return create_model(
        "ResearchOutputWithVerifiedContacts",
        __base__=ResearchOutput,
        contact=(constrained_contact | None, None),
    )


class ResearchService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        gateway: LLMGateway,
        prompt_version: str = "researcher:v1",
    ) -> None:
        self.session = session
        self.gateway = gateway
        self.prompt_version = prompt_version

    async def research(self, *, lead_id: int) -> ResearchOutput:
        lead = await self.session.get(Lead, lead_id)
        if lead is None:
            raise ValueError(f"lead {lead_id} does not exist")

        lead_repo = LeadRepository(self.session)
        await lead_repo.transition(lead_id, LeadState.RESEARCHING)
        await self.session.commit()
        await self.session.refresh(lead)

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
        contacts = list(
            (
                await self.session.scalars(
                    select(Contact)
                    .where(Contact.lead_id == lead_id, Contact.state == "VERIFIED")
                    .order_by(Contact.id)
                )
            ).all()
        )

        if not evidence:
            output = self._insufficient_output(lead)
            await self._persist(
                lead=lead,
                output=output,
                model_id=None,
                target_state=LeadState.RESEARCH_PENDING,
            )
            return output

        contact_ids = [row.id for row in contacts]
        context = {
            "business": {
                "name": lead.name,
                "category": lead.category,
                "city": lead.city,
            },
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
            "reference_constraints": {
                "allowed_contact_ids": contact_ids,
                "contact_must_be_null": not contacts,
            },
        }

        try:
            generated = await self.gateway.generate(
                task="researcher",
                context=context,
                response_model=_response_model_for_contacts(contact_ids),
                prompt_version=self.prompt_version,
            )
            output = ResearchOutput.model_validate(generated.output.model_dump())
            if not contacts and output.contact is not None:
                output = output.model_copy(update={"contact": None})
            self._validate_references(
                output,
                evidence_ids={row.id for row in evidence},
                contact_ids=set(contact_ids),
            )
        except Exception:
            current = await self.session.get(Lead, lead_id)
            if current is not None and current.state == LeadState.RESEARCHING.value:
                await lead_repo.transition(lead_id, LeadState.RESEARCH_PENDING)
                await self.session.commit()
            raise

        target_state = (
            LeadState.RESEARCHED
            if output.outcome in {"COMPLETE", "NO_CLEAR_OPPORTUNITY"}
            else LeadState.RESEARCH_PENDING
        )
        await self._persist(
            lead=lead,
            output=output,
            model_id=generated.metadata.model,
            target_state=target_state,
        )
        return output

    @staticmethod
    def _validate_references(
        output: ResearchOutput,
        *,
        evidence_ids: set[int],
        contact_ids: set[int],
    ) -> None:
        unknown_evidence = output.referenced_evidence_ids() - evidence_ids
        if unknown_evidence:
            raise ResearchEvidenceError(
                f"research output referenced unknown evidence IDs: {sorted(unknown_evidence)}"
            )
        if output.contact is not None and output.contact.contact_id not in contact_ids:
            raise ResearchEvidenceError(
                f"research output referenced invalid contact ID: {output.contact.contact_id}"
            )

    async def _persist(
        self,
        *,
        lead: Lead,
        output: ResearchOutput,
        model_id: str | None,
        target_state: LeadState,
    ) -> None:
        report = ResearchReport(
            lead_id=lead.id,
            status=output.outcome,
            dossier_json=output.model_dump_json(),
            confidence=output.confidence,
            prompt_version=self.prompt_version,
            model_id=model_id,
        )
        self.session.add(report)
        await LeadRepository(self.session).transition(lead.id, target_state)
        await self.session.commit()
        await self.session.refresh(lead)

    @staticmethod
    def _insufficient_output(lead: Lead) -> ResearchOutput:
        return ResearchOutput(
            business=BusinessSummary(
                name=lead.name,
                summary="",
                category=lead.category,
                location=lead.city,
            ),
            business_model=BusinessModelSummary(),
            presence=PresenceSummary(),
            strengths=[],
            website_findings=[],
            technical_findings=[],
            contact=None,
            confidence=0.0,
            outcome="INSUFFICIENT_EVIDENCE",
        )
