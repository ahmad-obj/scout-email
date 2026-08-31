from __future__ import annotations

from pydantic import BaseModel, Field


class QueueMessageRequest(BaseModel):
    recipient_id: int = Field(gt=0)
    sender_id: int = Field(gt=0)


class MessageView(BaseModel):
    id: int
    state: str
    recipient_email: str
    subject: str
    body: str
    provider_message_id: str | None = None
    provider_thread_id: str | None = None
