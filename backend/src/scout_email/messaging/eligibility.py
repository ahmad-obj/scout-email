from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit


def normalize_email_identity(value: str | None) -> str:
    return (value or "").strip().casefold()


def normalize_domain_identity(value: str | None) -> str:
    raw = (value or "").strip().casefold()
    if not raw:
        return ""

    parsed = urlsplit(raw if "://" in raw else f"//{raw}")
    host = (parsed.hostname or "").strip().rstrip(".").casefold()
    if host.startswith("www."):
        host = host[4:]
    return host


def normalize_business_identity(value: str | None) -> str:
    return " ".join((value or "").strip().casefold().split())


@dataclass(frozen=True, slots=True)
class EligibilitySnapshot:
    approval_state: str
    approval_hash_matches: bool
    contact_verified: bool
    dnc_match: bool
    duplicate_outreach: bool
    human_reply_exists: bool
    campaign_active: bool
    daily_sent_count: int
    max_per_day: int
    sender_enabled: bool
    sender_healthy: bool


@dataclass(frozen=True, slots=True)
class EligibilityResult:
    allowed: bool
    reasons: list[str]


def evaluate_send_eligibility(snapshot: EligibilitySnapshot) -> EligibilityResult:
    """Evaluate all hard send gates without short-circuiting diagnostics."""
    reasons: list[str] = []
    if snapshot.approval_state != "APPROVED":
        reasons.append("not_approved")
    if not snapshot.approval_hash_matches:
        reasons.append("approval_hash_mismatch")
    if not snapshot.contact_verified:
        reasons.append("contact_not_verified")
    if snapshot.dnc_match:
        reasons.append("do_not_contact")
    if snapshot.duplicate_outreach:
        reasons.append("duplicate_outreach")
    if snapshot.human_reply_exists:
        reasons.append("human_reply_exists")
    if not snapshot.campaign_active:
        reasons.append("campaign_paused")
    if snapshot.max_per_day <= 0 or snapshot.daily_sent_count >= snapshot.max_per_day:
        reasons.append("daily_limit_reached")
    if not snapshot.sender_enabled:
        reasons.append("sender_disabled")
    if not snapshot.sender_healthy:
        reasons.append("sender_unhealthy")
    return EligibilityResult(allowed=not reasons, reasons=reasons)
