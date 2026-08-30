from __future__ import annotations

from scout_email.research.schemas import ResearchOutput
from scout_email.research.service import ResearchService


async def run_research_job(service: ResearchService, *, lead_id: int) -> ResearchOutput:
    """Execute one bounded research job for a persisted lead."""
    return await service.research(lead_id=lead_id)
