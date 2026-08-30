from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RawLead(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    category: str | None = None
    city: str | None = None
    address: str | None = None
    phone: str | None = None
    website: str | None = None
    maps_url: str | None = None
    rating: float | None = Field(default=None, ge=0, le=5)
    review_count: int | None = Field(default=None, ge=0)


class NormalizedLead(BaseModel):
    name: str
    normalized_name: str
    category: str | None = None
    city: str | None = None
    address: str | None = None
    phone: str | None = None
    canonical_domain: str | None = None
    maps_url: str | None = None
    rating: float | None = None
    review_count: int | None = None


class ExistingLead(NormalizedLead):
    id: int


class MatchResult(BaseModel):
    lead_id: int
    reason: str
    confidence: float = Field(ge=0, le=1)


class LeadScore(BaseModel):
    total: int
    components: dict[str, int]


class LeadSourceInput(BaseModel):
    source: str = Field(min_length=1, max_length=80)
    source_external_id: str | None = Field(default=None, max_length=300)
    source_query: str | None = Field(default=None, max_length=300)
    source_url: str | None = None
    raw: dict[str, Any] | None = None


class LeadIngestResult(BaseModel):
    lead_id: int
    created: bool
    match_reason: str
    score: LeadScore

    model_config = ConfigDict(from_attributes=True)
