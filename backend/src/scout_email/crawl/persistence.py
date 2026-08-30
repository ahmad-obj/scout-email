from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scout_email.crawl.site import SiteCrawlResult
from scout_email.db.models import CrawlPage


class CrawlPersistenceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def persist(self, lead_id: int, result: SiteCrawlResult) -> None:
        fallback_urls = set(result.browser_fallback_urls)

        for page in result.pages:
            row = await self.session.scalar(
                select(CrawlPage).where(
                    CrawlPage.lead_id == lead_id,
                    CrawlPage.url == page.url,
                )
            )
            if row is None:
                row = CrawlPage(lead_id=lead_id, url=page.url)
                self.session.add(row)

            row.title = page.title
            row.important_text = page.important_text
            row.http_status = page.http_status
            row.extracted_json = json.dumps(
                {
                    "headings": page.headings,
                    "calls_to_action": page.calls_to_action,
                    "forms": page.forms,
                    "links": page.links,
                    "technical_signals": page.technical_signals,
                    "browser_fallback_required": page.url in fallback_urls,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            row.crawled_at = datetime.now(timezone.utc)

        await self.session.commit()
