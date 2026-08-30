from __future__ import annotations

from collections.abc import Sequence

from rapidfuzz.fuzz import ratio

from scout_email.leads.normalize import normalize_name
from scout_email.leads.schemas import ExistingLead, MatchResult, NormalizedLead

FUZZY_NAME_THRESHOLD = 92.0


def _conflicting_identifiers(candidate: NormalizedLead, existing: ExistingLead) -> bool:
    if candidate.phone and existing.phone and candidate.phone != existing.phone:
        return True
    if candidate.canonical_domain and existing.canonical_domain and candidate.canonical_domain != existing.canonical_domain:
        return True
    return False


def match_existing_lead(
    candidate: NormalizedLead,
    candidates: Sequence[ExistingLead],
) -> MatchResult | None:
    if candidate.phone:
        for existing in candidates:
            if existing.phone == candidate.phone:
                return MatchResult(lead_id=existing.id, reason="exact_phone", confidence=1.0)

    if candidate.canonical_domain:
        for existing in candidates:
            if existing.canonical_domain == candidate.canonical_domain:
                return MatchResult(lead_id=existing.id, reason="exact_domain", confidence=0.99)

    best: tuple[float, ExistingLead] | None = None
    candidate_city = normalize_name(candidate.city) if candidate.city else None
    for existing in candidates:
        if _conflicting_identifiers(candidate, existing):
            continue
        existing_city = normalize_name(existing.city) if existing.city else None
        if not candidate_city or candidate_city != existing_city:
            continue
        score = ratio(candidate.normalized_name, existing.normalized_name)
        if score >= FUZZY_NAME_THRESHOLD and (best is None or score > best[0]):
            best = (score, existing)

    if best is None:
        return None
    score, existing = best
    return MatchResult(
        lead_id=existing.id,
        reason="fuzzy_name_city",
        confidence=round(score / 100.0, 4),
    )
