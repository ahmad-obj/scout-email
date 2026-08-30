from __future__ import annotations

import re

from rapidfuzz.fuzz import ratio


_WHITESPACE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WHITESPACE.sub(" ", text.casefold().strip())


def structure_similarity(first: str, second: str) -> float:
    """Return a lightweight normalized similarity score in [0, 1]."""
    left = _normalize(first)
    right = _normalize(second)
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return round(ratio(left, right) / 100.0, 6)


def max_recent_similarity(candidate: str, recent: list[str] | tuple[str, ...]) -> float:
    if not recent:
        return 0.0
    return max(structure_similarity(candidate, item) for item in recent)
