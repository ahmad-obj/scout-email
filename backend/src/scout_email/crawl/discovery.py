from __future__ import annotations

from urllib.parse import urljoin, urlsplit, urlunsplit


_BLOCKED_SEGMENTS = {
    "privacy",
    "privacy-policy",
    "terms",
    "terms-of-service",
    "legal",
    "cookies",
    "cookie-policy",
    "tag",
    "tags",
    "category",
    "categories",
    "author",
    "feed",
    "wp-json",
    "wp-admin",
    "login",
    "cart",
    "checkout",
}

_PRIORITY_PREFIXES = (
    ("services", 10),
    ("service", 10),
    ("pricing", 15),
    ("case-studies", 20),
    ("case-study", 20),
    ("portfolio", 22),
    ("work", 22),
    ("contact", 25),
    ("about", 30),
    ("faq", 35),
    ("products", 40),
    ("product", 40),
    ("locations", 45),
    ("testimonials", 50),
    ("reviews", 50),
    ("blog", 100),
    ("news", 100),
)


def _host_key(host: str | None) -> str:
    value = (host or "").casefold().rstrip(".")
    return value[4:] if value.startswith("www.") else value


def _canonical_candidate(base_url: str, raw_url: str) -> str | None:
    try:
        joined = urljoin(base_url, raw_url)
        parsed = urlsplit(joined)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if _host_key(parsed.hostname) != _host_key(urlsplit(base_url).hostname):
        return None

    path = parsed.path or "/"
    parts = {part.casefold() for part in path.split("/") if part}
    if parts & _BLOCKED_SEGMENTS:
        return None

    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _dedupe_key(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return _host_key(parsed.hostname), path.casefold()


def _priority(url: str) -> tuple[int, int, str]:
    path = urlsplit(url).path.casefold().strip("/")
    first = path.split("/", 1)[0] if path else ""
    score = 80
    for prefix, value in _PRIORITY_PREFIXES:
        if first == prefix or path.startswith(prefix + "/"):
            score = value
            break
    depth = path.count("/") + (1 if path else 0)
    return score, depth, path


def select_candidate_urls(
    base_url: str,
    discovered_urls: list[str],
    *,
    max_pages: int = 20,
) -> list[str]:
    if max_pages < 1:
        return []

    root_parsed = urlsplit(base_url)
    if root_parsed.scheme not in {"http", "https"} or not root_parsed.hostname:
        raise ValueError("base_url must be an absolute HTTP(S) URL")
    root = urlunsplit((root_parsed.scheme, root_parsed.netloc, "/", "", ""))

    unique: dict[tuple[str, str], str] = {_dedupe_key(root): root}
    for raw_url in discovered_urls:
        candidate = _canonical_candidate(base_url, raw_url)
        if candidate is None:
            continue
        unique.setdefault(_dedupe_key(candidate), candidate)

    others = [url for key, url in unique.items() if key != _dedupe_key(root)]
    others.sort(key=_priority)
    return [root, *others[: max_pages - 1]]
