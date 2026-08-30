import httpx
import pytest

from scout_email.common.url_policy import UnsafeURLError
from scout_email.crawl.site import crawl_site


@pytest.mark.asyncio
async def test_crawl_site_combines_homepage_and_sitemap_with_global_page_bound():
    requested: list[str] = []
    responses = {
        "https://example.com/": httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="""
            <html><body><main>
              <h1>Acme Dental</h1>
              <a href="/services">Services</a>
              <a href="/contact">Contact</a>
              <a href="https://other.example/about">External</a>
            </main></body></html>
            """,
        ),
        "https://example.com/sitemap.xml": httpx.Response(
            200,
            headers={"content-type": "application/xml"},
            text="""<?xml version="1.0"?>
            <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
              <url><loc>https://example.com/pricing</loc></url>
              <url><loc>https://example.com/about</loc></url>
              <url><loc>https://example.com/privacy-policy</loc></url>
            </urlset>
            """,
        ),
        "https://example.com/services": httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<html><main><h1>Services</h1><p>Implants and whitening.</p></main></html>",
        ),
        "https://example.com/pricing": httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<html><main><h1>Pricing</h1><p>Consultation pricing.</p></main></html>",
        ),
        "https://example.com/contact": httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<html><main><h1>Contact</h1><p>Book an appointment.</p></main></html>",
        ),
        "https://example.com/about": httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<html><main><h1>About</h1><p>Established clinic.</p></main></html>",
        ),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        requested.append(url)
        response = responses.get(url)
        if response is None:
            return httpx.Response(404, request=request)
        response.request = request
        return response

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
    ) as client:
        result = await crawl_site(
            "https://example.com/",
            client=client,
            max_pages=4,
            url_validator=lambda _url: None,
        )

    assert [page.url for page in result.pages] == [
        "https://example.com/",
        "https://example.com/services",
        "https://example.com/pricing",
        "https://example.com/contact",
    ]
    assert len(result.pages) == 4
    assert result.browser_fallback_urls == []
    assert "https://example.com/sitemap.xml" in requested
    assert "https://example.com/privacy-policy" not in requested
    assert "https://other.example/about" not in requested
    assert "https://example.com/about" not in requested


@pytest.mark.asyncio
async def test_crawl_site_revalidates_redirect_before_following_it():
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(
            302,
            headers={"location": "http://127.0.0.1/admin"},
            request=request,
        )

    def validator(url: str):
        if "127.0.0.1" in url:
            raise UnsafeURLError("private redirect")
        return None

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
    ) as client:
        result = await crawl_site(
            "https://example.com/",
            client=client,
            max_pages=3,
            url_validator=validator,
        )

    assert requested == ["https://example.com/", "https://example.com/sitemap.xml"]
    assert result.pages == []
    assert result.skipped_urls["https://example.com/"] == "UNSAFE_REDIRECT"


@pytest.mark.asyncio
async def test_crawl_site_marks_thin_javascript_shell_for_browser_fallback():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("sitemap.xml"):
            return httpx.Response(404, request=request)
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="""
            <html><body>
              <div id="__next"></div>
              <script src="/_next/static/app.js"></script>
            </body></html>
            """,
            request=request,
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
    ) as client:
        result = await crawl_site(
            "https://example.com/",
            client=client,
            max_pages=2,
            url_validator=lambda _url: None,
        )

    assert len(result.pages) == 1
    assert result.browser_fallback_urls == ["https://example.com/"]
