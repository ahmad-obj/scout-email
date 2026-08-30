from pydantic import BaseModel, Field


class ScoutEnqueueResponse(BaseModel):
    campaign_id: int
    job_ids: list[int]


class ScoutSearchJobPayload(BaseModel):
    campaign_id: int
    campaign_search_id: int
    query: str
    search_term: str
    location: str
    max_results: int = Field(ge=1, le=100)
