from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class BrowserMapLead(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    category: str | None = None
    address: str | None = None
    phone: str | None = None
    website: str | None = None
    rating: float | None = Field(default=None, ge=0, le=5)
    review_count: int | None = Field(default=None, ge=0)
    maps_url: str | None = None
    source_external_id: str | None = None


class MapsSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    max_results: int = Field(default=25, ge=1, le=100)


class RenderRequest(BaseModel):
    url: HttpUrl
    viewport: Literal["desktop", "mobile"] = "desktop"
    screenshot_path: str | None = None


class RenderResponse(BaseModel):
    final_url: str
    title: str | None = None
    html: str
    screenshot_path: str | None = None
