from scout_email.crawl.audit import audit_page
from scout_email.crawl.extract import extract_page


def test_audit_page_reports_only_deterministic_technical_facts():
    html = """
    <html>
      <head>
        <title>Acme Dental Lahore</title>
        <meta name="description" content="Family and cosmetic dental care in Lahore">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link rel="canonical" href="/">
        <link rel="icon" href="/favicon.ico">
        <meta property="og:title" content="Acme Dental Lahore">
        <script type="application/ld+json">{"@type":"Dentist"}</script>
        <style>@media (max-width: 700px) { .hero { display:block; } }</style>
      </head>
      <body>
        <main>
          <h1>Acme Dental</h1>
          <a href="/appointments">Book appointment</a>
          <button>Request consultation</button>
          <a href="/services">Our services</a>
          <a href="https://instagram.com/acmedental">Instagram</a>
          <a href="https://www.linkedin.com/company/acme-dental">LinkedIn</a>
          <img src="/hero.webp" width="1600" height="900" alt="Clinic">
          <img src="/doctor.webp" alt="Dentist">
        </main>
      </body>
    </html>
    """

    audit = audit_page(html, "https://example.com/", http_status=200)

    assert audit.http_status == 200
    assert audit.uses_https is True
    assert audit.title == "Acme Dental Lahore"
    assert audit.title_present is True
    assert audit.meta_description == "Family and cosmetic dental care in Lahore"
    assert audit.missing_meta_description is False
    assert audit.has_viewport is True
    assert audit.has_responsive_indicators is True
    assert audit.canonical == "https://example.com/"
    assert audit.has_open_graph is True
    assert audit.has_structured_data is True
    assert audit.has_favicon is True
    assert audit.cta_count == 2
    assert audit.social_links == [
        "https://instagram.com/acmedental",
        "https://www.linkedin.com/company/acme-dental",
    ]
    assert audit.image_count == 2
    assert audit.declared_image_dimension_count == 1
    assert audit.page_weight_bytes == len(html.encode("utf-8"))


def test_audit_page_reports_missing_metadata_without_subjective_judgment():
    html = "<html><body><main><h1>Acme</h1><p>Dental care.</p></main></body></html>"

    audit = audit_page(html, "http://example.com/services", http_status=200)

    assert audit.uses_https is False
    assert audit.title is None
    assert audit.title_present is False
    assert audit.meta_description is None
    assert audit.missing_meta_description is True
    assert audit.has_viewport is False
    assert audit.has_responsive_indicators is False
    assert audit.canonical is None
    assert audit.has_open_graph is False
    assert audit.has_structured_data is False
    assert audit.has_favicon is False
    assert audit.cta_count == 0
    assert audit.social_links == []
    assert audit.image_count == 0
    assert audit.declared_image_dimension_count == 0


def test_extract_page_embeds_audit_facts_in_technical_signals():
    html = """
    <html>
      <head>
        <title>Acme</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <script type="application/ld+json">{"@type":"Organization"}</script>
      </head>
      <body><main><a href="/contact">Contact us</a></main></body>
    </html>
    """

    page = extract_page(html, "https://example.com/", http_status=200)

    assert page.technical_signals["http_status"] == 200
    assert page.technical_signals["uses_https"] is True
    assert page.technical_signals["title_present"] is True
    assert page.technical_signals["has_viewport"] is True
    assert page.technical_signals["has_structured_data"] is True
    assert page.technical_signals["cta_count"] == 1
