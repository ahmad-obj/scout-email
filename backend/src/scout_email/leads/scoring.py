from __future__ import annotations

from scout_email.leads.schemas import LeadScore, NormalizedLead

_HIGH_VALUE_TERMS = {
    "dentist", "dental", "clinic", "medical", "law", "lawyer", "attorney",
    "real estate", "property", "architect", "construction", "school", "academy",
    "manufacturer", "consultant", "salon", "spa", "hotel",
}


def score_lead(lead: NormalizedLead) -> LeadScore:
    category = (lead.category or "").casefold()
    reviews = lead.review_count or 0
    rating = lead.rating or 0.0
    components = {
        "website_present": 20 if lead.canonical_domain else 0,
        "phone_present": 8 if lead.phone else 0,
        "established_reviews": 20 if reviews >= 100 else 12 if reviews >= 25 else 5 if reviews >= 5 else 0,
        "strong_rating": 10 if rating >= 4.3 and reviews >= 5 else 5 if rating >= 4.0 and reviews >= 5 else 0,
        "high_value_service": 15 if any(term in category for term in _HIGH_VALUE_TERMS) else 0,
        "location_present": 5 if lead.city or lead.address else 0,
    }
    return LeadScore(total=sum(components.values()), components=components)
