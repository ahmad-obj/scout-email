from pydantic import BaseModel, Field


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


class BrowserRenderResponse(BaseModel):
    final_url: str = Field(min_length=1)
    title: str | None = None
    html: str
    screenshot_path: str | None = None
