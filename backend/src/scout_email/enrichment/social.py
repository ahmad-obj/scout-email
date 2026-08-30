from __future__ import annotations

from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from pydantic import BaseModel


_NETWORK_DOMAINS = {
    "instagram": {"instagram.com", "www.instagram.com"},
    "facebook": {"facebook.com", "www.facebook.com", "fb.com", "www.fb.com"},
    "linkedin": {"linkedin.com", "www.linkedin.com"},
    "youtube": {"youtube.com", "www.youtube.com", "youtu.be"},
    "tiktok": {"tiktok.com", "www.tiktok.com"},
    "x": {"x.com", "www.x.com", "twitter.com", "www.twitter.com"},
}


class SocialProfileCandidate(BaseModel):
    network: str
    url: str
    source_url: str
    verified: bool = True


def _network_for_url(url: str) -> str | None:
    try:
        host = (urlsplit(url).hostname or "").casefold().rstrip(".")
    except ValueError:
        return None
    for network, domains in _NETWORK_DOMAINS.items():
        if host in domains:
            return network
    return None


def discover_social_profiles(html: str, source_url: str) -> list[SocialProfileCandidate]:
    if not source_url.strip():
        raise ValueError("source_url is required for social provenance")

    soup = BeautifulSoup(html or "", "lxml")
    found: dict[tuple[str, str], SocialProfileCandidate] = {}
    for link in soup.find_all("a", href=True):
        href = link.get("href")
        if not isinstance(href, str) or not href.startswith(("https://", "http://")):
            continue
        network = _network_for_url(href)
        if network is None:
            continue
        key = (network, href.rstrip("/"))
        found[key] = SocialProfileCandidate(
            network=network,
            url=href,
            source_url=source_url,
            verified=True,
        )
    return sorted(found.values(), key=lambda item: (item.network, item.url))
