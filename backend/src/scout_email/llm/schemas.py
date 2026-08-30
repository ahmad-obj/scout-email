from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field


GenerationStatus = Literal["COMPLETE", "FAILED_SCHEMA", "FAILED_PROVIDER"]


class ProviderResult(BaseModel):
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    text: str
    request_id: str | None = None
    usage: dict[str, int] | None = None


class GenerationMetadata(BaseModel):
    task: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    status: GenerationStatus
    repair_attempted: bool = False
    generated_at: datetime
    generation_id: int | None = Field(default=None, gt=0)


T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class StructuredGeneration(Generic[T]):
    output: T
    metadata: GenerationMetadata
