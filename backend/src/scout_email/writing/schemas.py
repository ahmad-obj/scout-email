from __future__ import annotations

import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scout_email.common.enums import ClaimClass


PositiveId = Annotated[int, Field(gt=0)]
_PROBABILISTIC_TERMS = re.compile(
    r"\b(may|might|could|can potentially|potentially|likely|appears?|seems?|suggests?|possibly|perhaps)\b",
    re.IGNORECASE,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DraftClaim(StrictModel):
    text: str = Field(min_length=1, max_length=1000)
    claim_class: ClaimClass
    evidence_ids: list[PositiveId] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_sendable_claim(self) -> "DraftClaim":
        if self.claim_class == ClaimClass.UNVERIFIED:
            raise ValueError("UNVERIFIED claims are invalid in writer output")
        if not self.evidence_ids:
            raise ValueError("sendable claims require supporting evidence IDs")
        if (
            self.claim_class == ClaimClass.REASONABLE_INFERENCE
            and _PROBABILISTIC_TERMS.search(self.text) is None
        ):
            raise ValueError(
                "reasonable inferences must be phrased probabilistically"
            )
        return self


class WriterModelOutput(StrictModel):
    """Structured content produced by the model before trusted metadata is attached."""

    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=8000)
    claims: list[DraftClaim] = Field(min_length=1)
    strategy_label: str = Field(min_length=1, max_length=200)

    @field_validator("subject", "body", "strategy_label")
    @classmethod
    def strip_model_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("text must not be blank")
        return stripped


class EmailDraftOutput(WriterModelOutput):
    prompt_version: str = Field(min_length=1, max_length=80)
    playbook_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("prompt_version")
    @classmethod
    def strip_prompt_version(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("text must not be blank")
        return stripped
