from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scout_email.common.enums import ApprovalState, ClaimClass, LeadState, MessageState
from scout_email.db.models import (
    AuditFinding,
    EmailDraft,
    EmailDraftClaim,
    EmailEdit,
    Evidence,
    Lead,
    OutboundMessage,
    ResearchReport,
    Strategy,
)
from scout_email.llm.context import build_writer_context
from scout_email.llm.gateway import LLMGateway
from scout_email.writing.models import DraftGenerationMetadata
from scout_email.writing.playbook import WritingPlaybook
from scout_email.writing.schemas import EmailDraftOutput, WriterModelOutput
from scout_email.writing.similarity import max_recent_similarity


class WriterError(RuntimeError):
    pass


class WriterEvidenceError(WriterError):
    pass


class BannedPhraseError(WriterError):
    pass


class WriterService:
    PROMPT_VERSION = "writer:v2"

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

    async def write(
        self,
        *,
        lead_id: int,
        critic_feedback: list[str] | None = None,
    ) -> EmailDraftOutput:
        lead = await self.session.get(Lead, lead_id)
        if lead is None:
            raise ValueError("lead not found")
        if lead.state != LeadState.CONTACTABLE.value:
            raise WriterEvidenceError("Writer requires a CONTACTABLE lead")

        strategy = await self.session.scalar(
            select(Strategy)
            .where(Strategy.lead_id == lead_id, Strategy.decision == "CONTACT")
            .order_by(Strategy.id.desc())
        )
        if strategy is None:
            raise WriterEvidenceError("Writer requires a persisted CONTACT strategy")

        report = await self.session.scalar(
            select(ResearchReport)
            .where(
                ResearchReport.lead_id == lead_id,
                ResearchReport.status.in_(["COMPLETE", "NO_CLEAR_OPPORTUNITY"]),
            )
            .order_by(ResearchReport.id.desc())
        )
        if report is None:
            raise WriterEvidenceError("Writer requires a completed research dossier")

        allowed_ids = await self._safe_evidence_ids(lead_id)
        if not allowed_ids:
            raise WriterEvidenceError("Writer has no safe-to-reference evidence")

        evidence_rows = list(
            (
                await self.session.scalars(
                    select(Evidence)
                    .where(
                        Evidence.lead_id == lead_id,
                        Evidence.id.in_(allowed_ids),
                        Evidence.claim_class != ClaimClass.UNVERIFIED.value,
                    )
                    .order_by(Evidence.id)
                )
            ).all()
        )
        known_ids = {row.id for row in evidence_rows}
        if known_ids != allowed_ids:
            raise WriterEvidenceError("safe audit findings reference unavailable evidence")

        recent_bodies = list(
            (
                await self.session.scalars(
                    select(OutboundMessage.body)
                    .where(OutboundMessage.state == MessageState.SENT.value)
                    .order_by(OutboundMessage.id.desc())
                    .limit(20)
                )
            ).all()
        )
        corrections = list(
            (
                await self.session.scalars(
                    select(EmailEdit).order_by(EmailEdit.id.desc()).limit(5)
                )
            ).all()
        )

        context = build_writer_context(
            {
                "dossier_summary": json.loads(report.dossier_json),
                "persuasion_brief": json.loads(strategy.persuasion_brief_json),
                "allowed_evidence": [
                    {
                        "id": row.id,
                        "claim_class": row.claim_class,
                        "claim": row.claim,
                        "source_type": row.source_type,
                        "source_url": row.source_url,
                        "confidence": row.confidence,
                    }
                    for row in evidence_rows
                ],
                "weberaise_context": self.playbook.company_context,
                "writing_rules": [
                    self.playbook.writing_rules,
                    self.playbook.cta_rules,
                ],
                "approved_examples": list(self.playbook.approved_examples),
                "recent_corrections": [
                    {
                        "original_subject": row.original_subject,
                        "original_body": row.original_body,
                        "edited_subject": row.edited_subject,
                        "edited_body": row.edited_body,
                        "edit_context": row.edit_context,
                    }
                    for row in corrections
                ],
                "recent_sent_structures": recent_bodies,
                "critic_feedback": critic_feedback or [],
            }
        )

        generation = await self.gateway.generate(
            task="writer",
            context=context,
            response_model=WriterModelOutput,
            prompt_version=self.PROMPT_VERSION,
        )
        generated = generation.output

        self._assert_no_banned_phrase(generated.subject, generated.body)
        referenced_ids = {
            evidence_id
            for claim in generated.claims
            for evidence_id in claim.evidence_ids
        }
        unknown = referenced_ids - known_ids
        if unknown:
            raise WriterEvidenceError(
                f"Writer referenced unknown or unsafe evidence IDs: {sorted(unknown)}"
            )

        output = EmailDraftOutput(
            subject=generated.subject,
            body=generated.body,
            claims=generated.claims,
            strategy_label=generated.strategy_label,
            prompt_version=self.PROMPT_VERSION,
            playbook_hash=self.playbook.version_hash,
        )
        recent_similarity = max_recent_similarity(output.body, recent_bodies)

        draft = EmailDraft(
            lead_id=lead.id,
            strategy_id=strategy.id,
            subject=output.subject,
            body=output.body,
            writer_prompt_version=self.PROMPT_VERSION,
            model_id=generation.metadata.model,
            approval_state=ApprovalState.PENDING.value,
        )
        self.session.add(draft)
        await self.session.flush()

        for claim in output.claims:
            self.session.add(
                EmailDraftClaim(
                    draft_id=draft.id,
                    claim_text=claim.text,
                    claim_class=claim.claim_class.value,
                    evidence_ids_json=json.dumps(claim.evidence_ids),
                )
            )
        self.session.add(
            DraftGenerationMetadata(
                draft_id=draft.id,
                playbook_hash=self.playbook.version_hash,
                strategy_label=output.strategy_label,
                recent_similarity=recent_similarity,
            )
        )
        await self.session.commit()
        return output

    async def _safe_evidence_ids(self, lead_id: int) -> set[int]:
        findings = list(
            (
                await self.session.scalars(
                    select(AuditFinding).where(
                        AuditFinding.lead_id == lead_id,
                        AuditFinding.safe_to_reference.is_(True),
                    )
                )
            ).all()
        )
        ids: set[int] = set()
        for finding in findings:
            try:
                raw = json.loads(finding.evidence_ids_json)
            except (TypeError, json.JSONDecodeError) as error:
                raise WriterEvidenceError("audit finding has malformed evidence IDs") from error
            if not isinstance(raw, list) or any(
                not isinstance(item, int) or isinstance(item, bool) or item <= 0
                for item in raw
            ):
                raise WriterEvidenceError("audit finding has invalid evidence IDs")
            ids.update(raw)
        return ids

    def _assert_no_banned_phrase(self, subject: str, body: str) -> None:
        rendered = f"{subject}\n{body}".casefold()
        for phrase in self.playbook.banned_phrases:
            normalized = phrase.strip().casefold()
            if normalized and normalized in rendered:
                raise BannedPhraseError(f"draft contains banned phrase: {phrase}")
