from __future__ import annotations

from pydantic import BaseModel, Field

from scout_email.common.enums import ClaimClass


class EvidenceRecord(BaseModel):
    id: int = Field(gt=0)
    lead_id: int = Field(gt=0)
    kind: str
    claim_class: ClaimClass
    claim: str
    source_type: str
    source_url: str | None = None
    artifact_path: str | None = None
    confidence: float = Field(ge=0, le=1)


class ScreenshotRecord(BaseModel):
    id: int = Field(gt=0)
    lead_id: int = Field(gt=0)
    page_url: str
    viewport: str
    artifact_path: str


class EvidenceBundle(BaseModel):
    lead_id: int = Field(gt=0)
    evidence: list[EvidenceRecord]
    screenshots: list[ScreenshotRecord]
