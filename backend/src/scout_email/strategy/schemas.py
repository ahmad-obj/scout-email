from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


StrategyDecision = Literal["CONTACT", "RESEARCH_MORE", "LOW_PRIORITY", "SKIP"]
PositiveId = Annotated[int, Field(gt=0)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OpportunityScoreComponents(StrictModel):
    severity: float = Field(ge=0.0, le=1.0)
    evidence_confidence: float = Field(ge=0.0, le=1.0)
    business_impact: float = Field(ge=0.0, le=1.0)
    weberaise_fit: float = Field(ge=0.0, le=1.0)
    explainability: float = Field(ge=0.0, le=1.0)
    generic_speculation_risk: float = Field(ge=0.0, le=1.0)

    @computed_field
    @property
    def overall_score(self) -> float:
        return round(
            0.20 * self.severity
            + 0.20 * self.evidence_confidence
            + 0.25 * self.business_impact
            + 0.20 * self.weberaise_fit
            + 0.10 * self.explainability
            + 0.05 * (1.0 - self.generic_speculation_risk),
            6,
        )


class OpportunityCandidate(StrictModel):
    problem: str = Field(min_length=1)
    angle: str = Field(min_length=1)
    evidence_ids: list[PositiveId] = Field(min_length=1)
    score: OpportunityScoreComponents
    safe_to_reference: bool = False


class PersuasionBrief(StrictModel):
    primary_angle: str = Field(min_length=1)
    do_not_use: list[str] = Field(default_factory=list)
    recipient_goal: str | None = None
    observation: str | None = None
    business_implication: str | None = None
    offer_connection: str | None = None


class StrategyOutput(StrictModel):
    decision: StrategyDecision
    candidates: list[OpportunityCandidate] = Field(default_factory=list)
    persuasion_brief: PersuasionBrief | None = None
    supporting_evidence_ids: list[PositiveId] = Field(default_factory=list)
    score_components: OpportunityScoreComponents | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_contact_requirements(self) -> "StrategyOutput":
        if self.decision == "CONTACT":
            if self.persuasion_brief is None:
                raise ValueError("CONTACT requires a persuasion brief")
            if not self.supporting_evidence_ids:
                raise ValueError("CONTACT requires supporting evidence")
            if self.score_components is None:
                raise ValueError("CONTACT requires score components")

            safe_candidate_evidence = {
                evidence_id
                for candidate in self.candidates
                if candidate.safe_to_reference
                for evidence_id in candidate.evidence_ids
            }
            if not set(self.supporting_evidence_ids) <= safe_candidate_evidence:
                raise ValueError(
                    "CONTACT supporting evidence must come from safe-to-reference candidates"
                )
        return self
