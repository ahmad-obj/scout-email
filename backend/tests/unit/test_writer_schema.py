import pytest
from pydantic import ValidationError

from scout_email.common.enums import ClaimClass
from scout_email.writing.schemas import DraftClaim, EmailDraftOutput


def test_observed_claim_requires_evidence_ids():
    with pytest.raises(ValidationError):
        DraftClaim(
            text="The mobile booking CTA is below the fold.",
            claim_class=ClaimClass.OBSERVED_FACT,
            evidence_ids=[],
        )


def test_reasonable_inference_requires_evidence_and_probabilistic_language():
    with pytest.raises(ValidationError):
        DraftClaim(
            text="This loses customers.",
            claim_class=ClaimClass.REASONABLE_INFERENCE,
            evidence_ids=[7],
        )

    claim = DraftClaim(
        text="This may add friction for visitors trying to book on mobile.",
        claim_class=ClaimClass.REASONABLE_INFERENCE,
        evidence_ids=[7],
    )
    assert claim.evidence_ids == [7]


def test_unverified_claim_is_invalid_for_writer_output():
    with pytest.raises(ValidationError):
        DraftClaim(
            text="They probably lose 40% of bookings.",
            claim_class=ClaimClass.UNVERIFIED,
            evidence_ids=[],
        )


def test_final_draft_carries_prompt_and_playbook_versions():
    output = EmailDraftOutput(
        subject="Mobile booking thought",
        body="Short evidence-backed email body.",
        claims=[
            {
                "text": "The booking CTA is difficult to spot on mobile.",
                "claim_class": "OBSERVED_FACT",
                "evidence_ids": [3],
            }
        ],
        strategy_label="CONVERSION_PROBLEM",
        prompt_version="writer:v1",
        playbook_hash="a" * 64,
    )
    assert output.playbook_hash == "a" * 64
