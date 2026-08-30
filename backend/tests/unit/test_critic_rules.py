from scout_email.common.enums import ClaimClass
from scout_email.writing.critic import scan_hard_rejection_issues
from scout_email.writing.schemas import DraftClaim


def test_unsupported_quantified_business_loss_is_hard_rejection():
    issues = scan_hard_rejection_issues(
        body="You're losing 40% of bookings because of this.",
        claims=[],
    )
    assert "unsupported_quantified_loss" in issues


def test_fake_familiarity_pattern_is_hard_rejection():
    issues = scan_hard_rejection_issues(
        body="I've been following your brand for months and love everything you do.",
        claims=[],
    )
    assert "fake_familiarity" in issues


def test_normal_evidence_backed_inference_does_not_trigger_hard_language_rules():
    claims = [
        DraftClaim(
            text="That may add friction for visitors trying to book.",
            claim_class=ClaimClass.REASONABLE_INFERENCE,
            evidence_ids=[4],
        )
    ]
    issues = scan_hard_rejection_issues(
        body="That may add friction for visitors trying to book.",
        claims=claims,
    )
    assert issues == []
