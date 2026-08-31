from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scout_email.approval.models import EmailEditMetadata, HumanApprovalEvent
from scout_email.approval.schemas import ApprovalResult, EditResult, RegenerationResult
from scout_email.common.enums import ApprovalState
from scout_email.common.errors import InvalidStateTransitionError, NotFoundError
from scout_email.db.models import EmailDraft, EmailEdit, Lead
from scout_email.jobs.service import JobService
from scout_email.writing.models import DraftGenerationMetadata


def content_hash(subject: str, body: str) -> str:
    payload = f"{subject}\0{body}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class ApprovalService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _draft(self, draft_id: int) -> EmailDraft:
        draft = await self.session.get(EmailDraft, draft_id)
        if draft is None:
            raise NotFoundError(f"Draft {draft_id} not found")
        return draft

    def _event(
        self,
        draft: EmailDraft,
        *,
        action: str,
        reviewer: str,
        metadata: dict | None = None,
    ) -> HumanApprovalEvent:
        return HumanApprovalEvent(
            draft_id=draft.id,
            action=action,
            reviewer=reviewer.strip(),
            content_hash=content_hash(draft.subject, draft.body),
            subject_snapshot=draft.subject,
            body_snapshot=draft.body,
            metadata_json=json.dumps(metadata or {}, sort_keys=True),
        )

    async def is_currently_approved(self, draft_id: int) -> bool:
        draft = await self._draft(draft_id)
        current = content_hash(draft.subject, draft.body)
        return (
            draft.approval_state == ApprovalState.APPROVED.value
            and draft.approved_content_hash == current
            and draft.approved_at is not None
        )

    async def approve(self, *, draft_id: int, reviewer: str) -> ApprovalResult:
        draft = await self._draft(draft_id)
        if draft.approval_state == ApprovalState.REJECTED.value:
            raise InvalidStateTransitionError("rejected draft cannot be approved")
        digest = content_hash(draft.subject, draft.body)
        draft.approval_state = ApprovalState.APPROVED.value
        draft.approved_content_hash = digest
        draft.approved_at = datetime.now(UTC)
        self.session.add(self._event(draft, action="APPROVE", reviewer=reviewer))
        await self.session.commit()
        return ApprovalResult(
            draft_id=draft.id,
            approval_state=draft.approval_state,
            content_hash=digest,
        )

    async def edit(
        self,
        *,
        draft_id: int,
        subject: str,
        body: str,
        reviewer: str,
        edit_context: str | None = None,
    ) -> EditResult:
        draft = await self._draft(draft_id)
        if draft.approval_state == ApprovalState.REJECTED.value:
            raise InvalidStateTransitionError("rejected draft cannot be edited in place")
        if not subject.strip() or not body.strip():
            raise ValueError("subject and body are required")

        original_subject = draft.subject
        original_body = draft.body
        edit = EmailEdit(
            draft_id=draft.id,
            original_subject=original_subject,
            original_body=original_body,
            edited_subject=subject,
            edited_body=body,
            edit_context=edit_context,
        )
        self.session.add(edit)
        await self.session.flush()

        lead = await self.session.get(Lead, draft.lead_id)
        generation = await self.session.scalar(
            select(DraftGenerationMetadata).where(
                DraftGenerationMetadata.draft_id == draft.id
            )
        )
        self.session.add(
            EmailEditMetadata(
                edit_id=edit.id,
                lead_industry=lead.category if lead else None,
                playbook_hash=generation.playbook_hash if generation else None,
                writer_prompt_version=draft.writer_prompt_version,
            )
        )

        draft.subject = subject
        draft.body = body
        draft.approval_state = ApprovalState.PENDING.value
        draft.approved_content_hash = None
        draft.approved_at = None
        digest = content_hash(draft.subject, draft.body)
        self.session.add(
            self._event(
                draft,
                action="EDIT",
                reviewer=reviewer,
                metadata={"edit_id": edit.id, "edit_context": edit_context},
            )
        )
        await self.session.commit()
        return EditResult(
            draft_id=draft.id,
            approval_state=draft.approval_state,
            content_hash=digest,
        )

    async def reject(
        self,
        *,
        draft_id: int,
        reviewer: str,
        reason: str,
    ) -> ApprovalResult:
        draft = await self._draft(draft_id)
        draft.approval_state = ApprovalState.REJECTED.value
        draft.approved_content_hash = None
        draft.approved_at = None
        digest = content_hash(draft.subject, draft.body)
        self.session.add(
            self._event(
                draft,
                action="REJECT",
                reviewer=reviewer,
                metadata={"reason": reason},
            )
        )
        await self.session.commit()
        return ApprovalResult(
            draft_id=draft.id,
            approval_state=draft.approval_state,
            content_hash=digest,
        )

    async def regenerate(self, *, draft_id: int, reviewer: str) -> RegenerationResult:
        draft = await self._draft(draft_id)
        if draft.approval_state != ApprovalState.REJECTED.value:
            draft.approval_state = ApprovalState.REJECTED.value
            draft.approved_content_hash = None
            draft.approved_at = None
        self.session.add(self._event(draft, action="REGENERATE", reviewer=reviewer))
        await self.session.flush()

        job = await JobService(self.session).enqueue_job(
            "writer_critic",
            {"lead_id": draft.lead_id, "source_draft_id": draft.id},
            f"regenerate-draft:{draft.id}:{content_hash(draft.subject, draft.body)}",
        )
        return RegenerationResult(draft_id=draft.id, job=job)
