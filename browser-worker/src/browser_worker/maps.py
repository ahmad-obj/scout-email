from __future__ import annotations

import re
from urllib.parse import unquote

from bs4 import BeautifulSoup, Tag

from browser_worker.schemas import BrowserMapLead

_RESULT_LINK_SELECTOR = 'a.hfpxzc[href*="/maps/place/"]'
_ADDRESS_SELECTOR = '[data-item-id="address"]'
_PHONE_SELECTOR = '[data-item-id^="phone:tel:"]'
_WEBSITE_SELECTOR = 'a[data-item-id="authority"]'
_CATEGORY_SELECTORS = ('[data-testid="category"]', 'button[jsaction*="category"]')
_RATING_TEXT_RE = re.compile(r"(?P<rating>[0-5](?:\.\d+)?)\s*stars?", re.I)
_REVIEWS_TEXT_RE = re.compile(r"(?P<count>[\d,]+)\s*reviews?", re.I)
_EXTERNAL_ID_RE = re.compile(r"(?:^|!)1s(?P<id>0x[0-9a-f]+:0x[0-9a-f]+)", re.I)

# Playwright selectors are centralized here so Maps DOM drift is isolated.
# The generic text input is intentionally last: some headless Maps variants
# render the search box without the legacy id/aria-label, but expose exactly
# one visible text input in the Maps shell.
SEARCH_INPUT_SELECTORS = (
    "#searchboxinput",
    'input[aria-label*="Search Google Maps"]',
    'input[type="text"]',
)
RESULT_FEED_SELECTORS = (
    'div[role="feed"]',
    'div[aria-label^="Results for"]',
)
RESULT_LINK_SELECTORS = (
    'a.hfpxzc[href*="/maps/place/"]',
    'a[href*="/maps/place/"]',
)
DETAIL_HEADING_SELECTORS = (
    "h1.DUwDvf",
    "h1",
)


class MapsSearchError(RuntimeError):
    """Raised when Google Maps cannot produce a usable search result."""


def _attr_text(tag: Tag | None, attr: str, prefix: str | None = None) -> str | None:
    if tag is None:
        return None
    value = tag.get(attr)
    if not isinstance(value, str):
        return None
    value = value.strip()
    if prefix and value.casefold().startswith(prefix.casefold()):
        value = value[len(prefix):].strip()
    return value or None


def _parse_rating(text: str | None) -> float | None:
    if not text:
        return None
    match = _RATING_TEXT_RE.search(text)
    return float(match.group("rating")) if match else None


def _parse_reviews(text: str | None) -> int | None:
    if not text:
        return None
    match = _REVIEWS_TEXT_RE.search(text)
    return int(match.group("count").replace(",", "")) if match else None


def _source_external_id(url: str | None) -> str | None:
    if not url:
        return None
    match = _EXTERNAL_ID_RE.search(unquote(url))
    return match.group("id") if match else None


def _rating_review_text(root: Tag | BeautifulSoup) -> tuple[float | None, int | None]:
    rating: float | None = None
    reviews: int | None = None
    for tag in root.find_all(attrs={"aria-label": True}):
        label = tag.get("aria-label")
        if not isinstance(label, str):
            continue
        if rating is None:
            rating = _parse_rating(label)
        if reviews is None:
            reviews = _parse_reviews(label)
        if rating is not None and reviews is not None:
            break
    return rating, reviews


def extract_results_html(html: str, *, max_results: int = 25) -> list[BrowserMapLead]:
    soup = BeautifulSoup(html, "lxml")
    leads: list[BrowserMapLead] = []
    seen_urls: set[str] = set()

    for link in soup.select(_RESULT_LINK_SELECTOR):
        if len(leads) >= max_results:
            break
        href = _attr_text(link, "href")
        name = _attr_text(link, "aria-label")
        if not href or not name or href in seen_urls:
            continue
        seen_urls.add(href)

        card = link.find_parent(attrs={"role": "article"}) or link.parent
        category = None
        address = None
        if isinstance(card, Tag):
            details = card.select_one(".fontBodyMedium")
            if details:
                values = [
                    span.get_text(" ", strip=True)
                    for span in details.find_all("span", recursive=False)
                    if span.get_text(" ", strip=True) not in {"·", ""}
                ]
                if values:
                    category = values[0]
                if len(values) > 1:
                    address = values[-1]
            rating, reviews = _rating_review_text(card)
        else:
            rating, reviews = None, None

        leads.append(
            BrowserMapLead(
                name=name,
                category=category,
                address=address,
                rating=rating,
                review_count=reviews,
                maps_url=href,
                source_external_id=_source_external_id(href),
            )
        )

    return leads


def extract_listing_html(html: str) -> BrowserMapLead:
    soup = BeautifulSoup(html, "lxml")
    heading = soup.find("h1")
    if heading is None or not heading.get_text(" ", strip=True):
        raise ValueError("Maps listing HTML does not contain a business heading")

    canonical = soup.find("link", rel="canonical")
    maps_url = _attr_text(canonical, "href")
    address = _attr_text(soup.select_one(_ADDRESS_SELECTOR), "aria-label", "Address:")
    phone = _attr_text(soup.select_one(_PHONE_SELECTOR), "aria-label", "Phone:")
    website = _attr_text(soup.select_one(_WEBSITE_SELECTOR), "href")

    category = None
    for selector in _CATEGORY_SELECTORS:
        category_tag = soup.select_one(selector)
        if category_tag is not None:
            category = category_tag.get_text(" ", strip=True) or None
            if category:
                break

    rating, reviews = _rating_review_text(soup)
    return BrowserMapLead(
        name=heading.get_text(" ", strip=True),
        category=category,
        address=address,
        phone=phone,
        website=website,
        rating=rating,
        review_count=reviews,
        maps_url=maps_url,
        source_external_id=_source_external_id(maps_url),
    )


async def _first_visible(page, selectors: tuple[str, ...]):
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if await locator.count() and await locator.is_visible():
                return locator
        except Exception:
            continue
    return None


async def _dismiss_consent(page) -> None:
    for label in ("Accept all", "I agree", "Accept"):
        try:
            button = page.get_by_role("button", name=label, exact=True)
            if await button.count() and await button.first.is_visible():
                await button.first.click(timeout=2_000)
                return
        except Exception:
            continue


async def _collect_result_urls(page, max_results: int) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    no_growth_rounds = 0

    for _ in range(20):
        for selector in RESULT_LINK_SELECTORS:
            locator = page.locator(selector)
            try:
                hrefs = await locator.evaluate_all(
                    "els => els.map(el => el.href).filter(Boolean)"
                )
            except Exception:
                continue
            for href in hrefs:
                if href not in seen:
                    seen.add(href)
                    urls.append(href)
                    if len(urls) >= max_results:
                        return urls

        before = len(urls)
        feed = await _first_visible(page, RESULT_FEED_SELECTORS)
        if feed is None:
            break
        try:
            await feed.evaluate(
                "el => el.scrollBy(0, Math.max(el.clientHeight * 1.5, 900))"
            )
            await page.wait_for_timeout(600)
        except Exception:
            break
        if len(urls) == before:
            no_growth_rounds += 1
            if no_growth_rounds >= 3:
                break
        else:
            no_growth_rounds = 0

    return urls[:max_results]


async def search_maps(runtime, query: str, max_results: int = 25) -> list[BrowserMapLead]:
    from browser_worker.render import install_network_guard

    if not query.strip():
        raise ValueError("query must not be blank")
    max_results = max(1, min(max_results, 100))

    async with runtime.page(viewport={"width": 1440, "height": 1000}) as page:
        await install_network_guard(page)
        try:
            await page.goto("https://www.google.com/maps", wait_until="domcontentloaded")
            await _dismiss_consent(page)

            search_input = await _first_visible(page, SEARCH_INPUT_SELECTORS)
            if search_input is None:
                raise MapsSearchError("Google Maps search input was not found")
            await search_input.fill(query)
            await search_input.press("Enter")

            try:
                await page.wait_for_function(
                    """() => document.querySelector('div[role="feed"]') ||
                    document.querySelector('a[href*="/maps/place/"]') ||
                    document.querySelector('h1')""",
                    timeout=runtime.settings.navigation_timeout_ms,
                )
            except Exception as error:
                raise MapsSearchError("Google Maps results did not become available") from error

            await page.wait_for_timeout(800)
            snapshot = await page.content()
            summaries = extract_results_html(snapshot, max_results=max_results)
            summary_by_url = {lead.maps_url: lead for lead in summaries if lead.maps_url}
            urls = await _collect_result_urls(page, max_results)

            if not urls:
                try:
                    return [extract_listing_html(snapshot)]
                except ValueError as error:
                    raise MapsSearchError("Google Maps returned no business listings") from error

            results: list[BrowserMapLead] = []
            for maps_url in urls:
                try:
                    await page.goto(maps_url, wait_until="domcontentloaded")
                    heading = await _first_visible(page, DETAIL_HEADING_SELECTORS)
                    if heading is not None:
                        await heading.wait_for(state="visible", timeout=8_000)
                    await page.wait_for_timeout(300)
                    lead = extract_listing_html(await page.content())
                    updates: dict[str, str] = {}
                    if not lead.maps_url:
                        updates["maps_url"] = maps_url
                    if not lead.source_external_id:
                        external_id = _source_external_id(maps_url)
                        if external_id:
                            updates["source_external_id"] = external_id
                    if updates:
                        lead = lead.model_copy(update=updates)
                    results.append(lead)
                except Exception:
                    fallback = summary_by_url.get(maps_url)
                    if fallback is not None:
                        results.append(fallback)
                if len(results) >= max_results:
                    break

            if not results:
                raise MapsSearchError("All Google Maps listing extractions failed")
            return results
        except MapsSearchError:
            raise
        except Exception as error:
            raise MapsSearchError(f"Google Maps search failed: {error}") from error
