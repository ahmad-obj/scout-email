from scout_email.leads.scoring import score_lead
from scout_email.leads.schemas import NormalizedLead


def test_score_is_decomposable_and_total_equals_components():
    lead = NormalizedLead(
        name="ABC Dental", normalized_name="abc dental", category="Dentist", city="Lahore",
        phone="+923001234567", canonical_domain="abc.pk", rating=4.6, review_count=120,
    )
    score = score_lead(lead)
    assert score.total == sum(score.components.values())
    assert score.components["website_present"] > 0
    assert score.components["established_reviews"] > 0
    assert score.components["high_value_service"] > 0


def test_score_does_not_depend_on_llm_or_randomness():
    lead = NormalizedLead(name="Tiny Shop", normalized_name="tiny shop", category="Shop", city="Lahore")
    assert score_lead(lead) == score_lead(lead)
