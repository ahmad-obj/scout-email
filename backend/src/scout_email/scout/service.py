from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from scout_email.browser.client import BrowserWorkerClient
from scout_email.campaigns.service import CampaignService
from scout_email.common.errors import InvalidStateTransitionError
from scout_email.db.models import CampaignSearch, Lead
from scout_email.jobs.service import JobService
from scout_email.leads.service import LeadIngestService
from scout_email.scout.maps import browser_lead_to_inputs, source_identity
from scout_email.scout.models import LeadSourceQuery
from scout_email.scout.schemas import ScoutEnqueueResponse, ScoutSearchJobPayload

SCOUT_JOB_KIND = "MAPS_SCOUT_SEARCH"


class ScoutService:
    def __init__(self, session: AsyncSession, browser: BrowserWorkerClient | None = None) -> None:
        self.session = session
        self.browser = browser

    async def _campaign_and_count(self, campaign_id: int):
        campaign = await CampaignService(self.session).require_active(campaign_id)
        count = await self.session.scalar(select(func.count()).select_from(Lead).where(Lead.campaign_id == campaign_id))
        return campaign, int(count or 0)

    async def enqueue_campaign(self, campaign_id: int) -> ScoutEnqueueResponse:
        try:
            campaign, current = await self._campaign_and_count(campaign_id)
        except RuntimeError as error:
            raise InvalidStateTransitionError(str(error)) from error
        target = campaign.target_leads or 1
        if current >= target:
            return ScoutEnqueueResponse(campaign_id=campaign_id, job_ids=[])
        searches = (await self.session.execute(select(CampaignSearch).where(CampaignSearch.campaign_id == campaign_id).order_by(CampaignSearch.id))).scalars().all()
        job_service = JobService(self.session)
        job_ids: list[int] = []
        remaining = max(1, min(100, target - current))
        for row in searches:
            query = f"{row.search_term} in {row.location}"
            payload = ScoutSearchJobPayload(campaign_id=campaign_id, campaign_search_id=row.id, query=query, search_term=row.search_term, location=row.location, max_results=remaining)
            job = await job_service.enqueue_job(SCOUT_JOB_KIND, payload.model_dump(mode="json"), f"scout:{campaign_id}:{row.id}")
            job_ids.append(job.id)
        return ScoutEnqueueResponse(campaign_id=campaign_id, job_ids=job_ids)

    async def run_search(self, payload: ScoutSearchJobPayload) -> dict[str, int | str]:
        try:
            campaign, current = await self._campaign_and_count(payload.campaign_id)
        except RuntimeError as error:
            raise InvalidStateTransitionError(str(error)) from error
        target = campaign.target_leads or 1
        if current >= target:
            return {"status": "target_reached", "created": 0, "seen": 0}
        if self.browser is None:
            raise RuntimeError("ScoutService requires a browser client to execute search jobs")
        remaining = min(payload.max_results, target - current)
        browser_leads = await self.browser.search_maps(payload.query, remaining)
        ingest = LeadIngestService(self.session)
        created = 0
        seen = 0
        for browser_lead in browser_leads:
            if current + created >= target:
                break
            raw, source = browser_lead_to_inputs(browser_lead, query=payload.query, location=payload.location)
            result = await ingest.ingest(payload.campaign_id, raw, source)
            created += int(result.created)
            seen += 1
            await self.session.execute(sqlite_insert(LeadSourceQuery).values(campaign_id=payload.campaign_id, lead_id=result.lead_id, source="google_maps_browser", source_identity=source_identity(browser_lead), source_query=payload.query, source_url=browser_lead.maps_url).on_conflict_do_nothing(index_elements=["campaign_id", "source", "source_identity", "source_query"]))
        await self.session.commit()
        return {"status": "complete", "created": created, "seen": seen}
