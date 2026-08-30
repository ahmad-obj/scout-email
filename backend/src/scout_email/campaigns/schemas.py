from typing import Literal

from pydantic import BaseModel, Field, field_validator


class QualificationPolicy(BaseModel):
    minimum_rating: float | None = Field(default=None, ge=0, le=5)
    exclude_chains: bool = True


class SendingPolicy(BaseModel):
    max_per_day: int = Field(default=10, ge=1)
    human_approval: Literal[True] = True


class FollowUpPolicy(BaseModel):
    enabled: bool = True
    max_followups: int = Field(default=1, ge=0, le=1)
    delay_days: int = Field(default=4, ge=1, le=90)


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    searches: list[str] = Field(min_length=1)
    locations: list[str] = Field(min_length=1)
    target_leads: int = Field(ge=1)
    qualification: QualificationPolicy = Field(default_factory=QualificationPolicy)
    sending: SendingPolicy = Field(default_factory=SendingPolicy)
    follow_up: FollowUpPolicy = Field(default_factory=FollowUpPolicy)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value

    @field_validator("searches", "locations")
    @classmethod
    def normalize_nonempty_strings(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            item = value.strip()
            if not item:
                raise ValueError("items must not be blank")
            key = item.casefold()
            if key not in seen:
                cleaned.append(item)
                seen.add(key)
        if not cleaned:
            raise ValueError("at least one item is required")
        return cleaned


class CampaignResponse(BaseModel):
    id: int
    name: str
    searches: list[str]
    locations: list[str]
    target_leads: int
    qualification: QualificationPolicy
    sending: SendingPolicy
    follow_up: FollowUpPolicy
    status: str
