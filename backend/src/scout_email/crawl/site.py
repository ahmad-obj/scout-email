from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel

from scout_email.common.url_policy import UnsafeURLError, validate_public_http_url
from scout_email.crawl.discovery import select_candidate_urls
from scout_email.crawl.extract import PageExtraction, extract_page


_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class CrawledPage(PageExtraction):
    http_status: int


class SiteCrawlResult(BaseModel):
    start_url: str
    pages: list[CrawledPage]
    browser_fallback_urls: list[str]
    skipped_urls: dict[str, str]


def _root_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("start_url must be an absolute HTTP(S) URL")
    return urlunsplit((parsed.scheme, parsed.netloc, "/", "", ""))


def _sitemap_urls(xml: str) -> list[str]:
    soup = BeautifulSoup(xml or "", "xml")
    result: list[str] = []
    for loc in soup.find_all("loc"):
        value = " ".join(loc.get_text(" ", strip=True).split())
        if value:
            result.append(value)
    return result


def _is_html(response: httpx.Response) -> bool:
    content_type = response.headers.get("content-type", "").casefold()
    if "text/html" in content_type or "application/xhtml+xml" in content_type:
        return True
    stripped = response.text.lstrip().casefold()
    return stripped.startswith(("<!doctype html", "<html", "<head", "<body"))


def _needs_browser_render(html: str, extraction: PageExtraction) -> bool:
    if len(extraction.important_text.strip()) >= 80:
        return False
    lowered = html.casefold()
    shell_markers = (
        'id="__next"',
        "id='__next'",
        'id="__nuxt"',
        "id='__nuxt'",
        "data-reactroot",
        "/_next/static/",
        "/_nuxt/",
    )
    return any(marker in lowered for marker in shell_markers)


async def _fetch_with_redirects(
    url: str,
    *,
    client: httpx.AsyncClient,
    url_validator: Callable[[str], object],
    max_redirects: int = 5,
) -> tuple[httpx.Response | None, str, str | None]:
    current = url
    for redirect_index in range(max_redirects + 1):
        try:
            url_validator(current)
        except UnsafeURLError:
            return None, current, "UNSAFE_URL" if redirect_index == 0 else "UNSAFE_REDIRECT"

        try:
            response = await client.get(current, follow_redirects=False)
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
            return None, current, "NETWORK_ERROR"

        if response.status_code in _REDIRECT_STATUSES and response.headers.get("location"):
            if redirect_index >= max_redirects:
                return None, current, "REDIRECT_LIMIT"
            target = urljoin(current, response.headers["location"])
            try:
                url_validator(target)
            except UnsafeURLError:
                return None, current, "UNSAFE_REDIRECT"
            current = target
            continue

        return response, str(response.url), None

    return None, current, "REDIRECT_LIMIT"


async def crawl_site(
    start_url: str,
    *,
    client: httpx.AsyncClient | None = None,
    max_pages: int = 20,
    url_validator: Callable[[str], object] = validate_public_http_url,
) -> SiteCrawlResult:
    if max_pages < 1:
        return SiteCrawlResult(
            start_url=start_url,
            pages=[],
            browser_fallback_urls=[],
            skipped_urls={},
        )

    root = _root_url(start_url)
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            follow_redirects=False,
            headers={"User-Agent": "ScoutEmail/0.1 (+bounded public website research)"},
        )

    pages: list[CrawledPage] = []
    browser_fallback_urls: list[str] = []
    skipped_urls: dict[str, str] = {}
    discovered_urls: list[str] = []
    fetched: set[str] = set()

    try:
        root_response, root_final_url, root_error = await _fetch_with_redirects(
            root,
            client=client,
            url_validator=url_validator,
        )
        fetched.add(root)
        if root_error:
            skipped_urls[root] = root_error
        elif root_response is not None:
            if root_response.status_code >= 400:
                skipped_urls[root] = f"HTTP_{root_response.status_code}"
            elif not _is_html(root_response):
                skipped_urls[root] = "NON_HTML"
            else:
                extraction = extract_page(root_response.text, root_final_url)
                pages.append(
                    CrawledPage(
                        **extraction.model_dump(),
                        http_status=root_response.status_code,
                    )
                )
                discovered_urls.extend(extraction.links)
                if _needs_browser_render(root_response.text, extraction):
                    browser_fallback_urls.append(root_final_url)

        sitemap_url = urljoin(root, "sitemap.xml")
        sitemap_response, _sitemap_final, sitemap_error = await _fetch_with_redirects(
            sitemap_url,
            client=client,
            url_validator=url_validator,
        )
        fetched.add(sitemap_url)
        if sitemap_error is None and sitemap_response is not None and sitemap_response.status_code < 400:
            discovered_urls.extend(_sitemap_urls(sitemap_response.text))

        candidates = select_candidate_urls(root, discovered_urls, max_pages=max_pages)
        for candidate in candidates:
            if len(pages) >= max_pages:
                break
            if candidate == root or candidate in fetched:
                continue
            fetched.add(candidate)

            response, final_url, error = await _fetch_with_redirects(
                candidate,
                client=client,
                url_validator=url_validator,
            )
            if error:
                skipped_urls[candidate] = error
                continue
            if response is None:
                skipped_urls[candidate] = "NO_RESPONSE"
                continue
            if response.status_code >= 400:
                skipped_urls[candidate] = f"HTTP_{response.status_code}"
                continue
            if not _is_html(response):
                skipped_urls[candidate] = "NON_HTML"
                continue

            extraction = extract_page(response.text, final_url)
            pages.append(
                CrawledPage(
                    **extraction.model_dump(),
                    http_status=response.status_code,
                )
            )
            if _needs_browser_render(response.text, extraction):
                browser_fallback_urls.append(final_url)

        return SiteCrawlResult(
            start_url=start_url,
            pages=pages,
            browser_fallback_urls=list(dict.fromkeys(browser_fallback_urls)),
            skipped_urls=skipped_urls,
        )
    finally:
        if owns_client:
            await client.aclose()
