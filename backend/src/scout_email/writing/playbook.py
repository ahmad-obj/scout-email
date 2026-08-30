from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


_REQUIRED_FILES = (
    "company_context.md",
    "writing_rules.md",
    "banned_phrases.md",
    "cta_rules.md",
    "approved_examples.json",
    "rejected_patterns.json",
)


@dataclass(frozen=True, slots=True)
class WritingPlaybook:
    company_context: str
    writing_rules: str
    banned_phrases: tuple[str, ...]
    cta_rules: str
    approved_examples: tuple[Any, ...]
    rejected_patterns: tuple[Any, ...]
    version_hash: str


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _read_required(root: Path, name: str) -> bytes:
    path = root / name
    if not path.is_file():
        raise FileNotFoundError(f"required playbook source is missing: {name}")
    return path.read_bytes()


def load_playbook(root: Path | str) -> WritingPlaybook:
    root_path = Path(root)
    sources = {name: _read_required(root_path, name) for name in _REQUIRED_FILES}

    digest = sha256()
    for name in _REQUIRED_FILES:
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sources[name])
        digest.update(b"\0")

    company_context = sources["company_context.md"].decode("utf-8").strip()
    writing_rules = sources["writing_rules.md"].decode("utf-8").strip()
    cta_rules = sources["cta_rules.md"].decode("utf-8").strip()
    banned_phrases = tuple(
        line.strip()
        for line in sources["banned_phrases.md"].decode("utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )

    approved = json.loads(sources["approved_examples.json"])
    rejected = json.loads(sources["rejected_patterns.json"])
    if not isinstance(approved, list):
        raise ValueError("approved_examples.json must contain a JSON array")
    if not isinstance(rejected, list):
        raise ValueError("rejected_patterns.json must contain a JSON array")

    return WritingPlaybook(
        company_context=company_context,
        writing_rules=writing_rules,
        banned_phrases=banned_phrases,
        cta_rules=cta_rules,
        approved_examples=tuple(_freeze(item) for item in approved),
        rejected_patterns=tuple(_freeze(item) for item in rejected),
        version_hash=digest.hexdigest(),
    )
