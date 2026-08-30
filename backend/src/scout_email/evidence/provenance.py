from __future__ import annotations

from collections.abc import Iterable

from scout_email.common.enums import ClaimClass


class UnverifiedClaimError(ValueError):
    """Raised when an UNVERIFIED claim is considered for outgoing use."""


class UnsupportedClaimError(ValueError):
    """Raised when a sendable claim has no valid supporting evidence IDs."""


def assert_claim_supported(evidence_ids: Iterable[int], claim_class: ClaimClass) -> None:
    """Fail closed unless a claim class is sendable and has stable evidence IDs."""
    if claim_class is ClaimClass.UNVERIFIED:
        raise UnverifiedClaimError("UNVERIFIED claims cannot be used in outgoing copy")

    ids = list(evidence_ids)
    if not ids or any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in ids):
        raise UnsupportedClaimError("sendable claims require positive persisted evidence IDs")
