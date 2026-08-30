from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


ResearchOutcome = Literal[
    "COMPLETE",
    "INSUFFICIENT_EVIDENCE",
    "NO_CLEAR_OPPORTUNITY",
    "RESEARCH_MORE",
]
PositiveId = Annotated[int, Field(gt=0)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceFinding(StrictModel):
    text: str = Field(min_length=1)
    evidence_ids: list[PositiveId] = Field(min_length=1)


class BusinessSummary(StrictModel):
    name: str = Field(min_length=1)
    summary: str = ""
    category: str | None = None
    location: str | None = None


class BusinessModelSummary(StrictModel):
    target_customers: list[str] = Field(default_factory=list)
    offerings: list[str] = Field(default_factory=list)
    primary_conversion: str | None = None


class PresenceSummary(StrictModel):
    website_state: str | None = None
    social_profiles: list[str] = Field(default_factory=list)


class ContactReference(StrictModel):
    contact_id: PositiveId


class ResearchOutput(StrictModel):
    business: BusinessSummary
    business_model: BusinessModelSummary
    presence: PresenceSummary
    strengths: list[EvidenceFinding] = Field(default_factory=list)
    website_findings: list[EvidenceFinding] = Field(default_factory=list)
    technical_findings: list[EvidenceFinding] = Field(default_factory=list)
    contact: ContactReference | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    outcome: ResearchOutcome

    def referenced_evidence_ids(self) -> set[int]:
        return {
            evidence_id
            for finding in (
                self.strengths
                + self.website_findings
                + self.technical_findings
            )
            for evidence_id in finding.evidence_ids
        }
