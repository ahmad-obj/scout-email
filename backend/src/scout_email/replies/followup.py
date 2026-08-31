from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FollowupEligibilitySnapshot:
    current_stage: int
    elapsed_seconds: float
    required_delay_seconds: float
    campaign_active: bool
    thread_cancelled: bool
    contact_verified: bool
    dnc_match: bool
    reply_exists: bool
    hard_bounce_exists: bool
    followup_stage_one_exists: bool


@dataclass(frozen=True, slots=True)
class FollowupEligibilityResult:
    allowed: bool
    reasons: list[str]


def evaluate_followup_eligibility(
    snapshot: FollowupEligibilitySnapshot,
) -> FollowupEligibilityResult:
    reasons: list[str] = []
    if snapshot.current_stage >= 1:
        reasons.append("max_stage_reached")
    if snapshot.elapsed_seconds < snapshot.required_delay_seconds:
        reasons.append("followup_not_due")
    if not snapshot.campaign_active:
        reasons.append("campaign_paused")
    if snapshot.thread_cancelled:
        reasons.append("thread_cancelled")
    if not snapshot.contact_verified:
        reasons.append("contact_not_verified")
    if snapshot.dnc_match:
        reasons.append("do_not_contact")
    if snapshot.reply_exists:
        reasons.append("reply_exists")
    if snapshot.hard_bounce_exists:
        reasons.append("hard_bounce_exists")
    if snapshot.followup_stage_one_exists:
        reasons.append("followup_already_exists")
    return FollowupEligibilityResult(allowed=not reasons, reasons=reasons)
