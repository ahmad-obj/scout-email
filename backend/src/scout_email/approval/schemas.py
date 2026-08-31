from __future__ import annotations

from pydantic import BaseModel, Field

from scout_email.jobs.schemas import JobView


class ApprovalResult(BaseModel):
    draft_id: int
    approval_state: str
    content_hash: str


class EditResult(BaseModel):
    draft_id: int
    approval_state: str
    content_hash: str


class RegenerationResult(BaseModel):
    draft_id: int
    job: JobView


class EditRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1)
    reviewer: str = Field(default="human", min_length=1, max_length=200)
    edit_context: str | None = Field(default=None, max_length=80)


class ReviewerRequest(BaseModel):
    reviewer: str = Field(default="human", min_length=1, max_length=200)


class RejectRequest(ReviewerRequest):
    reason: str = Field(min_length=1, max_length=1000)
