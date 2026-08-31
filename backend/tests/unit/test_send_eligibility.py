from __future__ import annotations

from dataclasses import replace

import pytest

from scout_email.messaging.eligibility import EligibilitySnapshot, evaluate_send_eligibility


def _eligible() -> EligibilitySnapshot:
    return EligibilitySnapshot(
        approval_state="APPROVED",
        approval_hash_matches=True,
        contact_verified=True,
        dnc_match=False,
        duplicate_outreach=False,
        human_reply_exists=False,
        campaign_active=True,
        daily_sent_count=0,
        max_per_day=10,
        sender_enabled=True,
        sender_healthy=True,
    )


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"approval_state": "PENDING"}, "not_approved"),
        ({"approval_hash_matches": False}, "approval_hash_mismatch"),
        ({"contact_verified": False}, "contact_not_verified"),
        ({"dnc_match": True}, "do_not_contact"),
        ({"duplicate_outreach": True}, "duplicate_outreach"),
        ({"human_reply_exists": True}, "human_reply_exists"),
        ({"campaign_active": False}, "campaign_paused"),
        ({"daily_sent_count": 10}, "daily_limit_reached"),
        ({"sender_enabled": False}, "sender_disabled"),
        ({"sender_healthy": False}, "sender_unhealthy"),
    ],
)
def test_each_hard_block_fails_closed(changes, reason):
    snapshot = replace(_eligible(), **changes)
    result = evaluate_send_eligibility(snapshot)
    assert result.allowed is False
    assert reason in result.reasons


def test_fully_eligible_snapshot_is_allowed():
    result = evaluate_send_eligibility(_eligible())
    assert result.allowed is True
    assert result.reasons == []
