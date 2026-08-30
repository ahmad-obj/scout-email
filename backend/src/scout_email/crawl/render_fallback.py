from __future__ import annotations

from typing import Protocol

from scout_email.browser.client import BrowserWorkerError
from scout_email.browser.schemas import BrowserRenderResponse
from scout_email.crawl.extract import extract_page
from scout_email.crawl.site import CrawledPage, SiteCrawlResult


class RenderBrowser(Protocol):
    async def render(
        self,
        url: str,
        *,
        viewport: str = "desktop",
        screenshot_path: str | None = None,
    ) -> BrowserRenderResponse: ...


async def refine_with_browser(
    result: SiteCrawlResult,
    *,
    browser: RenderBrowser,
    max_render_pages: int = 4,
) -> SiteCrawlResult:
    """Replace thin static-page extractions with bounded browser-rendered evidence.

    Only URLs already flagged by the deterministic crawler are eligible. Successful
    renders clear their fallback flag; failed and over-budget URLs remain unresolved.
    The original crawl URL is preserved as the page identity so persistence remains
    idempotent even when a browser navigation ends on a redirected URL.
    """
    if max_render_pages <= 0 or not result.browser_fallback_urls:
        return result.model_copy(deep=True)

    pages = [page.model_copy(deep=True) for page in result.pages]
    page_indexes = {page.url: index for index, page in enumerate(pages)}
    unresolved = list(result.browser_fallback_urls)
    skipped = dict(result.skipped_urls)

    for url in result.browser_fallback_urls[:max_render_pages]:
        page_index = page_indexes.get(url)
        if page_index is None:
            continue

        try:
            rendered = await browser.render(url, viewport="desktop")
        except BrowserWorkerError:
            skipped[url] = "BROWSER_RENDER_FAILED"
            continue

        extracted = extract_page(rendered.html, rendered.final_url)
        original = pages[page_index]
        pages[page_index] = CrawledPage(
            url=original.url,
            http_status=original.http_status,
            title=extracted.title or rendered.title or original.title,
            headings=extracted.headings,
            important_text=extracted.important_text,
            calls_to_action=extracted.calls_to_action,
            forms=extracted.forms,
            links=extracted.links,
            technical_signals=extracted.technical_signals,
        )
        unresolved.remove(url)

    return SiteCrawlResult(
        start_url=result.start_url,
        pages=pages,
        browser_fallback_urls=unresolved,
        skipped_urls=skipped,
    )
