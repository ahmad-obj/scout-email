import pytest
from pydantic import ValidationError

from scout_email.strategy.schemas import OpportunityScoreComponents, StrategyOutput


def _score() -> dict:
    return {
        "severity": 0.8,
        "evidence_confidence": 0.9,
        "business_impact": 0.8,
        "weberaise_fit": 0.95,
        "explainability": 0.9,
        "generic_speculation_risk": 0.1,
    }


def test_strategy_json_schema_requires_control_critical_fields():
    schema = StrategyOutput.model_json_schema()

    required = set(schema["required"])
    assert {
        "decision",
        "candidates",
        "persuasion_brief",
        "supporting_evidence_ids",
        "score_components",
        "confidence",
        "rationale",
    } <= required

    candidate_required = set(schema["$defs"]["OpportunityCandidate"]["required"])
    assert "safe_to_reference" in candidate_required


def test_contact_requires_supporting_evidence():
    with pytest.raises(ValidationError):
        StrategyOutput(
            decision="CONTACT",
            candidates=[],
            persuasion_brief={
                "primary_angle": "booking friction",
                "do_not_use": ["unsupported revenue claims"],
            },
            supporting_evidence_ids=[],
            score_components=_score(),
            confidence=0.9,
            rationale="Strong fit",
        )


def test_contact_requires_exactly_one_primary_angle_and_score():
    output = StrategyOutput(
        decision="CONTACT",
        candidates=[
            {
                "problem": "Booking CTA is difficult to notice on mobile.",
                "angle": "Reduce mobile booking friction.",
                "evidence_ids": [11],
                "score": _score(),
                "safe_to_reference": True,
            }
        ],
        persuasion_brief={
            "primary_angle": "booking friction",
            "do_not_use": ["SEO claims"],
        },
        supporting_evidence_ids=[11],
        score_components=_score(),
        confidence=0.9,
        rationale="Strong fit",
    )
    assert output.persuasion_brief is not None
    assert output.persuasion_brief.primary_angle == "booking friction"


def test_opportunity_overall_score_is_derived_not_model_supplied():
    low_risk = OpportunityScoreComponents(**_score())
    high_risk_payload = _score()
    high_risk_payload["generic_speculation_risk"] = 1.0
    high_risk = OpportunityScoreComponents(**high_risk_payload)

    assert 0 <= low_risk.overall_score <= 1
    assert 0 <= high_risk.overall_score <= 1
    assert low_risk.overall_score > high_risk.overall_score


def test_score_components_are_bounded():
    payload = _score()
    payload["severity"] = 1.1
    with pytest.raises(ValidationError):
        OpportunityScoreComponents(**payload)


def test_decision_is_closed_enum():
    with pytest.raises(ValidationError):
        StrategyOutput(
            decision="EMAIL_ANYWAY",
            candidates=[],
            persuasion_brief=None,
            supporting_evidence_ids=[],
            score_components=None,
            confidence=0.5,
            rationale="No",
        )
