from scout_email.enrichment.contacts import extract_public_contacts
from scout_email.enrichment.social import discover_social_profiles


def test_contact_requires_public_source_and_preserves_provenance():
    html = """
    <html><body>
      <a href="mailto:Hello@Example.com">Email us</a>
      <p>For general inquiries: hello@example.com</p>
    </body></html>
    """
    contacts = extract_public_contacts(html, "https://example.com/contact")
    assert len(contacts) == 1
    assert contacts[0].email == "hello@example.com"
    assert contacts[0].source_url == "https://example.com/contact"
    assert contacts[0].contact_type == "business"
    assert contacts[0].confidence == 1.0


def test_contact_extractor_never_guesses_address_from_names():
    html = "<h1>Acme Dental</h1><p>Owner: Jane Smith</p><p>Call us today.</p>"
    assert extract_public_contacts(html, "https://acme.example/about") == []


def test_visible_public_email_can_be_extracted_without_mailto():
    html = "<p>Write to bookings@example.com for appointments.</p>"
    contacts = extract_public_contacts(html, "https://example.com/contact")
    assert [contact.email for contact in contacts] == ["bookings@example.com"]
    assert contacts[0].confidence < 1.0


def test_social_profiles_preserve_the_page_that_exposed_them():
    html = """
    <a href="https://instagram.com/acme/">Instagram</a>
    <a href="https://www.facebook.com/acme">Facebook</a>
    <a href="https://www.linkedin.com/company/acme">LinkedIn</a>
    """
    profiles = discover_social_profiles(html, "https://example.com/")
    assert {profile.network for profile in profiles} == {"instagram", "facebook", "linkedin"}
    assert all(profile.source_url == "https://example.com/" for profile in profiles)
    assert all(profile.verified is True for profile in profiles)
