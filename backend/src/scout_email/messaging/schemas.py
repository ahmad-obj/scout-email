from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QueueMessageRequest(StrictModel):
    recipient_id: int = Field(gt=0)
    sender_id: int = Field(gt=0)


class ProviderCompletionRequest(StrictModel):
    status: Literal["SENT", "FAILED"]
    provider_message_id: str | None = Field(default=None, min_length=1, max_length=300)
    provider_thread_id: str | None = Field(default=None, min_length=1, max_length=300)
    error: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def validate_provider_ids(self) -> "ProviderCompletionRequest":
        if self.status == "SENT" and (
            not self.provider_message_id or not self.provider_thread_id
        ):
            raise ValueError("SENT completion requires provider message and thread IDs")
        return self


class MessageView(StrictModel):
    id: int
    state: str
    recipient_email: str
    subject: str
    body: str
    provider_message_id: str | None = None
    provider_thread_id: str | None = None
