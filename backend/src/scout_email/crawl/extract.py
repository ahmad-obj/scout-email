from __future__ import annotations

from urllib.parse import urldefrag, urljoin

from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from scout_email.crawl.audit import audit_page


class PageExtraction(BaseModel):
    url: str
    title: str | None = None
    headings: list[str]
    important_text: str
    calls_to_action: list[str]
    forms: list[dict[str, object]]
    links: list[str]
    images: list[dict[str, object]] = Field(default_factory=list)
    technical_signals: dict[str, object]


def _text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _dimension(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value.isdigit():
        return None
    number = int(value)
    return number if number > 0 else None


def extract_page(
    html: str,
    url: str,
    *,
    text_limit: int = 12_000,
    http_status: int | None = None,
) -> PageExtraction:
    soup = BeautifulSoup(html or "", "lxml")

    title = _text(soup.title.get_text(" ", strip=True)) if soup.title else None
    headings = [
        value
        for tag in soup.select("h1, h2, h3")
        if (value := _text(tag.get_text(" ", strip=True)))
    ]

    calls_to_action = [
        value
        for tag in soup.select("a, button")
        if (value := _text(tag.get_text(" ", strip=True)))
    ]

    forms: list[dict[str, object]] = []
    for form in soup.find_all("form"):
        raw_action = form.get("action")
        action = urljoin(url, raw_action) if isinstance(raw_action, str) and raw_action.strip() else url
        method = str(form.get("method") or "get").casefold()
        input_types = [
            str(field.get("type") or "text").casefold()
            for field in form.find_all("input")
        ]
        forms.append(
            {
                "action": action,
                "method": method,
                "input_types": input_types,
            }
        )

    links: list[str] = []
    for link in soup.find_all("a", href=True):
        href = link.get("href")
        if not isinstance(href, str):
            continue
        href = href.strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        absolute, _fragment = urldefrag(urljoin(url, href))
        links.append(absolute)

    images: list[dict[str, object]] = []
    seen_images: set[str] = set()
    for image in soup.find_all("img", src=True):
        raw_src = image.get("src")
        if not isinstance(raw_src, str) or not raw_src.strip():
            continue
        src = urljoin(url, raw_src.strip())
        if src in seen_images:
            continue
        seen_images.add(src)
        images.append(
            {
                "src": src,
                "alt": _text(image.get("alt")) if isinstance(image.get("alt"), str) else None,
                "width": _dimension(image.get("width")),
                "height": _dimension(image.get("height")),
            }
        )

    technical_signals = audit_page(
        html,
        url,
        http_status=http_status,
    ).model_dump(mode="json")

    reduced = BeautifulSoup(html or "", "lxml")
    for tag in reduced.select("script, style, noscript, template, nav, footer, header, aside"):
        tag.decompose()
    content_root = reduced.find("main") or reduced.find("article") or reduced.body or reduced
    important_text = _text(content_root.get_text(" ", strip=True)) or ""
    important_text = important_text[:text_limit]

    return PageExtraction(
        url=url,
        title=title,
        headings=headings,
        important_text=important_text,
        calls_to_action=_dedupe(calls_to_action),
        forms=forms,
        links=_dedupe(links),
        images=images,
        technical_signals=technical_signals,
    )
