from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from scout_email.common.enums import ReplyClass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReplySyncRequest(StrictModel):
    gmail_thread_id: str = Field(min_length=1, max_length=300)
    gmail_message_id: str = Field(min_length=1, max_length=300)
    from_email: str = Field(min_length=3, max_length=320)
    subject: str = Field(default="", max_length=1000)
    body: str = Field(default="", max_length=100_000)
    headers: dict[str, str] = Field(default_factory=dict)
    received_at: datetime


class ReplyIntelligence(StrictModel):
    classification: ReplyClass
    summary: str = Field(min_length=1, max_length=2000)
    intent_score: float = Field(ge=0.0, le=1.0)
    questions: list[str] = Field(default_factory=list, max_length=10)
    recommended_action: str = Field(min_length=1, max_length=120)


class ReplyView(StrictModel):
    id: int
    thread_id: int
    gmail_message_id: str
    classification: ReplyClass
    summary: str | None
    intent_score: float
    questions: list[str]
    recommended_action: str
    received_at: datetime
