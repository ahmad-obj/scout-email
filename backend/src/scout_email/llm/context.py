from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


_FORBIDDEN_KEYS = {
    "raw_html",
    "html",
    "dom",
    "browser_dump",
    "page_source",
}
_WRITER_KEYS = (
    "dossier_summary",
    "persuasion_brief",
    "allowed_evidence",
    "weberaise_context",
    "writing_rules",
    "approved_examples",
    "recent_corrections",
)


def sanitize_context(value: Any, *, max_text_chars: int = 12_000) -> Any:
    if max_text_chars <= 0:
        raise ValueError("max_text_chars must be positive")
    if isinstance(value, str):
        return value[:max_text_chars]
    if isinstance(value, Mapping):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.casefold() in _FORBIDDEN_KEYS:
                continue
            cleaned[key_text] = sanitize_context(item, max_text_chars=max_text_chars)
        return cleaned
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [sanitize_context(item, max_text_chars=max_text_chars) for item in value]
    return value


def build_writer_context(source: Mapping[str, Any], *, max_text_chars: int = 6_000) -> dict[str, Any]:
    """Return only the explicitly approved Writer context sections."""
    bounded = {
        key: source[key]
        for key in _WRITER_KEYS
        if key in source
    }
    return sanitize_context(bounded, max_text_chars=max_text_chars)
