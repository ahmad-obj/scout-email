from __future__ import annotations

import re
from urllib.parse import unquote

from bs4 import BeautifulSoup
from pydantic import BaseModel, Field


_EMAIL_RE = re.compile(
    r"(?<![A-Z0-9._%+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,63})(?![A-Z0-9._%+-])",
    re.IGNORECASE,
)


class ContactCandidate(BaseModel):
    email: str
    source_url: str
    contact_type: str = "business"
    confidence: float = Field(ge=0, le=1)


def _normalize_email(value: str) -> str | None:
    value = unquote(value).strip().strip("<>()[]{}.,;:'\"").casefold()
    if not value or len(value) > 320 or not _EMAIL_RE.fullmatch(value):
        return None
    local, domain = value.rsplit("@", 1)
    if local.startswith(".") or local.endswith(".") or ".." in local:
        return None
    if domain.startswith("-") or domain.endswith("-") or ".." in domain:
        return None
    return value


def extract_public_contacts(html: str, source_url: str) -> list[ContactCandidate]:
    """Extract only addresses that are actually present in public source material.

    This function has no inputs from which an address could be synthesized. It
    consumes HTML plus its source URL and returns only literal addresses found in
    mailto links or visible page text.
    """
    if not source_url.strip():
        raise ValueError("source_url is required for contact provenance")

    soup = BeautifulSoup(html or "", "lxml")
    found: dict[str, ContactCandidate] = {}

    for link in soup.select('a[href^="mailto:"]'):
        href = link.get("href")
        if not isinstance(href, str):
            continue
        target = href[7:].split("?", 1)[0]
        for raw in target.split(","):
            email = _normalize_email(raw)
            if email:
                found[email] = ContactCandidate(
                    email=email,
                    source_url=source_url,
                    confidence=1.0,
                )

    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    visible_text = soup.get_text(" ", strip=True)
    for match in _EMAIL_RE.finditer(visible_text):
        email = _normalize_email(match.group(1))
        if not email or email in found:
            continue
        found[email] = ContactCandidate(
            email=email,
            source_url=source_url,
            confidence=0.95,
        )

    return sorted(found.values(), key=lambda candidate: candidate.email)
