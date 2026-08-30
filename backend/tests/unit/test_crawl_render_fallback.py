import pytest

from scout_email.browser.schemas import BrowserRenderResponse
from scout_email.crawl.render_fallback import refine_with_browser
from scout_email.crawl.site import CrawledPage, SiteCrawlResult


def _page(url: str, label: str) -> CrawledPage:
    return CrawledPage(
        url=url,
        http_status=200,
        title=label,
        headings=[],
        important_text="",
        calls_to_action=[],
        forms=[],
        links=[],
        technical_signals={"has_viewport": True},
    )


class FakeBrowser:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def render(self, url: str, **_kwargs) -> BrowserRenderResponse:
        self.calls.append(url)
        slug = url.rstrip("/").rsplit("/", 1)[-1] or "home"
        return BrowserRenderResponse(
            final_url=url,
            title=f"Rendered {slug}",
            html=(
                "<html><main>"
                f"<h1>Rendered {slug}</h1>"
                "<p>This rendered page contains enough meaningful business content "
                "to replace the empty JavaScript application shell safely.</p>"
                "<a href='/contact'>Book consultation</a>"
                "</main></html>"
            ),
        )


@pytest.mark.asyncio
async def test_refinement_only_renders_flagged_pages_and_has_separate_cap():
    result = SiteCrawlResult(
        start_url="https://example.com/",
        pages=[
            _page("https://example.com/", "Home"),
            _page("https://example.com/services", "Services"),
            _page("https://example.com/pricing", "Pricing"),
            CrawledPage(
                url="https://example.com/contact",
                http_status=200,
                title="Contact",
                headings=["Contact"],
                important_text="Contact our clinic to schedule a consultation.",
                calls_to_action=["Book"],
                forms=[],
                links=[],
                technical_signals={"has_viewport": True},
            ),
        ],
        browser_fallback_urls=[
            "https://example.com/",
            "https://example.com/services",
            "https://example.com/pricing",
        ],
        skipped_urls={},
    )
    browser = FakeBrowser()

    refined = await refine_with_browser(
        result,
        browser=browser,
        max_render_pages=2,
    )

    assert browser.calls == [
        "https://example.com/",
        "https://example.com/services",
    ]
    assert refined.browser_fallback_urls == ["https://example.com/pricing"]

    homepage = next(page for page in refined.pages if page.url == "https://example.com/")
    services = next(page for page in refined.pages if page.url.endswith("/services"))
    pricing = next(page for page in refined.pages if page.url.endswith("/pricing"))
    contact = next(page for page in refined.pages if page.url.endswith("/contact"))

    assert homepage.headings == ["Rendered home"]
    assert "meaningful business content" in homepage.important_text
    assert services.headings == ["Rendered services"]
    assert pricing.important_text == ""
    assert contact.important_text == "Contact our clinic to schedule a consultation."
    assert homepage.http_status == 200
