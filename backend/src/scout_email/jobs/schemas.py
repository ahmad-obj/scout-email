from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class JobReference(BaseModel):
    job_id: int
    status_url: str
    correlation_id: str


class JobView(JobReference):
    id: int
    kind: str
    state: str
    payload: dict[str, Any]
    result: dict[str, Any] | None = None
    attempt_count: int
    max_attempts: int
    next_attempt_at: datetime | None = None
    locked_by: str | None = None
    lease_expires_at: datetime | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None


class JobEnqueueRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=80)
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1, max_length=128)
    max_attempts: int = Field(default=3, ge=1, le=20)


class JobClaimRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=200)
    kinds: list[str] = Field(min_length=1)
