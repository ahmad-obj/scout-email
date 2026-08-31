from pydantic import BaseModel, Field

from scout_email.jobs.schemas import JobReference


class ScoutEnqueueResponse(BaseModel):
    campaign_id: int
    jobs: list[JobReference]
    job_ids: list[int]


class ScoutSearchJobPayload(BaseModel):
    campaign_id: int
    campaign_search_id: int
    query: str
    search_term: str
    location: str
    max_results: int = Field(ge=1, le=100)
