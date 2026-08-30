from pathlib import Path

from browser_worker.maps import extract_listing_html, extract_results_html

FIXTURES = Path(__file__).parent / "fixtures"


def read(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_results_fixture_extracts_ordered_partial_leads():
    leads = extract_results_html(read("maps_results.html"), max_results=10)
    assert [lead.name for lead in leads] == ["ABC Dental Clinic", "Smile Care"]
    assert leads[0].rating == 4.7
    assert leads[0].review_count == 123
    assert leads[0].maps_url.startswith("https://www.google.com/maps/place/")
    assert leads[1].rating is None
    assert leads[1].review_count is None


def test_listing_extracts_contact_and_listing_fields():
    lead = extract_listing_html(read("maps_listing.html"))
    assert lead.name == "ABC Dental Clinic"
    assert lead.category == "Dentist"
    assert lead.address == "12 Main Boulevard, Gulberg, Lahore"
    assert lead.phone == "+92 300 1234567"
    assert lead.website == "https://abc-dental.pk/"
    assert lead.rating == 4.7
    assert lead.review_count == 123
    assert lead.source_external_id == "0xabc:0x123"


def test_listing_missing_optional_fields_is_still_valid():
    lead = extract_listing_html(read("maps_listing_minimal.html"))
    assert lead.name == "Corner Bakery"
    assert lead.category == "Bakery"
    assert lead.phone is None
    assert lead.website is None
    assert lead.rating is None
    assert lead.review_count is None
    assert lead.source_external_id == "0xbeef:0xcafe"


def test_results_respects_max_results():
    leads = extract_results_html(read("maps_results.html"), max_results=1)
    assert len(leads) == 1
