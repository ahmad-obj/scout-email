from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from scout_email.approval.schemas import (
    ApprovalResult,
    EditRequest,
    EditResult,
    RegenerationResult,
    RejectRequest,
    ReviewerRequest,
)
from scout_email.approval.service import ApprovalService
from scout_email.common.errors import InvalidStateTransitionError, NotFoundError
from scout_email.db.session import get_session

router = APIRouter(prefix="/approval/drafts", tags=["approval"])


def _translate(error: Exception) -> HTTPException:
    if isinstance(error, NotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, InvalidStateTransitionError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))


@router.post("/{draft_id}/approve", response_model=ApprovalResult)
async def approve_draft(
    draft_id: int,
    payload: ReviewerRequest,
    session: AsyncSession = Depends(get_session),
) -> ApprovalResult:
    try:
        return await ApprovalService(session).approve(
            draft_id=draft_id, reviewer=payload.reviewer
        )
    except (NotFoundError, InvalidStateTransitionError) as error:
        raise _translate(error) from error


@router.post("/{draft_id}/edit", response_model=EditResult)
async def edit_draft(
    draft_id: int,
    payload: EditRequest,
    session: AsyncSession = Depends(get_session),
) -> EditResult:
    try:
        return await ApprovalService(session).edit(
            draft_id=draft_id,
            subject=payload.subject,
            body=payload.body,
            reviewer=payload.reviewer,
            edit_context=payload.edit_context,
        )
    except (NotFoundError, InvalidStateTransitionError, ValueError) as error:
        raise _translate(error) from error


@router.post("/{draft_id}/reject", response_model=ApprovalResult)
async def reject_draft(
    draft_id: int,
    payload: RejectRequest,
    session: AsyncSession = Depends(get_session),
) -> ApprovalResult:
    try:
        return await ApprovalService(session).reject(
            draft_id=draft_id,
            reviewer=payload.reviewer,
            reason=payload.reason,
        )
    except (NotFoundError, InvalidStateTransitionError) as error:
        raise _translate(error) from error


@router.post(
    "/{draft_id}/regenerate",
    response_model=RegenerationResult,
    status_code=status.HTTP_202_ACCEPTED,
)
async def regenerate_draft(
    draft_id: int,
    payload: ReviewerRequest,
    session: AsyncSession = Depends(get_session),
) -> RegenerationResult:
    try:
        return await ApprovalService(session).regenerate(
            draft_id=draft_id, reviewer=payload.reviewer
        )
    except (NotFoundError, InvalidStateTransitionError) as error:
        raise _translate(error) from error
