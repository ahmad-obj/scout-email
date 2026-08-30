from sqlalchemy.ext.asyncio import AsyncSession

from scout_email.browser.client import BrowserWorkerClient
from scout_email.scout.schemas import ScoutSearchJobPayload
from scout_email.scout.service import SCOUT_JOB_KIND, ScoutService


def scout_handlers(session: AsyncSession, browser: BrowserWorkerClient):
    async def handle(payload: dict):
        return await ScoutService(session, browser).run_search(ScoutSearchJobPayload.model_validate(payload))
    return {SCOUT_JOB_KIND: handle}
