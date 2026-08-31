from scout_email.messaging.eligibility import (
    normalize_business_identity,
    normalize_domain_identity,
    normalize_email_identity,
)


def test_dnc_identity_normalization_is_canonical():
    assert normalize_email_identity(" Owner@Example.COM ") == "owner@example.com"
    assert normalize_domain_identity(" WWW.Example.COM. ") == "example.com"
    assert normalize_domain_identity("https://www.Example.com/contact") == "example.com"
    assert normalize_business_identity("  ACME   Dental  ") == "acme dental"
