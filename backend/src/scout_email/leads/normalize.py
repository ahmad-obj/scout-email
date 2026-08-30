from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit

from scout_email.leads.schemas import NormalizedLead, RawLead

_WHITESPACE_RE = re.compile(r"\s+")
_NAME_SEP_RE = re.compile(r"[^\w]+", flags=re.UNICODE)


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    value = _WHITESPACE_RE.sub(" ", value.strip())
    return value or None


def normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold().replace("&", " ")
    value = _NAME_SEP_RE.sub(" ", value)
    return _WHITESPACE_RE.sub(" ", value).strip()


def normalize_phone(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    digits = "".join(ch for ch in value if ch.isdigit())
    if not digits:
        return None
    return ("+" if value.startswith("+") else "") + digits


def canonical_domain(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    parsed = urlsplit(candidate if "://" in candidate else f"//{candidate}")
    host = parsed.hostname
    if not host:
        return None
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    host = host.casefold().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host or None


def normalize_lead(raw: RawLead) -> NormalizedLead:
    name = _clean_optional(raw.name)
    if not name:
        raise ValueError("lead name must not be blank")
    return NormalizedLead(
        name=name,
        normalized_name=normalize_name(name),
        category=_clean_optional(raw.category),
        city=_clean_optional(raw.city),
        address=_clean_optional(raw.address),
        phone=normalize_phone(raw.phone),
        canonical_domain=canonical_domain(raw.website),
        maps_url=_clean_optional(raw.maps_url),
        rating=raw.rating,
        review_count=raw.review_count,
    )
