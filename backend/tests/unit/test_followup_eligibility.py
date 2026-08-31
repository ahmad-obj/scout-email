from __future__ import annotations

from dataclasses import replace

import pytest

from scout_email.replies.followup import FollowupEligibilitySnapshot, evaluate_followup_eligibility


def _eligible() -> FollowupEligibilitySnapshot:
    return FollowupEligibilitySnapshot(
        current_stage=0,
        elapsed_seconds=4 * 24 * 60 * 60,
        required_delay_seconds=3 * 24 * 60 * 60,
        campaign_active=True,
        thread_cancelled=False,
        contact_verified=True,
        dnc_match=False,
        reply_exists=False,
        hard_bounce_exists=False,
        followup_stage_one_exists=False,
    )


def test_followup_is_allowed_only_after_delay_with_clean_thread_state():
    result = evaluate_followup_eligibility(_eligible())
    assert result.allowed is True
    assert result.reasons == []


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"current_stage": 1}, "max_stage_reached"),
        ({"elapsed_seconds": 60}, "followup_not_due"),
        ({"campaign_active": False}, "campaign_paused"),
        ({"thread_cancelled": True}, "thread_cancelled"),
        ({"contact_verified": False}, "contact_not_verified"),
        ({"dnc_match": True}, "do_not_contact"),
        ({"reply_exists": True}, "reply_exists"),
        ({"hard_bounce_exists": True}, "hard_bounce_exists"),
        ({"followup_stage_one_exists": True}, "followup_already_exists"),
    ],
)
def test_followup_hard_blocks_are_fail_closed(changes, reason):
    result = evaluate_followup_eligibility(replace(_eligible(), **changes))
    assert result.allowed is False
    assert reason in result.reasons
