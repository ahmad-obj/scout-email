from scout_email.leads.dedupe import match_existing_lead
from scout_email.leads.schemas import ExistingLead, NormalizedLead


def n(name, phone=None, domain=None, city="Lahore"):
    return NormalizedLead(name=name, normalized_name=name.casefold(), phone=phone, canonical_domain=domain, city=city)


def test_exact_phone_outranks_fuzzy_name():
    candidate = n("ABC Dental Clinic", "+923001234567", "newsite.pk")
    existing = [
        ExistingLead(id=1, **n("ABC Dental", "+923001234567", "olddomain.pk").model_dump()),
        ExistingLead(id=2, **n("ABC Dental Clinic Lahore", "+923009999999", "different.pk").model_dump()),
    ]
    result = match_existing_lead(candidate, existing)
    assert result is not None
    assert result.lead_id == 1
    assert result.reason == "exact_phone"


def test_exact_domain_matches_despite_name_variation():
    candidate = n("ABC Smiles", None, "abc.pk")
    existing = [ExistingLead(id=7, **n("ABC Dental Centre", None, "abc.pk").model_dump())]
    assert match_existing_lead(candidate, existing).lead_id == 7


def test_similar_name_with_conflicting_phone_and_domain_does_not_merge():
    candidate = n("ABC Dental Clinic", "+923001111111", "abc-new.pk")
    existing = [ExistingLead(id=1, **n("ABC Dental Clinic Lahore", "+923002222222", "abc-old.pk").model_dump())]
    assert match_existing_lead(candidate, existing) is None


def test_fuzzy_name_can_match_only_without_identifier_conflict_and_same_city():
    candidate = n("Smile Dental Clinic", None, None, "Lahore")
    existing = [ExistingLead(id=4, **n("Smile Dental Clinc", None, None, "Lahore").model_dump())]
    result = match_existing_lead(candidate, existing)
    assert result is not None and result.reason == "fuzzy_name_city"
