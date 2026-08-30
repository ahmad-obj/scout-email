from scout_email.leads.normalize import canonical_domain, normalize_name, normalize_phone, normalize_lead
from scout_email.leads.schemas import RawLead


def test_domain_canonicalization():
    assert canonical_domain("https://www.Example.com/about?x=1") == "example.com"
    assert canonical_domain("example.com/") == "example.com"


def test_phone_normalization_keeps_country_code():
    assert normalize_phone("+92 300-1234567") == "+923001234567"


def test_name_normalization_is_stable_not_destructive():
    assert normalize_name("  ABC   Dental & Clinic  ") == "abc dental clinic"


def test_normalize_lead_preserves_original_name_and_canonical_fields():
    lead = normalize_lead(RawLead(name=" ABC Dental ", phone="+92 300 1234567", website="https://www.ABC.pk/contact"))
    assert lead.name == "ABC Dental"
    assert lead.normalized_name == "abc dental"
    assert lead.phone == "+923001234567"
    assert lead.canonical_domain == "abc.pk"
