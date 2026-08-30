from __future__ import annotations

from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from pydantic import BaseModel, Field


_CTA_PREFIXES = (
    "book",
    "request",
    "contact",
    "schedule",
    "reserve",
    "get quote",
    "get a quote",
    "call",
    "start",
    "sign up",
    "signup",
)
_SOCIAL_HOSTS = {
    "instagram.com",
    "www.instagram.com",
    "linkedin.com",
    "www.linkedin.com",
    "facebook.com",
    "www.facebook.com",
    "x.com",
    "www.x.com",
    "twitter.com",
    "www.twitter.com",
    "youtube.com",
    "www.youtube.com",
    "tiktok.com",
    "www.tiktok.com",
}


class PageAudit(BaseModel):
    http_status: int | None = None
    uses_https: bool
    title: str | None = None
    title_present: bool
    meta_description: str | None = None
    missing_meta_description: bool
    has_viewport: bool
    has_responsive_indicators: bool
    canonical: str | None = None
    has_open_graph: bool
    has_structured_data: bool
    has_favicon: bool
    cta_count: int
    social_links: list[str] = Field(default_factory=list)
    image_count: int
    declared_image_dimension_count: int
    page_weight_bytes: int


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _is_cta(text: str) -> bool:
    normalized = " ".join(text.casefold().split())
    return any(normalized.startswith(prefix) for prefix in _CTA_PREFIXES)


def _social_links(soup: BeautifulSoup) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for link in soup.find_all("a", href=True):
        href = link.get("href")
        if not isinstance(href, str):
            continue
        try:
            host = (urlsplit(href).hostname or "").casefold().rstrip(".")
        except ValueError:
            continue
        if host not in _SOCIAL_HOSTS or href in seen:
            continue
        seen.add(href)
        result.append(href)
    return result


def audit_page(html: str, url: str, *, http_status: int | None = None) -> PageAudit:
    """Return deterministic, directly observable technical facts for one page."""
    soup = BeautifulSoup(html or "", "lxml")

    title = _clean_text(soup.title.get_text(" ", strip=True)) if soup.title else None
    meta = soup.find(
        "meta",
        attrs={"name": lambda value: isinstance(value, str) and value.casefold() == "description"},
    )
    meta_description = (
        _clean_text(meta.get("content"))
        if meta is not None and isinstance(meta.get("content"), str)
        else None
    )
    viewport = soup.find(
        "meta",
        attrs={"name": lambda value: isinstance(value, str) and value.casefold() == "viewport"},
    )
    canonical_tag = soup.find("link", rel=lambda value: value and "canonical" in value)
    canonical_href = canonical_tag.get("href") if canonical_tag is not None else None
    canonical = urljoin(url, canonical_href) if isinstance(canonical_href, str) and canonical_href else None

    has_open_graph = soup.find(
        "meta",
        attrs={"property": lambda value: isinstance(value, str) and value.casefold().startswith("og:")},
    ) is not None
    has_structured_data = any(
        isinstance(tag.get("type"), str)
        and tag.get("type").casefold() == "application/ld+json"
        for tag in soup.find_all("script")
    )
    has_favicon = any(
        "icon" in [str(item).casefold() for item in (tag.get("rel") or [])]
        for tag in soup.find_all("link")
    )

    style_text = " ".join(tag.get_text(" ", strip=True) for tag in soup.find_all("style"))
    has_viewport = viewport is not None
    has_responsive_indicators = has_viewport or "@media" in style_text.casefold()

    cta_count = 0
    for tag in soup.select("a, button"):
        text = _clean_text(tag.get_text(" ", strip=True))
        if text and _is_cta(text):
            cta_count += 1

    images = soup.find_all("img")
    declared_dimensions = sum(
        1
        for image in images
        if isinstance(image.get("width"), str)
        and image.get("width").strip()
        and isinstance(image.get("height"), str)
        and image.get("height").strip()
    )

    return PageAudit(
        http_status=http_status,
        uses_https=urlsplit(url).scheme.casefold() == "https",
        title=title,
        title_present=title is not None,
        meta_description=meta_description,
        missing_meta_description=meta_description is None,
        has_viewport=has_viewport,
        has_responsive_indicators=has_responsive_indicators,
        canonical=canonical,
        has_open_graph=has_open_graph,
        has_structured_data=has_structured_data,
        has_favicon=has_favicon,
        cta_count=cta_count,
        social_links=_social_links(soup),
        image_count=len(images),
        declared_image_dimension_count=declared_dimensions,
        page_weight_bytes=len((html or "").encode("utf-8")),
    )
