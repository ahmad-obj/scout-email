import pytest
from pydantic import ValidationError

from scout_email.research.schemas import EvidenceFinding, ResearchOutput


def _valid_output() -> dict:
    return {
        "business": {
            "name": "Acme Dental",
            "summary": "A dental clinic serving local patients.",
            "category": "Dentist",
            "location": "Lahore",
        },
        "business_model": {
            "target_customers": ["patients"],
            "offerings": ["family dentistry"],
            "primary_conversion": "book appointment",
        },
        "presence": {"website_state": "LIVE", "social_profiles": []},
        "strengths": [{"text": "Clear service positioning", "evidence_ids": [1]}],
        "website_findings": [{"text": "Booking CTA is weak", "evidence_ids": [2]}],
        "technical_findings": [],
        "contact": {"contact_id": 7},
        "confidence": 0.9,
        "outcome": "COMPLETE",
    }


def test_research_confidence_is_bounded_zero_to_one():
    payload = _valid_output()
    payload["confidence"] = 1.01
    with pytest.raises(ValidationError):
        ResearchOutput.model_validate(payload)


def test_findings_require_persisted_evidence_ids():
    with pytest.raises(ValidationError):
        EvidenceFinding(text="Generic claim", evidence_ids=[])


def test_contact_is_a_persisted_reference_not_free_form_email():
    payload = _valid_output()
    payload["contact"] = {"email": "invented@example.com"}
    with pytest.raises(ValidationError):
        ResearchOutput.model_validate(payload)


def test_research_outcome_is_closed_enum():
    payload = _valid_output()
    payload["outcome"] = "MAYBE"
    with pytest.raises(ValidationError):
        ResearchOutput.model_validate(payload)
